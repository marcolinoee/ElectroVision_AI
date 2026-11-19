"""CLI entrypoint for ElectroVision AI Public Electrical Dataset Harvester.

Usage:
    python -m app.services.ml_ops.harvester.cli --max-mb 950
    python -m app.services.ml_ops.harvester.cli --max-mb 20 --sources wikimedia,cad_symbols
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.logging import configure_logging, get_logger
from app.services.ml_ops.harvester.config import HARD_QUOTA_BYTES, HarvesterConfig
from app.services.ml_ops.harvester.pipeline import DatasetHarvesterPipeline

logger = get_logger(__name__)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="electrovision-harvester",
        description="Coleta massiva auditável de dados públicos de engenharia elétrica (teto rígido 950 MB).",
    )
    parser.add_argument(
        "--max-mb",
        type=int,
        default=950,
        help="Limite máximo de disco em MB (máximo absoluto: 950 MB).",
    )
    parser.add_argument(
        "--sources",
        type=str,
        default="wikimedia,huggingface,public_yolo,cad_symbols",
        help="Lista separada por vírgula de conectores (wikimedia,huggingface,public_yolo,cad_symbols).",
    )
    parser.add_argument(
        "--max-items-per-source",
        type=int,
        default=1500,
        help="Máximo de itens tentados por conector.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Diretório de saída (padrão: storage/datasets/public_harvest).",
    )
    parser.add_argument(
        "--public-yolo-manifest",
        type=Path,
        default=None,
        help="Caminho opcional para YAML/JSON com repositórios YOLO públicos.",
    )
    parser.add_argument(
        "--cad-manifest",
        type=Path,
        default=None,
        help="Caminho opcional para YAML/JSON com repositórios CAD (.dxf/.svg).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging("INFO")
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    max_bytes = min(HARD_QUOTA_BYTES, max(1, args.max_mb) * 1024 * 1024)
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]

    kwargs: dict[str, object] = {
        "max_bytes": max_bytes,
        "enabled_sources": sources,
        "max_items_per_source": args.max_items_per_source,
        "public_yolo_manifest_path": args.public_yolo_manifest,
        "cad_symbols_manifest_path": args.cad_manifest,
    }
    if args.output_dir is not None:
        kwargs["output_dir"] = args.output_dir

    config = HarvesterConfig(**kwargs)  # type: ignore[arg-type]
    pipeline = DatasetHarvesterPipeline(
        config=config,
        progress_callback=lambda pct, msg: logger.info("harvest_progress", pct=pct, message=msg),
    )
    summary = pipeline.run(max_items_per_source=args.max_items_per_source)

    print(
        json.dumps(
            {
                "output_dir": str(summary.output_dir),
                "manifest_path": str(summary.manifest_path),
                "dataset_yaml_path": str(summary.dataset_yaml_path),
                "quota_reached": summary.quota_reached,
                "used_bytes": summary.used_bytes,
                "max_bytes": summary.max_bytes,
                "labeled_counts": summary.labeled_counts,
                "unlabeled_count": summary.unlabeled_count,
                "cad_symbols_count": summary.cad_symbols_count,
                "rejected_counts": summary.rejected_counts,
                "counts_by_source": summary.counts_by_source,
                "counts_by_class": summary.counts_by_class,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
