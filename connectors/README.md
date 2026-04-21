# APEX Connectors

Provider-agnostic market-data and execution boundary. Concrete
implementations of `MarketDataProvider` / `ExecutionProvider` /
`BrokerProvider` (see [`protocol.py`](protocol.py)) live under
`connectors/alpaca/`, `connectors/ibkr/`, and `connectors/polygon/`.

Everything below the `connectors/` tree is **pure adapter layer**. No
service, no core model, and no trading strategy imports an SDK
directly — they import from `connectors.*`.

## Current status

All three connectors are **stubs** as of 2026-04-21. Every method
raises `NotImplementedError` with a pointer to the Phase B gate that
will implement it. This PR sets up:
- The `Protocol` surface every connector must satisfy.
- Pydantic models (`Tick`, `Bar`, `OrderRequest`, `OrderStatus`,
  `Position`, `Account`) that cross the boundary.
- Three config shapes with `SecretStr`-protected credentials.
- `pyproject.toml` optional-dependency extras so that only the SDKs
  you actually use get installed.

## Comparison matrix

| Feature                | Alpaca           | IBKR                    | Polygon         | Databento (future) |
|---                     |---               |---                      |---              |---                 |
| Equity US live ticks   | free             | with account            | free tier (delayed) | premium        |
| Equity US historical   | 5y free          | on demand               | 2y free         | full history       |
| Crypto                 | live + paper     | no                      | limited         | yes                |
| FX                     | no               | yes                     | no              | yes                |
| Options                | limited          | full chain              | paid add-on     | yes                |
| Paper execution        | built-in         | built-in                | no (data only)  | no                 |
| Tick-by-tick L3        | no               | no                      | no              | yes                |
| Cost per month         | free             | free (with IB account)  | free starter / $199 pro | ~$2000+  |
| Setup complexity       | low              | medium (TWS must run)   | low             | medium (contract)  |
| Best for               | quick paper start, Phase B Gate 2A | multi-asset coverage, Phase B Gate 3 | historical research | institutional microstructure, Phase C |

## Recommendation

- **Phase B Gate 2A** — start with **Alpaca**. Free, real-time paper
  trading, covers equity US + crypto, zero infrastructure (no TWS).
  Gate 2A paper trading and initial live smoke tests can happen against
  a single Alpaca account.
- **Phase B Gate 3** — add **IBKR**. Unlocks FX, international equity,
  futures, and the full option chain. Requires TWS / IB Gateway in the
  deployment topology; plan for the extra container.
- **Phase C** — consider migrating hot-path microstructure signals
  (OFI, CVD, Kyle lambda) onto **Databento** for tick-by-tick L3
  depth. Budget ~$2000+/month — only justify when quant edge is proven.

## Installing SDKs

```bash
# Phase B Gate 2A: just Alpaca (and optionally Polygon for research)
pip install -e ".[connectors-alpaca]"
pip install -e ".[connectors-polygon]"

# Phase B Gate 3: add IBKR
pip install -e ".[connectors-ibkr]"

# Everything:
pip install -e ".[connectors-alpaca,connectors-ibkr,connectors-polygon]"
```

## Test strategy

Unit-level tests (in `connectors/tests/`) cover:
- Protocol conformance (type-checker `isinstance(...)` runtime
  validation).
- Connector construction with dummy configs.
- The `NotImplementedError` contract: every method on every stub must
  raise with a clear "Phase B" message (so orchestration code never
  silently succeeds against a stub).

Live integration tests are gated by per-provider env vars
(`APEX_ALPACA_API_KEY`, `APEX_IBKR_LIVE`, `APEX_POLYGON_API_KEY`) and
will be added in the relevant Phase B gate PRs.
