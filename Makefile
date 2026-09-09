.PHONY: dev dev-build dev-ollama dev-full down test lint typecheck build clean fmt init migrate

# --- Setup ---

init: ## Interactive setup — choose providers, create config
	@python3 -m bitmod.cli init

# --- Development ---

dev: ## Start core services (SQLite, bring-your-own LLM)
	docker compose up

dev-build: ## Start core services (rebuild images)
	docker compose up --build

dev-ollama: ## Start with local Ollama (no API keys needed)
	docker compose --profile ollama up --build

dev-full: ## Start everything (Ollama + Postgres + Redis)
	docker compose --profile ollama --profile postgres up --build

dev-local: ## Start all services bare-metal (no Docker)
	@lsof -ti:3000 -ti:8000 -ti:8001 | xargs kill -9 2>/dev/null || true
	@echo "Starting chat service on :8001..."
	@cd services/chat && python3 -m uvicorn app.main:app --port 8001 --reload &
	@echo "Starting gateway on :8000..."
	@cd services/gateway && python3 -m uvicorn app.main:app --port 8000 --reload &
	@echo "Starting frontend on :3000..."
	@cd services/frontend && rm -rf .next && npx next dev &
	@echo "All services starting. Gateway: http://localhost:8000  Frontend: http://localhost:3000"

down: ## Stop all services
	docker compose --profile ollama --profile postgres down

down-local: ## Kill bare-metal dev processes
	@lsof -ti:3000 -ti:8000 -ti:8001 | xargs kill -9 2>/dev/null || true
	@echo "All local services stopped."

# --- Database ---

migrate: ## Run database migrations locally
	python3 -m bitmod.cli migrate

# --- Quality ---

lint: ## Run ruff linter
	ruff check core/ services/gateway/ services/chat/

fmt: ## Auto-format code with ruff
	ruff format core/ services/gateway/ services/chat/
	ruff check --fix core/ services/gateway/ services/chat/

typecheck: ## Run mypy type checker on core library
	mypy core/bitmod/ --ignore-missing-imports

test: ## Run pytest with coverage
	pytest tests/ -v --cov=bitmod --cov-report=term-missing

test-db-up: ## Start throwaway PostgreSQL + MySQL for backend tests
	docker compose -f docker-compose.test.yml up -d --wait

test-db-down: ## Stop and remove the test databases
	docker compose -f docker-compose.test.yml down -v

test-all-backends: test-db-up ## Run the suite against SQLite, PostgreSQL and MySQL
	BITMOD_TEST_POSTGRES=1 \
	DATABASE_URL=postgresql://bitmod:bitmod@localhost:5433/bitmod_test \
	BITMOD_TEST_MYSQL=1 \
	MYSQL_URL=mysql+pymysql://bitmod:bitmod@localhost:3307/bitmod_test \
	pytest tests/test_backend_search_integration.py tests/test_source_verification.py tests/test_session_resolution.py tests/test_qualification_gate.py tests/test_fuzzy_matching.py tests/test_threshold_config.py tests/test_text_search.py tests/test_packaging.py tests/test_section_hash_batching.py -v

# --- Build ---

build: ## Build Python package
	python -m build core/

# --- Cleanup ---

clean: ## Remove build artifacts and caches
	rm -rf core/dist/ core/build/ core/*.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true

clean-docker: ## Remove Docker volumes and images
	docker compose --profile ollama --profile postgres down -v --rmi local

# --- Help ---

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
