# Polygon Connector

Wraps [polygon-api-client](https://pypi.org/project/polygon-api-client/)
as a `MarketDataProvider` implementation. Market data only — Polygon does
not offer brokerage / execution.

## Role
- Broad US-equity + crypto historical coverage (minute + daily bars).
- Free "starter" tier gives 2 years of historical equity bars and
  end-of-day data — enough for research, IC computation, and short
  walk-forward windows.
- Complements Alpaca during Phase B: Alpaca for paper execution + live
  data, Polygon for deeper historical research.

## Activation

1. Install the SDK extra:
   ```
   pip install -e ".[connectors-polygon]"
   ```
2. Sign up at <https://polygon.io/dashboard>, generate an API key.
3. Export the key:
   ```
   export APEX_POLYGON_API_KEY="..."
   ```
4. Minimal usage (Phase B Gate 2A):
   ```python
   from connectors.polygon import PolygonConfig, PolygonConnector
   from pydantic import SecretStr
   import os

   cfg = PolygonConfig(api_key=SecretStr(os.environ["APEX_POLYGON_API_KEY"]))
   mkt = PolygonConnector(cfg)
   # await mkt.get_historical_bars("AAPL", start, end, "1d")  # Phase B
   ```

## Known limitations (free starter tier)
- No live trade execution (Polygon is a data vendor, not a broker).
- Free tier: 5 req/min rate cap on the REST API — for heavy historical
  pulls, upgrade to the paid tier or page slowly.
- Real-time websocket feed requires paid "stocks" or "crypto" plan.
- Option chain data requires the options plan (paid).

## Testing approach
- Unit tests (`connectors/tests/test_polygon_init.py`): instantiate
  with a dummy `PolygonConfig`, assert every method raises
  `NotImplementedError`.
- Live integration tests (Phase B): gated by `APEX_POLYGON_API_KEY`;
  skip cleanly when absent.
- Protocol conformance: `isinstance(PolygonConnector(cfg),
  MarketDataProvider)` must hold at the type level. The type-checker
  must NOT allow `PolygonConnector` to be passed where
  `ExecutionProvider` is required.
