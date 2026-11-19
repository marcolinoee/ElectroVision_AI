# ElectroVision AI

Plataforma **100% local-first**, determinística e auditável de **Engenharia Elétrica Diagnóstica e Projetos Automatizados por Visão Computacional** (NBR 5410 / NR-10 / NBR 14039).

## Arquitetura & Topologia de Containers

| Serviço | Stack | Filas / Porta Host |
| :--- | :--- | :--- |
| `frontend` (`ev_frontend`) | Next.js 14 (App Router), TypeScript, TailwindCSS, `react-konva` (`ssr: false`), Zustand + Zundo (Undo/Redo), SSE | `http://localhost:3030` |
| `api` (`ev_api`) | FastAPI, SQLAlchemy 2.0 Async, Alembic, `structlog`, SSE | `http://localhost:8030` |
| `worker-ml` (`ev_worker_ml`) | Celery, PyTorch (CPU padrão / GPU override), Ultralytics YOLO, EasyOCR, OpenCV | `vision_queue`, `train_queue` |
| `worker-engine` (`ev_worker_engine`) | Celery, `ezdxf` (`ezdxf.audit()`), `python-docx`, `openpyxl`, ONNX (`multilingual-e5-small`) | `engine_queue` |
| `postgres` (`ev_postgres`) | PostgreSQL 16 + `pgvector` | `localhost:5435` |
| `redis` (`ev_redis`) | Redis 7 (Broker/Backend Celery + Pub/Sub SSE) | `localhost:6380` |

## Guardrails de Engenharia & Segurança

- **Sign-Off Humano Obrigatório (CREA/ART):** Máquina de estados rígida `DRAFT -> AI_PROCESSED -> ENGINEER_VALIDATED -> EXPORTED`. Exportações oficiais (`.DXF`, `.SVG`, `.DOCX`, `.XLSX`) são bloqueadas (`HTTP 403`) sem validação humana de todos os itens com confiança `< 0.80` e registro de hash **SHA-256** vinculando o `DigitalTwinJSON` aos artefatos (`export_manifest.json`).
- **Visão Computacional & Active Learning Blindado:** Pré-processamento obrigatório (constância de cor + *deskew*) antes de OCR e análise de cores de cabos (azul-claro Neutro / verde PE). Promoção atômica (`.tmp -> os.replace`) de pesos `.pt` condicionada a ganho em `mAP50-95` no *Golden Holdout Set* fixo e `Recall >= 0.95` em `IDR`, `DPS` e `Disjuntor`.
- **Motor Determinístico vs. RAG:** Conformidade NBR 5410 / NR-10 / NBR 14039 avaliada exclusivamente de forma determinística. O `pgvector` armazena apenas trechos de PDFs importados localmente pelo usuário (sem texto integral protegido da ABNT nos seeds).
- **CAD Auditado:** Todo `.DXF` gerado (Diagrama Unifilar ou Planta Elétrica condicionada a `.DXF` arquitetônico base calibrado) passa obrigatoriamente por `ezdxf.audit()` com 0 erros antes da escrita atômica.
- **AppSec de Mídia:** Validação por *magic bytes*, limites de tamanho, proteção contra *decompression bombs* e sanitização contra *Path Traversal*.

## Como Executar Localmente

```bash
# 1. Subir stack completa (CPU padrão)
docker compose -f docker-compose.yml up --build -d

# (Opcional) Subir com GPU NVIDIA explícita
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build -d

# 2. Aplicar migrações Alembic (PostgreSQL 16 + pgvector) e seeds (metadados normativos + SINAPI)
docker compose exec api alembic upgrade head
docker compose exec api python -m app.seeds.run_seeds
```

- **Frontend:** `http://localhost:3030`
- **API / Swagger:** `http://localhost:8030/docs`

## Testes Automatizados

```bash
# Backend (36 testes: contratos, máquina de estados, AppSec, visão, MLOps, NBR 5410, ezdxf.audit, DOCX/XLSX/SHA-256)
cd backend
uv run --extra dev --extra engine pytest -v
uv run --extra dev ruff check app tests

# Frontend (TypeScript + Next.js 14 production build)
cd frontend
npm run typecheck
npm run build
```
