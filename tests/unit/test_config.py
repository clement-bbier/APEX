"""Unit tests for core.config Settings (Phase 2.5 extensions)."""

from __future__ import annotations

from pydantic import SecretStr

from core.config import Settings


class TestAlpacaSettings:
    """Validate Alpaca settings load from env vars."""

    def test_alpaca_keys_from_env(self, monkeypatch: object) -> None:

        mp = monkeypatch  # type: ignore[assignment]
        mp.setenv("ALPACA_API_KEY", "PK_TEST_123")
        mp.setenv("ALPACA_SECRET_KEY", "SK_TEST_456")
        mp.setenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
        mp.setenv("ALPACA_DATA_URL", "https://data.alpaca.markets")
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.alpaca_api_key == "PK_TEST_123"
        assert s.alpaca_secret_key == "SK_TEST_456"
        assert "paper-api" in s.alpaca_base_url

    def test_alpaca_defaults(self) -> None:
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.alpaca_api_key == ""
        assert "paper-api" in s.alpaca_base_url


class TestMassiveSettings:
    """Validate Massive (ex-Polygon) settings load from env vars."""

    def test_massive_keys_from_env(self, monkeypatch: object) -> None:
        mp = monkeypatch  # type: ignore[assignment]
        mp.setenv("MASSIVE_API_KEY", "api_key_test")
        mp.setenv("MASSIVE_S3_ACCESS_KEY", "s3_access_test")
        mp.setenv("MASSIVE_S3_SECRET_KEY", "s3_secret_test")
        mp.setenv("MASSIVE_S3_ENDPOINT", "https://test.massive.com")
        mp.setenv("MASSIVE_S3_BUCKET", "test-bucket")
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert isinstance(s.massive_api_key, SecretStr)
        assert s.massive_api_key.get_secret_value() == "api_key_test"
        assert s.massive_s3_access_key.get_secret_value() == "s3_access_test"
        assert s.massive_s3_secret_key.get_secret_value() == "s3_secret_test"
        assert s.massive_s3_endpoint == "https://test.massive.com"
        assert s.massive_s3_bucket == "test-bucket"

    def test_massive_defaults(self) -> None:
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.massive_api_key.get_secret_value() == ""
        assert s.massive_s3_endpoint == "https://files.massive.com"
        assert s.massive_s3_bucket == "flatfiles"


class TestFredSettings:
    """Validate FRED API key is SecretStr."""

    def test_fred_key_from_env(self, monkeypatch: object) -> None:
        mp = monkeypatch  # type: ignore[assignment]
        mp.setenv("FRED_API_KEY", "fred_test_key")
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert isinstance(s.fred_api_key, SecretStr)
        assert s.fred_api_key.get_secret_value() == "fred_test_key"
