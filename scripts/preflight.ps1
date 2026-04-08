$ErrorActionPreference = "Stop"
$python = ".venv\Scripts\python.exe"

Write-Host ">> ruff check + format" -ForegroundColor Cyan
& $python -m ruff check .
& $python -m ruff format --check .

Write-Host ">> mypy --strict" -ForegroundColor Cyan
& $python -m mypy . --strict

Write-Host ">> bandit security scan" -ForegroundColor Cyan
& $python -m bandit -r core supervisor services backtesting -c pyproject.toml

Write-Host ">> unit tests" -ForegroundColor Cyan
& $python -m pytest tests/unit/ -v --cov=services --cov=core --cov=backtesting --cov-fail-under=40 --timeout=30

Write-Host ">> integration tests" -ForegroundColor Cyan
& $python -m pytest tests/integration/ -v --timeout=60

Write-Host ">> backtest regression gate" -ForegroundColor Cyan
& $python scripts/generate_test_fixtures.py
& $python scripts/backtest_regression.py --fixture tests/fixtures/30d_btcusdt_1m.parquet

Write-Host ""
Write-Host "  APEX preflight green - safe to push" -ForegroundColor Green
