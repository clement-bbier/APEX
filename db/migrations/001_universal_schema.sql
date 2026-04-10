-- 001_universal_schema.sql
-- Universal TimescaleDB schema for APEX Trading System
-- Phase 2.1: Foundation data layer
--
-- References:
--   Kleppmann (2017) Ch. 3+6: storage engines, partitioning
--   Bouchaud et al. (2018) Ch. 2: financial data conventions
--   TimescaleDB docs: hypertables, compression, retention

-- ============================================================
-- 0. Extension
-- ============================================================
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- ============================================================
-- 1. Asset Registry
-- ============================================================
CREATE TABLE IF NOT EXISTS assets (
    asset_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol        VARCHAR(40)  NOT NULL,
    exchange      VARCHAR(40)  NOT NULL,
    asset_class   VARCHAR(20)  NOT NULL
                  CHECK (asset_class IN (
                      'crypto', 'equity', 'forex', 'commodity',
                      'bond', 'option', 'future', 'index', 'macro'
                  )),
    currency      VARCHAR(10)  NOT NULL,
    timezone      VARCHAR(40)  DEFAULT 'UTC',
    tick_size     NUMERIC(20,10),
    lot_size      NUMERIC(20,10),
    is_active     BOOLEAN      DEFAULT TRUE,
    listing_date  DATE,
    delisting_date DATE,
    metadata_json JSONB        DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ  DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  DEFAULT NOW(),
    UNIQUE (symbol, exchange)
);

CREATE INDEX IF NOT EXISTS idx_assets_asset_class ON assets (asset_class);
CREATE INDEX IF NOT EXISTS idx_assets_is_active   ON assets (is_active);

-- ============================================================
-- 2. Bars — Universal OHLCV (hypertable)
-- ============================================================
CREATE TABLE IF NOT EXISTS bars (
    asset_id    UUID         NOT NULL REFERENCES assets(asset_id),
    bar_type    VARCHAR(10)  NOT NULL,
    bar_size    VARCHAR(10)  NOT NULL,
    timestamp   TIMESTAMPTZ  NOT NULL,
    open        NUMERIC(20,8) NOT NULL,
    high        NUMERIC(20,8) NOT NULL,
    low         NUMERIC(20,8) NOT NULL,
    close       NUMERIC(20,8) NOT NULL,
    volume      NUMERIC(20,8) NOT NULL,
    trade_count INTEGER,
    vwap        NUMERIC(20,8),
    adj_close   NUMERIC(20,8),
    PRIMARY KEY (asset_id, bar_type, bar_size, timestamp)
);

SELECT create_hypertable('bars', 'timestamp',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists       => TRUE
);

CREATE INDEX IF NOT EXISTS idx_bars_asset_ts ON bars (asset_id, timestamp);

ALTER TABLE bars SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'asset_id, bar_type, bar_size',
    timescaledb.compress_orderby   = 'timestamp'
);

SELECT add_compression_policy('bars', INTERVAL '30 days', if_not_exists => TRUE);

-- ============================================================
-- 3. Ticks — Tick-level data (hypertable)
-- ============================================================
CREATE TABLE IF NOT EXISTS ticks (
    asset_id    UUID          NOT NULL REFERENCES assets(asset_id),
    timestamp   TIMESTAMPTZ   NOT NULL,
    trade_id    VARCHAR(40)   DEFAULT '',
    price       NUMERIC(20,8) NOT NULL,
    quantity    NUMERIC(20,8) NOT NULL,
    side        VARCHAR(7)    DEFAULT 'unknown',
    PRIMARY KEY (asset_id, timestamp, trade_id)
);

SELECT create_hypertable('ticks', 'timestamp',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists       => TRUE
);

ALTER TABLE ticks SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'asset_id',
    timescaledb.compress_orderby   = 'timestamp'
);

SELECT add_compression_policy('ticks', INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_retention_policy('ticks', INTERVAL '6 months', if_not_exists => TRUE);

-- ============================================================
-- 4. Order Book Snapshots (hypertable)
-- ============================================================
CREATE TABLE IF NOT EXISTS order_book_snapshots (
    asset_id    UUID          NOT NULL,
    timestamp   TIMESTAMPTZ   NOT NULL,
    depth_level SMALLINT      NOT NULL,
    bid_price   NUMERIC(20,8),
    bid_size    NUMERIC(20,8),
    ask_price   NUMERIC(20,8),
    ask_size    NUMERIC(20,8),
    PRIMARY KEY (asset_id, timestamp, depth_level)
);

SELECT create_hypertable('order_book_snapshots', 'timestamp',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists       => TRUE
);

ALTER TABLE order_book_snapshots SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'asset_id',
    timescaledb.compress_orderby   = 'timestamp'
);

