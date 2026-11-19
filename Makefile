.PHONY: up up-gpu down logs migrate seed test lint lock init-storage

init-storage:
	@mkdir -p storage/uploads storage/proxies storage/frames storage/datasets storage/golden_set storage/models_weights storage/exports storage/norms_pdfs

up: init-storage
	docker compose -f docker-compose.yml up --build -d

up-gpu: init-storage
	docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build -d

down:
	docker compose -f docker-compose.yml down

logs:
	docker compose -f docker-compose.yml logs -f

migrate:
	docker compose exec api alembic upgrade head

seed:
	docker compose exec api python -m app.seeds.run_seeds

lock:
	cd backend && uv lock

test:
	cd backend && uv run --extra dev pytest -v

lint:
	cd backend && uv run --extra dev ruff check app tests
