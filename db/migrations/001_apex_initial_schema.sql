-- 001_apex_initial_schema.sql
-- APEX TimescaleDB schema v2 — multi-strategy-aware foundation (Phase B)
--
-- See docs/adr/ADR-0014-timescaledb-schema-v2.md for the full rationale.
--
-- Invariants
--   * Every DDL statement is idempotent: CREATE ... IF NOT EXISTS,
--     if_not_exists => TRUE, ON CONFLICT DO NOTHING. Re-running this
--     migration is a safe no-op.
--   * Every order-path / PnL / metrics table carries ``strategy_id``
--     (Charter §5.5) with default ``'default'`` for backward compatibility.
--   * Prices, sizes, PnL, fees are NUMERIC(20,8) — never FLOAT.
--   * All timestamps are TIMESTAMPTZ. The application layer stores UTC.
--   * Forward-only. No DROP anywhere. Destructive changes get their own
--     migration file with their own ADR.
--
-- References
--   * Charter §5.5 — per-strategy identity
--   * ADR-0007 — strategy-as-microservice
--   * PHASE_5_v3_MULTI_STRAT_ALIGNED_ROADMAP.md §3 — Phase B

-- ============================================================
-- 0. Extensions
-- ============================================================
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================
-- 1. ticks — raw tick / top-of-book snapshots (hypertable)
-- ============================================================
CREATE TABLE IF NOT EXISTS ticks (
    symbol      TEXT          NOT NULL,
    exchange    TEXT          NOT NULL,
    ts          TIMESTAMPTZ   NOT NULL,
    bid         NUMERIC(20,8),
    ask         NUMERIC(20,8),
    bid_size    NUMERIC(20,8),
    ask_size    NUMERIC(20,8),
    last_price  NUMERIC(20,8),
    last_size   NUMERIC(20,8)
);

SELECT create_hypertable('ticks', 'ts',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists       => TRUE
);

CREATE INDEX IF NOT EXISTS idx_ticks_symbol_ts_desc
    ON ticks (symbol, ts DESC);

ALTER TABLE ticks SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol, exchange',
    timescaledb.compress_orderby   = 'ts'
);

SELECT add_compression_policy('ticks', INTERVAL '7 days',  if_not_exists => TRUE);
SELECT add_retention_policy  ('ticks', INTERVAL '90 days', if_not_exists => TRUE);

-- ============================================================
-- 2. bars_1m — 1-minute OHLCV, strategy-tagged (hypertable)
-- ============================================================
CREATE TABLE IF NOT EXISTS bars_1m (
    symbol       TEXT          NOT NULL,
    strategy_id  TEXT          NOT NULL DEFAULT 'default',
    ts           TIMESTAMPTZ   NOT NULL,
    open         NUMERIC(20,8) NOT NULL,
    high         NUMERIC(20,8) NOT NULL,
    low          NUMERIC(20,8) NOT NULL,
    close        NUMERIC(20,8) NOT NULL,
    volume       NUMERIC(20,8) NOT NULL,
    vwap         NUMERIC(20,8),
    trade_count  INTEGER
);

SELECT create_hypertable('bars_1m', 'ts',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists       => TRUE
);

CREATE INDEX IF NOT EXISTS idx_bars_1m_strategy_symbol_ts_desc
    ON bars_1m (strategy_id, symbol, ts DESC);

ALTER TABLE bars_1m SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'strategy_id, symbol',
    timescaledb.compress_orderby   = 'ts'
);