SELECT add_compression_policy('order_book_snapshots', INTERVAL '3 days', if_not_exists => TRUE);
SELECT add_retention_policy('order_book_snapshots', INTERVAL '3 months', if_not_exists => TRUE);

-- ============================================================
-- 5. Macro Series (hypertable)
-- ============================================================
CREATE TABLE IF NOT EXISTS macro_series (
    series_id   VARCHAR(40)      NOT NULL,
    timestamp   TIMESTAMPTZ      NOT NULL,
    value       DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (series_id, timestamp)
);

SELECT create_hypertable('macro_series', 'timestamp',
    chunk_time_interval => INTERVAL '1 year',
    if_not_exists       => TRUE
);

-- ============================================================
-- 6. Macro Series Metadata
-- ============================================================
CREATE TABLE IF NOT EXISTS macro_series_metadata (
    series_id   VARCHAR(40)  PRIMARY KEY,
    source      VARCHAR(20)  NOT NULL,
    name        VARCHAR(200) NOT NULL,
    frequency   VARCHAR(20),
    unit        VARCHAR(50),
    description TEXT
);

-- ============================================================
-- 7. Fundamentals
-- ============================================================
CREATE TABLE IF NOT EXISTS fundamentals (
    asset_id    UUID         NOT NULL,
    report_date DATE         NOT NULL,
    period_type VARCHAR(10)  NOT NULL,
    metric_name VARCHAR(60)  NOT NULL,
    value       DOUBLE PRECISION,
    currency    VARCHAR(10),
    PRIMARY KEY (asset_id, report_date, period_type, metric_name)
);

-- ============================================================
-- 8. Corporate Events
-- ============================================================
CREATE TABLE IF NOT EXISTS corporate_events (
    event_id     UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_id     UUID        NOT NULL,
    event_date   DATE        NOT NULL,
    event_type   VARCHAR(30) NOT NULL,
    details_json JSONB       DEFAULT '{}'::jsonb
);

-- ============================================================
-- 9. Economic Events
-- ============================================================
CREATE TABLE IF NOT EXISTS economic_events (
    event_id         UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type       VARCHAR(40)   NOT NULL,
    scheduled_time   TIMESTAMPTZ   NOT NULL,
    actual           DOUBLE PRECISION,
    consensus        DOUBLE PRECISION,
    prior            DOUBLE PRECISION,
    impact_score     SMALLINT      DEFAULT 1,
    related_asset_id UUID,
    source           VARCHAR(40)
);

-- ============================================================
-- 10. Data Quality Log
-- ============================================================
CREATE TABLE IF NOT EXISTS data_quality_log (
    check_id     UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp    TIMESTAMPTZ DEFAULT NOW(),
    check_type   VARCHAR(40) NOT NULL,
    asset_id     UUID,
    severity     VARCHAR(10) NOT NULL,
    details_json JSONB       DEFAULT '{}'::jsonb,
    resolved     BOOLEAN     DEFAULT FALSE
);

-- ============================================================
-- 11. Ingestion Runs
-- ============================================================
CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    connector     VARCHAR(40) NOT NULL,
    asset_id      UUID,
    started_at    TIMESTAMPTZ NOT NULL,
    finished_at   TIMESTAMPTZ,
    status        VARCHAR(20) DEFAULT 'running',
    rows_inserted BIGINT      DEFAULT 0,
    error_message TEXT,
    metadata_json JSONB       DEFAULT '{}'::jsonb
);

-- ============================================================
-- 12. Schema Versions (migration tracking)
-- ============================================================
CREATE TABLE IF NOT EXISTS schema_versions (
    version    INTEGER      PRIMARY KEY,
    filename   VARCHAR(200) NOT NULL,
    applied_at TIMESTAMPTZ  DEFAULT NOW(),
    checksum   VARCHAR(64)
);
