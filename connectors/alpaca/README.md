# Alpaca Connector

Wraps [alpaca-py](https://pypi.org/project/alpaca-py/) as a
`BrokerProvider` implementation (market data + execution).

## Role
- Equity US: live ticks, minute bars, 5y of historical bars.
- Crypto: 24/7 live ticks + paper execution (BTC, ETH, top ~20 pairs).
- Paper trading: first-class, free, no account balance required.

## Activation

1. Install the SDK extra:
   ```
   pip install -e ".[connectors-alpaca]"
   ```
2. Create a paper account at <https://app.alpaca.markets/paper/dashboard/overview>
   and generate API keys.
3. Export keys (preferred over writing them into `config.yaml`):
   ```
   export APEX_ALPACA_API_KEY="..."
   export APEX_ALPACA_API_SECRET="..."
   ```
4. Minimal usage (Phase B Gate 2A will wire this into `services/data/` and
   `services/execution/`):
   ```python
   from connectors.alpaca import AlpacaConfig, AlpacaConnector
   from pydantic import SecretStr
   import os

   cfg = AlpacaConfig(
       api_key=SecretStr(os.environ["APEX_ALPACA_API_KEY"]),
       api_secret=SecretStr(os.environ["APEX_ALPACA_API_SECRET"]),
   )
   broker = AlpacaConnector(cfg)
   # broker.submit_order(...)  # Phase B Gate 2A
   ```

## Known limitations (free tier)
- No FX (use IBKR).
- Options are limited (no multi-leg, no full chain quoting).
- Historical data capped at 5 years of minute bars.
- Crypto universe is smaller than Binance.

## Testing approach
- Unit tests (`connectors/tests/test_alpaca_init.py`): instantiate with a
  dummy `AlpacaConfig`, assert every method raises `NotImplementedError`.
- Live integration tests (Phase B): gated by `APEX_ALPACA_API_KEY` /
  `APEX_ALPACA_API_SECRET` env vars. CI without secrets must skip cleanly.
- Protocol conformance: `isinstance(AlpacaConnector(cfg), BrokerProvider)`
  at the type level (see `test_protocol.py`).
