-- 002_feature_store.sql
-- Feature Store schema for APEX Trading System
-- Phase 3.2: Versioned, reproducible feature persistence with point-in-time queries
--
-- References:
--   Sculley et al. (2015) "Hidden Technical Debt in ML Systems", NeurIPS
--   Fowler (2002) PoEAA Ch. 10 — Repository Pattern
--   Kleppmann (2017) DDIA Ch. 11 — Stream Processing
--
-- Invariants:
--   - feature_versions is append-only (no UPDATE in runtime; retention policies only)
--   - Re-extraction with same params -> same content_hash -> detects code changes
--   - computed_at in both tables is THE column for point-in-time (as_of) filtering
--   - A version once written is immutable: (asset_id, feature_name, version) is unique

-- ============================================================
-- 1. Feature Values — versioned feature data (hypertable)
-- ============================================================
CREATE TABLE IF NOT EXISTS feature_values (
    asset_id      UUID         NOT NULL REFERENCES assets(asset_id),
    feature_name  VARCHAR(64)  NOT NULL,
    version       VARCHAR(40)  NOT NULL,
    timestamp     TIMESTAMPTZ  NOT NULL,
    value         DOUBLE PRECISION,
    computed_at   TIMESTAMPTZ  NOT NULL,
    PRIMARY KEY (asset_id, feature_name, version, timestamp)
);

SELECT create_hypertable('feature_values', 'timestamp',
    chunk_time_interval => INTERVAL '30 days',
    if_not_exists       => TRUE
);

CREATE INDEX IF NOT EXISTS idx_feature_values_lookup
    ON feature_values (asset_id, feature_name, version, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_feature_values_computed_at
    ON feature_values (computed_at);

ALTER TABLE feature_values SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'asset_id, feature_name, version',
    timescaledb.compress_orderby   = 'timestamp'
);

SELECT add_compression_policy('feature_values', INTERVAL '60 days', if_not_exists => TRUE);

-- ============================================================
-- 2. Feature Versions — immutable metadata catalog
-- ============================================================
CREATE TABLE IF NOT EXISTS feature_versions (
    asset_id          UUID         NOT NULL REFERENCES assets(asset_id),
    feature_name      VARCHAR(64)  NOT NULL,
    version           VARCHAR(40)  NOT NULL,
    computed_at       TIMESTAMPTZ  NOT NULL,
    content_hash      VARCHAR(64)  NOT NULL,
    calculator_name   VARCHAR(64)  NOT NULL,
    calculator_params JSONB        DEFAULT '{}'::jsonb,
    row_count         BIGINT       NOT NULL,
    start_ts          TIMESTAMPTZ  NOT NULL,
    end_ts            TIMESTAMPTZ  NOT NULL,
    PRIMARY KEY (asset_id, feature_name, version)
);

CREATE INDEX IF NOT EXISTS idx_feature_versions_latest
    ON feature_versions (asset_id, feature_name, computed_at DESC);
