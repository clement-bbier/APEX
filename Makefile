.PHONY: help lint fmt test test-unit test-int build-rust fixtures backtest up up-win check-docker down logs download-all clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS=":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Code quality ──────────────────────────────────────────────────────────────

lint: ## Run ruff check + mypy + bandit
	ruff check . && ruff format --check . && mypy . --ignore-missing-imports && bandit -r . -x tests/ -c pyproject.toml

fmt: ## Auto-format with ruff
	ruff format . && ruff check . --fix

# ── Tests ─────────────────────────────────────────────────────────────────────

test: ## Run all tests
	pytest tests/ -v

test-unit: ## Run unit tests only (no docker needed)
	pytest tests/unit/ -v --override-ini="addopts="

test-int: ## Run integration tests (requires docker)
	docker compose -f docker/docker-compose.test.yml up -d
	pytest tests/integration/ -v --timeout=60
	docker compose -f docker/docker-compose.test.yml down -v

# ── Rust ──────────────────────────────────────────────────────────────────────

build-rust: ## Build and install Rust extensions (apex_mc + apex_risk)
	cd rust && cargo test --workspace
	cd rust/apex_mc && maturin build --release
	cd rust/apex_risk && maturin build --release
	pip install rust/target/wheels/*.whl
	python -c "from apex_mc import run_mc_batch, compute_var, compute_cvar; print('apex_mc OK')"
	python -c "from apex_risk import compute_exposure; print('apex_risk OK')"

# ── Fixtures ──────────────────────────────────────────────────────────────────

fixtures: ## Generate synthetic test fixtures for CI
	python scripts/generate_test_fixtures.py

backtest: fixtures ## Run regression backtest on synthetic fixture (local dev mode)
	BACKTEST_MODE=true BACKTEST_MIN_SHARPE=-999 BACKTEST_MAX_DD=1.0 PYTHONPATH=. python scripts/backtest_regression.py --fixture tests/fixtures/30d_btcusdt_1m.parquet

# ── Docker / services ─────────────────────────────────────────────────────────

up: ## Start full APEX trading stack
	docker compose -f docker/docker-compose.yml up -d

up-win: ## Start stack on Windows (explicit linux/amd64 platform)
	DOCKER_DEFAULT_PLATFORM=linux/amd64 docker compose -f docker/docker-compose.yml up -d

check-docker: ## Verify Docker Desktop is running
	@docker info > /dev/null 2>&1 && echo "Docker OK" || echo "ERROR: Docker Desktop is not running"

down: ## Stop all services
	docker compose -f docker/docker-compose.yml down

logs: ## Follow service logs (last 100 lines)
	docker compose -f docker/docker-compose.yml logs -f --tail=100

# ── Setup ────────────────────────────────────────────────────────────────────

download-all: ## Download 1yr BTC/USDT + ETH/USDT real data from Binance (no API key needed)
	PYTHONPATH=. python scripts/download_history.py --years 1

install: ## Install Python dependencies
	pip install -r requirements.txt

validate: ## Run pre-flight connectivity checks
	python scripts/validate_setup.py

# ── Clean ─────────────────────────────────────────────────────────────────────

clean: ## Remove Python bytecode and build artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf rust/target/wheels/ .mypy_cache .ruff_cache .pytest_cache htmlcov
