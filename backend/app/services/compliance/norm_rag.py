"""100% Local Normative RAG (ONNX `intfloat/multilingual-e5-small` + pgvector).

ARCHITECTURE & COPYRIGHT GUARDRAIL:
- Zero external cloud calls.
- Indexes ONLY PDFs imported locally by the user into `./storage/norms_pdfs`.
- Used strictly to attach normative citations to deterministic findings (NEVER decides compliance).
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.security import compute_sha256_file
from app.models.rule_metadata import NormChunk

logger = get_logger(__name__)

EMBEDDING_DIM: int = 384
_TOKEN_RE = re.compile(r"[a-zA-ZÀ-ÿ0-9]+")


class EmbeddingModelProtocol(Protocol):
    """Protocol for 384-d local text embedders."""

    def embed_texts(self, texts: list[str], prefix: str = "passage: ") -> list[list[float]]:
        ...


class LocalONNXEmbedder:
    """Local ONNX Runtime embedder for `intfloat/multilingual-e5-small` (384 dimensions).

    If local ONNX model files (`model.onnx` + `tokenizer.json`) are not yet provisioned
    in `storage/models_weights/e5_small_onnx`, falls back cleanly to a deterministic
    local hashed n-gram 384-d projection so tests and offline deployments never crash.
    """

    def __init__(self, model_dir: Path | None = None) -> None:
        self._model_dir = model_dir
        self._session: Any | None = None
        self._tokenizer: Any | None = None
        self._onnx_ready: bool | None = None

    def _try_init_onnx(self) -> bool:
        if self._onnx_ready is not None:
            return self._onnx_ready
        if self._model_dir is None:
            self._onnx_ready = False
            return False

        onnx_file = self._model_dir / "model.onnx"
        tok_file = self._model_dir / "tokenizer.json"
        if not onnx_file.exists() or not tok_file.exists():
            logger.info("onnx_e5_not_provisioned_using_deterministic_local_embedder", dir=str(self._model_dir))
            self._onnx_ready = False
            return False

        import onnxruntime as ort
        from tokenizers import Tokenizer

        self._tokenizer = Tokenizer.from_file(str(tok_file))
        self._tokenizer.enable_truncation(max_length=512)
        self._tokenizer.enable_padding(pad_id=1, pad_token="<pad>")
        self._session = ort.InferenceSession(str(onnx_file), providers=["CPUExecutionProvider"])
        self._onnx_ready = True
        return True

    def embed_texts(self, texts: list[str], prefix: str = "passage: ") -> list[list[float]]:
        if not texts:
            return []
        prefixed = [f"{prefix}{t}" for t in texts]
        if self._try_init_onnx() and self._session is not None and self._tokenizer is not None:
            encoded = self._tokenizer.encode_batch(prefixed)
            input_ids = np.array([e.ids for e in encoded], dtype=np.int64)
            attention_mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
            outputs = self._session.run(
                None,
                {"input_ids": input_ids, "attention_mask": attention_mask},
            )
            token_embeddings = outputs[0]  # (B, L, 384)
            mask_expanded = np.expand_dims(attention_mask, axis=-1).astype(np.float32)
            summed = np.sum(token_embeddings * mask_expanded, axis=1)
            counts = np.clip(np.sum(mask_expanded, axis=1), 1e-9, None)
            pooled = summed / counts
            norms = np.linalg.norm(pooled, axis=1, keepdims=True)
            normalized = pooled / np.clip(norms, 1e-9, None)
            return [row.astype(float).tolist() for row in normalized]

        # Deterministic offline fallback (signed feature hashing into 384-d unit sphere)
        return [_deterministic_hash_embedding(t) for t in prefixed]


def _deterministic_hash_embedding(text: str) -> list[float]:
    vec = [0.0] * EMBEDDING_DIM
    tokens = [tok.lower() for tok in _TOKEN_RE.findall(text)]
    if not tokens:
        return vec
    for tok in tokens:
        digest = hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(digest[:4], "little") % EMBEDDING_DIM
        sign = 1.0 if (digest[4] & 1) == 0 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [round(v / norm, 6) for v in vec]


def chunk_text(text: str, chunk_size: int = 700, overlap: int = 120) -> list[str]:
    """Split extracted PDF text into overlapping clean chunks."""
    cleaned = " ".join(text.split())
    if not cleaned:
        return []
    chunks: list[str] = []
    start = 0
    step = max(1, chunk_size - overlap)
    while start < len(cleaned):
        piece = cleaned[start : start + chunk_size].strip()
        if piece:
            chunks.append(piece)
        start += step
    return chunks


@dataclass(frozen=True, slots=True)
class CitationMatch:
    standard_code: str
    document_filename: str
    page_number: int
    excerpt: str
    similarity: float


async def ingest_local_norm_pdf(
    session: AsyncSession,
    pdf_path: Path,
    standard_code: str,
    embedder: EmbeddingModelProtocol | None = None,
) -> int:
    """Extract, chunk, embed locally, and store a user-supplied normative PDF in `norm_chunks`."""
    if not pdf_path.exists():
        raise FileNotFoundError(f"Normative PDF not found: {pdf_path}")

    doc_sha = compute_sha256_file(pdf_path)
    existing = await session.scalar(
        select(NormChunk.id).where(NormChunk.document_sha256 == doc_sha).limit(1)
    )
    if existing is not None:
        return 0  # Idempotent skip if exact PDF already indexed

    reader = PdfReader(str(pdf_path))
    model = embedder or LocalONNXEmbedder()

    raw_records: list[tuple[int, int, str]] = []
    for page_idx, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""
        for chunk_idx, text_chunk in enumerate(chunk_text(page_text)):
            raw_records.append((page_idx, chunk_idx, text_chunk))

    if not raw_records:
        return 0

    embeddings = model.embed_texts([rec[2] for rec in raw_records], prefix="passage: ")
    for (page_num, chunk_idx, text_chunk), emb in zip(raw_records, embeddings, strict=True):
        session.add(
            NormChunk(
                standard_code=standard_code,
                document_filename=pdf_path.name,
                document_sha256=doc_sha,
                page_number=page_num,
                chunk_index=chunk_idx,
                content=text_chunk,
                embedding=emb,
            )
        )
    await session.flush()
    return len(raw_records)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    va = np.asarray(a, dtype=np.float32)
    vb = np.asarray(b, dtype=np.float32)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    if denom <= 1e-9:
        return 0.0
    return float(np.dot(va, vb) / denom)


async def search_norm_citations(
    session: AsyncSession,
    query: str,
    standard_code: str | None = None,
    top_k: int = 3,
    embedder: EmbeddingModelProtocol | None = None,
) -> list[CitationMatch]:
    """Retrieve top-k local normative excerpts for citation support only."""
    model = embedder or LocalONNXEmbedder()
    query_vec = model.embed_texts([query], prefix="query: ")[0]

    stmt = select(NormChunk)
    if standard_code:
        stmt = stmt.where(NormChunk.standard_code == standard_code)

    dialect_name = session.bind.dialect.name if session.bind is not None else "sqlite"
    if dialect_name == "postgresql":
        distance = NormChunk.embedding.cosine_distance(query_vec)
        rows = list((await session.scalars(stmt.order_by(distance).limit(top_k))).all())
        return [
            CitationMatch(
                standard_code=row.standard_code,
                document_filename=row.document_filename,
                page_number=row.page_number,
                excerpt=row.content[:320],
                similarity=round(_cosine_similarity(query_vec, list(row.embedding)), 4),
            )
            for row in rows
        ]

    # SQLite / in-memory fallback for local tests
    rows = list((await session.scalars(stmt)).all())
    scored = [
        (row, _cosine_similarity(query_vec, list(row.embedding)))
        for row in rows
    ]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [
        CitationMatch(
            standard_code=row.standard_code,
            document_filename=row.document_filename,
            page_number=row.page_number,
            excerpt=row.content[:320],
            similarity=round(sim, 4),
        )
        for row, sim in scored[:top_k]
    ]