SELECT add_compression_policy('bars_1m', INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_retention_policy  ('bars_1m', INTERVAL '730 days', if_not_exists => TRUE);

-- ============================================================
-- 3. signals — strategy-emitted signals (hypertable)
-- ============================================================
CREATE TABLE IF NOT EXISTS signals (
    signal_id    UUID          NOT NULL DEFAULT gen_random_uuid(),
    strategy_id  TEXT          NOT NULL DEFAULT 'default',
    symbol       TEXT          NOT NULL,
    ts           TIMESTAMPTZ   NOT NULL,
    direction    TEXT          NOT NULL
                 CHECK (direction IN ('long', 'short', 'flat')),
    confidence   NUMERIC(5,4)  NOT NULL
                 CHECK (confidence >= 0 AND confidence <= 1),
    features     JSONB         DEFAULT '{}'::jsonb,
    source       TEXT,
    PRIMARY KEY (signal_id, ts)
);

SELECT create_hypertable('signals', 'ts',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists       => TRUE
);

CREATE INDEX IF NOT EXISTS idx_signals_strategy_ts_desc
    ON signals (strategy_id, ts DESC);

SELECT add_retention_policy('signals', INTERVAL '730 days', if_not_exists => TRUE);

-- ============================================================
-- 4. order_candidates — pre-VETO order proposals (hypertable)
-- ============================================================
CREATE TABLE IF NOT EXISTS order_candidates (
    order_id          UUID          NOT NULL DEFAULT gen_random_uuid(),
    strategy_id       TEXT          NOT NULL DEFAULT 'default',
    symbol            TEXT          NOT NULL,
    ts_proposed       TIMESTAMPTZ   NOT NULL,
    direction         TEXT          NOT NULL
                      CHECK (direction IN ('long', 'short')),
    size              NUMERIC(20,8) NOT NULL,
    entry             NUMERIC(20,8) NOT NULL,
    stop_loss         NUMERIC(20,8) NOT NULL,
    targets           JSONB         DEFAULT '[]'::jsonb,
    source_signal_id  UUID,
    capital_at_risk   NUMERIC(20,8),
    PRIMARY KEY (order_id, ts_proposed)
);

SELECT create_hypertable('order_candidates', 'ts_proposed',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists       => TRUE
);

CREATE INDEX IF NOT EXISTS idx_order_candidates_strategy_ts_desc
    ON order_candidates (strategy_id, ts_proposed DESC);

-- ============================================================
-- 5. approved_orders — post-VETO approved orders (hypertable)
-- ============================================================
CREATE TABLE IF NOT EXISTS approved_orders (
    order_id           UUID          NOT NULL,
    strategy_id        TEXT          NOT NULL DEFAULT 'default',
    symbol             TEXT          NOT NULL,
    ts_approved        TIMESTAMPTZ   NOT NULL,
    risk_chain_result  JSONB         DEFAULT '{}'::jsonb,
    PRIMARY KEY (order_id, ts_approved)
);

SELECT create_hypertable('approved_orders', 'ts_approved',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists       => TRUE
);

CREATE INDEX IF NOT EXISTS idx_approved_orders_strategy_ts_desc
    ON approved_orders (strategy_id, ts_approved DESC);

-- ============================================================
-- 6. executed_orders — broker-confirmed executions (hypertable)
-- ============================================================
CREATE TABLE IF NOT EXISTS executed_orders (
    order_id         UUID          NOT NULL,
    strategy_id      TEXT          NOT NULL DEFAULT 'default',
    symbol           TEXT          NOT NULL,
    ts_submitted     TIMESTAMPTZ   NOT NULL,
    ts_filled        TIMESTAMPTZ,
    fill_price       NUMERIC(20,8),
    fill_size        NUMERIC(20,8),
    slippage         NUMERIC(20,8),
    broker_order_id  TEXT,
    venue            TEXT,
    PRIMARY KEY (order_id, ts_submitted)
);

SELECT create_hypertable('executed_orders', 'ts_submitted',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists       => TRUE
);

CREATE INDEX IF NOT EXISTS idx_executed_orders_strategy_ts_desc
    ON executed_orders (strategy_id, ts_submitted DESC);

-- ============================================================
-- 7. trade_records — closed-trade PnL attribution (hypertable)
-- ============================================================
CREATE TABLE IF NOT EXISTS trade_records (
    trade_id         UUID          NOT NULL DEFAULT gen_random_uuid(),
    strategy_id      TEXT          NOT NULL DEFAULT 'default',
    symbol           TEXT          NOT NULL,
    ts_open          TIMESTAMPTZ   NOT NULL,
    ts_close         TIMESTAMPTZ   NOT NULL,
    direction        TEXT          NOT NULL
                     CHECK (direction IN ('long', 'short')),
    entry_price      NUMERIC(20,8) NOT NULL,
    exit_price       NUMERIC(20,8) NOT NULL,
    size             NUMERIC(20,8) NOT NULL,
    pnl              NUMERIC(20,8) NOT NULL,
    fees             NUMERIC(20,8) NOT NULL DEFAULT 0,
    pnl_attribution  JSONB         DEFAULT '{}'::jsonb,
    PRIMARY KEY (trade_id, ts_close)
);

SELECT create_hypertable('trade_records', 'ts_close',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists       => TRUE
);

CREATE INDEX IF NOT EXISTS idx_trade_records_strategy_ts_close_desc
    ON trade_records (strategy_id, ts_close DESC);

-- ============================================================
-- 8. pnl_snapshots — per-strategy portfolio state (hypertable)
-- ============================================================
CREATE TABLE IF NOT EXISTS pnl_snapshots (
    snapshot_ts      TIMESTAMPTZ   NOT NULL,
    strategy_id      TEXT          NOT NULL DEFAULT 'default',
    realized_pnl     NUMERIC(20,8) NOT NULL DEFAULT 0,
    unrealized_pnl   NUMERIC(20,8) NOT NULL DEFAULT 0,
    gross_exposure   NUMERIC(20,8) NOT NULL DEFAULT 0,
    net_exposure     NUMERIC(20,8) NOT NULL DEFAULT 0,
    positions        JSONB         DEFAULT '{}'::jsonb,
    PRIMARY KEY (snapshot_ts, strategy_id)
);

SELECT create_hypertable('pnl_snapshots', 'snapshot_ts',
    chunk_time_interval => INTERVAL '1 hour',
    if_not_exists       => TRUE
);

CREATE INDEX IF NOT EXISTS idx_pnl_snapshots_strategy_ts_desc
    ON pnl_snapshots (strategy_id, snapshot_ts DESC);

-- ============================================================
-- 9. strategy_metrics — daily per-strategy performance (regular table)
-- ============================================================
CREATE TABLE IF NOT EXISTS strategy_metrics (
    date           DATE          NOT NULL,
    strategy_id    TEXT          NOT NULL DEFAULT 'default',
    sharpe         NUMERIC(10,6),
    sortino        NUMERIC(10,6),
    psr            NUMERIC(10,6),
    dsr            NUMERIC(10,6),
    calmar         NUMERIC(10,6),
    max_drawdown   NUMERIC(10,6),
    ulcer_index    NUMERIC(10,6),
    n_trades       INTEGER       NOT NULL DEFAULT 0,
    win_rate       NUMERIC(5,4)
                   CHECK (win_rate IS NULL OR (win_rate >= 0 AND win_rate <= 1)),
    PRIMARY KEY (date, strategy_id)
);

CREATE INDEX IF NOT EXISTS idx_strategy_metrics_strategy_date_desc
    ON strategy_metrics (strategy_id, date DESC);

-- ============================================================
-- 10. regime_states — regime classification over time (hypertable)
-- ============================================================
CREATE TABLE IF NOT EXISTS regime_states (
    ts            TIMESTAMPTZ   NOT NULL,
    regime_label  TEXT          NOT NULL,
    confidence    NUMERIC(5,4)  NOT NULL
                  CHECK (confidence >= 0 AND confidence <= 1),
    features      JSONB         DEFAULT '{}'::jsonb,
    PRIMARY KEY (ts, regime_label)
);

SELECT create_hypertable('regime_states', 'ts',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists       => TRUE
);

CREATE INDEX IF NOT EXISTS idx_regime_states_ts_desc
    ON regime_states (ts DESC);

-- ============================================================
-- 11. risk_limits — per-strategy risk envelopes (regular table)
-- ============================================================
CREATE TABLE IF NOT EXISTS risk_limits (
    strategy_id          TEXT          PRIMARY KEY,
    max_position_size    NUMERIC(20,8) NOT NULL,
    max_gross_exposure   NUMERIC(20,8) NOT NULL,
    daily_loss_limit     NUMERIC(20,8) NOT NULL,
    updated_at           TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- Seed the default strategy with loose placeholder limits so the
-- legacy path does not trip STEP 3 during Phase B bring-up. Real
-- limits are populated by the Playbook §4 Gate 2 PR for each strategy.
INSERT INTO risk_limits (strategy_id, max_position_size, max_gross_exposure, daily_loss_limit)
VALUES ('default', 1000000, 10000000, 100000)
ON CONFLICT (strategy_id) DO NOTHING;

-- ============================================================
-- Schema version tag
-- ============================================================
CREATE TABLE IF NOT EXISTS schema_versions_v2 (
    version     INTEGER      PRIMARY KEY,
    filename    TEXT         NOT NULL,
    applied_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

INSERT INTO schema_versions_v2 (version, filename)
VALUES (1, '001_apex_initial_schema.sql')
ON CONFLICT (version) DO NOTHING;
