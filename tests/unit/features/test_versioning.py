"""Tests for features.versioning — FeatureVersion, version strings, content hashes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import polars as pl
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from features.versioning import (
    FeatureVersion,
    compute_content_hash,
    compute_version_string,
)


class TestFeatureVersionFrozen:
    """FeatureVersion is an immutable frozen dataclass."""

    def test_frozen_cannot_mutate(self) -> None:
        v = FeatureVersion(
            asset_id=uuid4(),
            feature_name="har_rv",
            version="har_rv-abcd1234",
            computed_at=datetime.now(UTC),
            content_hash="a" * 64,
            calculator_name="har_rv",
            calculator_params={},
            row_count=100,
            start_ts=datetime(2024, 1, 1, tzinfo=UTC),
            end_ts=datetime(2024, 6, 1, tzinfo=UTC),
        )
        with pytest.raises(AttributeError):
            v.feature_name = "other"  # type: ignore[misc]

    def test_equality(self) -> None:
        aid = uuid4()
        ts = datetime.now(UTC)
        kwargs = {
            "asset_id": aid,
            "feature_name": "har_rv",
            "version": "har_rv-abcd1234",
            "computed_at": ts,
            "content_hash": "a" * 64,
            "calculator_name": "har_rv",
            "calculator_params": {},
            "row_count": 100,
            "start_ts": datetime(2024, 1, 1, tzinfo=UTC),
            "end_ts": datetime(2024, 6, 1, tzinfo=UTC),
        }
        assert FeatureVersion(**kwargs) == FeatureVersion(**kwargs)

    def test_inequality_different_version(self) -> None:
        aid = uuid4()
        ts = datetime.now(UTC)
        base = {
            "asset_id": aid,
            "feature_name": "har_rv",
            "computed_at": ts,
            "content_hash": "a" * 64,
            "calculator_name": "har_rv",
            "calculator_params": {},
            "row_count": 100,
            "start_ts": datetime(2024, 1, 1, tzinfo=UTC),
            "end_ts": datetime(2024, 6, 1, tzinfo=UTC),
        }
        v1 = FeatureVersion(version="har_rv-v1", **base)
        v2 = FeatureVersion(version="har_rv-v2", **base)
        assert v1 != v2


class TestComputeVersionString:
    """compute_version_string is deterministic and discriminating."""

    def test_deterministic(self) -> None:
        ts = datetime(2026, 4, 13, 15, 0, 0, tzinfo=UTC)
        v1 = compute_version_string("har_rv", {"window": 22}, ts)
        v2 = compute_version_string("har_rv", {"window": 22}, ts)
        assert v1 == v2

    def test_different_params_different_version(self) -> None:
        ts = datetime(2026, 4, 13, 15, 0, 0, tzinfo=UTC)
        v1 = compute_version_string("har_rv", {"window": 22}, ts)
        v2 = compute_version_string("har_rv", {"window": 44}, ts)
        assert v1 != v2

    def test_different_calculator_different_version(self) -> None:
        ts = datetime(2026, 4, 13, 15, 0, 0, tzinfo=UTC)
        v1 = compute_version_string("har_rv", {}, ts)
        v2 = compute_version_string("rough_vol", {}, ts)
        assert v1 != v2

    def test_different_time_different_version(self) -> None:
        v1 = compute_version_string("har_rv", {}, datetime(2026, 1, 1, tzinfo=UTC))
        v2 = compute_version_string("har_rv", {}, datetime(2026, 1, 2, tzinfo=UTC))
        assert v1 != v2

    def test_format_prefix(self) -> None:
        ts = datetime(2026, 4, 13, 15, 0, 0, tzinfo=UTC)
        v = compute_version_string("har_rv", {}, ts)
        assert v.startswith("har_rv-")
        assert len(v) == len("har_rv-") + 8

    def test_param_order_invariant(self) -> None:
        ts = datetime(2026, 4, 13, 15, 0, 0, tzinfo=UTC)
        v1 = compute_version_string("har_rv", {"a": 1, "b": 2}, ts)
        v2 = compute_version_string("har_rv", {"b": 2, "a": 1}, ts)
        assert v1 == v2

    @settings(max_examples=1000)
    @given(
        name=st.text(
            min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L", "N"))
        ),
        param_val=st.integers(min_value=0, max_value=10000),
        hours_offset=st.integers(min_value=0, max_value=8760),
    )
    def test_hypothesis_deterministic(self, name: str, param_val: int, hours_offset: int) -> None:
        ts = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=hours_offset)
        v1 = compute_version_string(name, {"p": param_val}, ts)
        v2 = compute_version_string(name, {"p": param_val}, ts)
        assert v1 == v2

    @settings(max_examples=1000)
    @given(
        param_a=st.integers(min_value=0, max_value=10000),
        param_b=st.integers(min_value=0, max_value=10000),
    )
    def test_hypothesis_different_params(self, param_a: int, param_b: int) -> None:
        from hypothesis import assume

        assume(param_a != param_b)
        ts = datetime(2026, 1, 1, tzinfo=UTC)
        v1 = compute_version_string("test", {"p": param_a}, ts)
        v2 = compute_version_string("test", {"p": param_b}, ts)
        assert v1 != v2


class TestComputeContentHash:
    """compute_content_hash produces deterministic SHA-256 digests."""

    def test_deterministic(self) -> None:
        df = pl.DataFrame(
            {
                "timestamp": [datetime(2024, 1, 1, tzinfo=UTC)],
                "value": [1.0],
            }
        )
        h1 = compute_content_hash(df)
        h2 = compute_content_hash(df)
        assert h1 == h2

    def test_different_data_different_hash(self) -> None:
        df1 = pl.DataFrame(
            {
                "timestamp": [datetime(2024, 1, 1, tzinfo=UTC)],
                "value": [1.0],
            }
        )
        df2 = pl.DataFrame(
            {
                "timestamp": [datetime(2024, 1, 1, tzinfo=UTC)],
                "value": [2.0],
            }
        )
        assert compute_content_hash(df1) != compute_content_hash(df2)

    def test_hash_length(self) -> None:
        df = pl.DataFrame(
            {
                "timestamp": [datetime(2024, 1, 1, tzinfo=UTC)],
                "value": [1.0],
            }
        )
        assert len(compute_content_hash(df)) == 64

    def test_row_order_invariant_with_timestamp(self) -> None:
        """DataFrame is sorted by timestamp before hashing."""
        ts1 = datetime(2024, 1, 1, tzinfo=UTC)
        ts2 = datetime(2024, 1, 2, tzinfo=UTC)
        df_asc = pl.DataFrame({"timestamp": [ts1, ts2], "value": [1.0, 2.0]})
        df_desc = pl.DataFrame({"timestamp": [ts2, ts1], "value": [2.0, 1.0]})
        assert compute_content_hash(df_asc) == compute_content_hash(df_desc)
