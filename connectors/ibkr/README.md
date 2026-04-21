# IBKR Connector

Wraps [ib_insync](https://pypi.org/project/ib_insync/) (or eventually
`ibapi` directly) as a `BrokerProvider` implementation.

## Role
- Broadest coverage of any tier-1 broker: US + international equities,
  FX (spot + forwards), futures, options (full chain), bonds.
- Paper and live accounts identical API surface.
- The right choice for Phase B Gate 3 once the strategy universe
  expands beyond US equities + crypto.

## Activation

1. Install the SDK extra:
   ```
   pip install -e ".[connectors-ibkr]"
   ```
2. Run TWS or IB Gateway locally. API access must be enabled in the
   configuration dialog (`Global Configuration → API → Settings`):
   - "Enable ActiveX and Socket Clients": on
   - "Read-Only API": on for paper-only safety, off for live trading
   - "Socket port": 7497 (paper TWS) or 7496 (live TWS)
3. Start APEX with IBKR enabled (Phase B Gate 3 wires this in):
   ```python
   from connectors.ibkr import IBKRConfig, IBKRConnector

   cfg = IBKRConfig(host="127.0.0.1", port=7497, client_id=1)
   broker = IBKRConnector(cfg)
   # await broker.get_account()  # Phase B Gate 3
   ```

## Known limitations
- Setup complexity is higher than Alpaca: TWS/IB Gateway must be
  running (and, for production, auto-restarted).
- Market-data subscriptions are per-exchange pay-per-use — budget
  this separately before enabling live feeds.
- The TWS API rate-limit is strict (50 req/s soft, 200 req/s hard).
  `ib_insync` pipelines calls but heavy backtesting should still use
  batched historical bars.
- Crypto is NOT supported via IBKR; continue using Alpaca / Binance.

## Testing approach
- Unit tests (`connectors/tests/test_ibkr_init.py`): instantiate with a
  dummy `IBKRConfig`, assert every method raises `NotImplementedError`.
- Live integration tests (Phase B Gate 3): gated by a `APEX_IBKR_LIVE`
  env var; CI runs them only in a dedicated job with a paper TWS
  reachable on the runner.
- Protocol conformance: the `isinstance(IBKRConnector(cfg),
  BrokerProvider)` check must hold at the type level
  (`test_protocol.py`).
