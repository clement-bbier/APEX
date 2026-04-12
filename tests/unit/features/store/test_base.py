"""Tests for features.store.base — FeatureStore ABC."""

from __future__ import annotations

import pytest

from features.store.base import FeatureStore


class TestFeatureStoreABC:
    """FeatureStore cannot be instantiated."""

    def test_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError, match="abstract method"):
            FeatureStore()  # type: ignore[abstract]

    def test_has_required_abstract_methods(self) -> None:
        abstract_names = {
            m
            for m in dir(FeatureStore)
            if getattr(getattr(FeatureStore, m, None), "__isabstractmethod__", False)
        }
        assert abstract_names == {"save", "load", "list_versions", "latest_version"}
