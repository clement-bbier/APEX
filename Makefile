.PHONY: clean install lint type test-unit test-integration backtest preflight

PYTHON := .venv/Scripts/python.exe

clean:
	@echo ">> cleaning caches"
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@rm -rf .mypy_cache .pytest_cache .ruff_cache

install:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt
	$(PYTHON) -m pip install pytest-asyncio fakeredis bandit "maturin>=1.9.4"

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

type:
	$(PYTHON) -m mypy . --strict

test-unit:
	$(PYTHON) -m pytest tests/unit/ -v \
		--cov=services --cov=core --cov=backtesting \
		--cov-report=term-missing --cov-fail-under=40 --timeout=30

test-integration:
	$(PYTHON) -m pytest tests/integration/ -v --timeout=60

backtest:
	$(PYTHON) scripts/generate_test_fixtures.py
	$(PYTHON) scripts/backtest_regression.py --fixture tests/fixtures/30d_btcusdt_1m.parquet

preflight: lint type test-unit test-integration backtest
	@echo ""
	@echo "  APEX preflight green - safe to push"
