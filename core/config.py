"""Configuration management for APEX Trading System.

Uses Pydantic Settings to load configuration from environment variables / .env file.
All settings are validated at startup.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TradingMode(StrEnum):
    """System trading mode."""

    PAPER = "paper"
    LIVE = "live"


class Settings(BaseSettings):
    """APEX Trading System configuration loaded from environment variables.

    All sensitive values (API keys, secrets) must be set via environment or .env file.
    No default values are provided for security-critical settings.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Trading Mode ──────────────────────────────────────────────────────────
    trading_mode: TradingMode = Field(default=TradingMode.PAPER, description="paper or live")

    # ── Alpaca ────────────────────────────────────────────────────────────────
    alpaca_api_key: str = Field(default="", description="Alpaca API key")
    alpaca_api_secret: str = Field(default="", description="Alpaca API secret")
    alpaca_base_url: str = Field(
        default="https://paper-api.alpaca.markets",
        description="Alpaca REST base URL",
    )
    alpaca_data_url: str = Field(
        default="wss://stream.data.alpaca.markets/v2/iex",
        description="Alpaca WebSocket data stream URL",
    )

    # ── Binance ───────────────────────────────────────────────────────────────
    binance_api_key: str = Field(default="", description="Binance API key")
    binance_secret_key: str = Field(default="", description="Binance secret key")
    binance_testnet: bool = Field(default=True, description="Use Binance testnet")
    binance_rest_url: str = Field(
        default="https://testnet.binance.vision",
        description="Binance REST API base URL",
    )
    binance_ws_url: str = Field(
        default="wss://testnet.binance.vision/ws",
        description="Binance WebSocket base URL",
    )

    # ── FRED API ──────────────────────────────────────────────────────────────
    fred_api_key: SecretStr = Field(
        default=SecretStr(""), description="FRED API key for macro data"
    )

    # ── Massive (ex-Polygon) ─────────────────────────────────────────────────
    massive_api_key: SecretStr = Field(
        default=SecretStr(""), description="Massive/Polygon REST API key"
    )
    massive_s3_access_key: SecretStr = Field(
        default=SecretStr(""), description="Massive S3 access key"
    )
    massive_s3_secret_key: SecretStr = Field(
        default=SecretStr(""), description="Massive S3 secret key"
    )
    massive_s3_endpoint: str = Field(
        default="https://files.massive.com", description="Massive S3 endpoint URL"
    )
    massive_s3_bucket: str = Field(default="flatfiles", description="Massive S3 bucket name")

    # ── SimFin ────────────────────────────────────────────────────────────────
    simfin_api_key: SecretStr = Field(
        default=SecretStr(""), description="SimFin API key for fundamentals"
    )

    # ── SEC EDGAR ─────────────────────────────────────────────────────────────
    edgar_user_agent: str = Field(
        default="APEX/CashMachine clement.barbier@example.com",
        description="User-Agent for SEC EDGAR requests (required by SEC)",
    )

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = Field(default="redis://localhost:6379/0", description="Redis connection URL")
    redis_max_connections: int = Field(default=50)
    redis_ttl_seconds: int = Field(
        default=3600, description="Default TTL for cached values in Redis"
    )

    # ── ZeroMQ ────────────────────────────────────────────────────────────────
    # APEX uses a single XSUB/XPUB broker (see ``core/zmq_broker.py``).
    # Publishers CONNECT to ``zmq_pub_port`` (the broker's XSUB facing port);
    # subscribers CONNECT to ``zmq_sub_port`` (the XPUB facing port). Only
    # the broker BINDS — services never bind anything.
    zmq_pub_port: int = Field(
        default=5555,
        description="Broker XSUB port — publishers CONNECT here",
    )
    zmq_sub_port: int = Field(
        default=5556,
        description="Broker XPUB port — subscribers CONNECT here",
    )
    zmq_push_port: int = Field(default=5557, description="ZMQ PUSH socket port")
    zmq_pull_port: int = Field(default=5557, description="ZMQ PULL socket port")
    zmq_host: str = Field(default="127.0.0.1", description="ZMQ broker host")

    # ── Risk Parameters ───────────────────────────────────────────────────────
    max_daily_drawdown_pct: float = Field(
        default=3.0,
        gt=0.0,
        le=10.0,
        description="Maximum daily drawdown % before circuit breaker opens",
    )
    max_position_risk_pct: float = Field(
        default=0.5,
        gt=0.0,
        le=5.0,
        description="Max capital at risk per trade as % of portfolio",
    )
    max_total_exposure_pct: float = Field(
        default=40.0,
        gt=0.0,
        le=100.0,
        description="Max total portfolio exposure as % of capital",
    )
    max_per_asset_class_pct: float = Field(
        default=25.0,
        gt=0.0,
        le=100.0,
        description="Max exposure per asset class as % of capital",
    )
    max_position_size_pct: float = Field(
        default=10.0,
        gt=0.0,
        le=50.0,
        description="Max single position size as % of capital",
    )
    max_simultaneous_positions: int = Field(
        default=5,
        gt=0,
        le=20,
        description="Maximum number of open positions at once",
    )
    min_risk_reward: float = Field(
        default=1.5, gt=0.0, description="Minimum required risk/reward ratio"
    )
    crypto_size_multiplier: float = Field(
        default=0.70,
        gt=0.0,
        le=1.0,
        description="Size reduction factor for crypto positions",
    )
    max_inter_position_correlation: float = Field(
        default=0.70,
        gt=0.0,
        le=1.0,
        description="Maximum allowed correlation between open positions",
    )

    # ── Capital ───────────────────────────────────────────────────────────────
    initial_capital: Decimal = Field(
        default=Decimal("100000"),
        description="Starting capital in quote currency (USD)",
    )

    # ── Session Windows (UTC offsets) ─────────────────────────────────────────
    us_market_open_utc_hour: int = Field(
        default=14, description="US market open UTC hour (14:30 UTC = 09:30 ET)"
    )
    us_market_close_utc_hour: int = Field(
        default=21, description="US market close UTC hour (21:00 UTC = 16:00 ET)"
    )

    # ── Circuit Breaker ───────────────────────────────────────────────────────
    cb_loss_window_minutes: int = Field(
        default=30, description="Rolling window for intraday loss check"
    )
    cb_loss_pct_in_window: float = Field(
        default=2.0, description="Loss % in cb_loss_window_minutes to open circuit"
    )
    cb_vix_spike_pct: float = Field(default=20.0, description="VIX 1h spike % to open circuit")
    cb_data_timeout_seconds: int = Field(
        default=60, description="Data feed silence duration to open circuit"
    )
    cb_price_gap_pct: float = Field(
        default=5.0, description="Single-tick price gap % to open circuit"
    )

    # ── Pre-Event Block Window ─────────────────────────────────────────────────
    cb_event_pre_block_minutes: int = Field(
        default=45, description="Minutes before CB event to block new entries"
    )
    cb_event_post_scalp_minutes: int = Field(
        default=60, description="Minutes after CB event to allow post-event scalp"
    )
    cb_event_post_size_mult: float = Field(
        default=0.50, description="Size multiplier for post-event scalp entries"
    )

    # ── Kelly Sizer ───────────────────────────────────────────────────────────
    kelly_divisor: int = Field(
        default=4, description="Divide raw Kelly fraction by this (quarter-Kelly)"
    )
    kelly_rolling_trades: int = Field(
        default=100, description="Rolling window of trades for Kelly stats"
    )

    # ── Signals ───────────────────────────────────────────────────────────────
    min_signal_strength: float = Field(
        default=0.3, ge=0.0, le=1.0, description="Minimum |strength| to act on a signal"
    )
    min_confluence_triggers: int = Field(
        default=2, ge=1, description="Minimum triggers for a valid signal"
    )
    backtest_mode: bool = Field(
        default=False,
        description="Relaxed signal thresholds for backtesting synthetic data",
    )

    # ── Alerts ────────────────────────────────────────────────────────────────
    # SMTP fields accept both their canonical name (``alert_smtp_*``) and the
    # short ``smtp_*`` variant used inside the historical .env file. Pydantic
    # picks the first source it finds.
    alert_email: str | None = Field(default=None, description="Email address for alerts")
    alert_smtp_host: str = Field(
        default="smtp.gmail.com",
        validation_alias=AliasChoices("alert_smtp_host", "smtp_host"),
    )
    alert_smtp_port: int = Field(
        default=587,
        validation_alias=AliasChoices("alert_smtp_port", "smtp_port"),
    )
    alert_smtp_user: str = Field(
        default="",
        validation_alias=AliasChoices("alert_smtp_user", "smtp_user"),
    )
    alert_smtp_password: str = Field(
        default="",
        validation_alias=AliasChoices("alert_smtp_password", "smtp_password"),
    )
    twilio_sid: str | None = Field(default=None, description="Twilio account SID")
    twilio_token: str | None = Field(default=None, description="Twilio auth token")
    twilio_from_number: str = Field(default="", description="Twilio sender phone number")
    alert_phone_number: str = Field(default="", description="SMS recipient phone number")

    # ── TimescaleDB ─────────────────────────────────────────────────────────────
    timescale_host: str = Field(default="localhost", description="TimescaleDB host")
    timescale_port: int = Field(default=5432, description="TimescaleDB port")
    timescale_db: str = Field(default="apex", description="TimescaleDB database name")
    timescale_user: str = Field(default="apex", description="TimescaleDB user")
    timescale_password: str = Field(default="apex_secret", description="TimescaleDB password")
    timescale_pool_min: int = Field(default=2, description="Min asyncpg pool size")
    timescale_pool_max: int = Field(default=10, description="Max asyncpg pool size")

    @property
    def timescale_dsn(self) -> str:
        """Build PostgreSQL DSN from individual components."""
        return (
            f"postgresql://{self.timescale_user}:{self.timescale_password}"
            f"@{self.timescale_host}:{self.timescale_port}/{self.timescale_db}"
        )

    # ── Database (optional persistence layer) ─────────────────────────────────
    db_password: str = Field(
        default="",
        description="Optional database password (consumed by docker-compose / scripts)",
    )

    # ── Monitoring Dashboard ──────────────────────────────────────────────────
    dashboard_host: str = Field(default="0.0.0.0")  # noqa: S104
    dashboard_port: int = Field(default=8080)

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: str = Field(default="INFO")

    # ── OpenTelemetry ────────────────────────────────────────────────────────
    otel_endpoint: str | None = Field(
        default=None,
        description="OTLP gRPC endpoint (e.g. http://localhost:4317). None = ConsoleSpanExporter.",
    )

    @field_validator("trading_mode", mode="before")
    @classmethod
    def normalize_mode(cls, v: object) -> str:
        """Normalize trading mode to lowercase."""
        if isinstance(v, str):
            return v.lower()
        return v  # type: ignore[return-value]


# Module-level singleton
_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the singleton Settings instance, creating it on first call.

    Returns:
        Validated Settings loaded from environment / .env file.
    """
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
