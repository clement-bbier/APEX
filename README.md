# APEX Trading System (CashMachine)

Autonomous quantitative trading engine — hedge fund grade.
**Objective: maximize alpha through systematic, continuously adaptive signal generation.**

## Architecture

10 microservices connected via ZeroMQ + Redis:

```
S01 Data -> S02 Signal -> S03 Regime -> S04 Fusion -> S05 Risk -> S06 Execution
                                            ^               ^
                            S07 Analytics   S08 Macro   S09 Feedback   S10 Monitor
```

## Quick Start

### Prerequisites

- Python 3.12+
- Rust (stable) + maturin
- Docker Desktop
- Redis (via Docker)

### Setup

```bash
# 1. Clone and enter
git clone https://github.com/clement-bbier/CashMachine.git
cd CashMachine

# 2. Create virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Build Rust extensions
make build-rust

# 5. Configure
cp .env.example .env
# Edit .env with your API keys
```

### Paper Trading (no real money)

```bash
# Verify Docker is running
make check-docker

# Start full stack
make up        # Linux/Mac
make up-win    # Windows

# Monitor dashboard
# Open http://localhost:8080
```

### Backtesting

```bash
# Download real historical data (no API key needed)
make download-all

# Or use synthetic fixtures for quick validation
make backtest
```

### Development

```bash
make lint        # ruff + mypy + bandit
make test-unit   # fast unit tests (no Docker needed)
make test-int    # integration tests (requires Docker)
```

## Status

See MANIFEST.md for full specification, roadmap, and mathematical foundations.

Paper -> Live criteria: 3 months profitable, Sharpe > 1.5, max DD < 5%.
