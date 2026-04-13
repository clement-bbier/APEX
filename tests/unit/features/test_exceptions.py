"""Tests for features.exceptions — exception hierarchy."""

from __future__ import annotations

from features.exceptions import (
    FeatureStoreError,
    FeatureVersionExistsError,
    FeatureVersionNotFoundError,
    LookAheadViolationError,
)


class TestExceptionHierarchy:
    """All feature exceptions inherit from FeatureStoreError."""

    def test_version_exists_is_store_error(self) -> None:
        assert issubclass(FeatureVersionExistsError, FeatureStoreError)

    def test_version_not_found_is_store_error(self) -> None:
        assert issubclass(FeatureVersionNotFoundError, FeatureStoreError)

    def test_lookahead_violation_is_store_error(self) -> None:
        assert issubclass(LookAheadViolationError, FeatureStoreError)

    def test_base_is_exception(self) -> None:
        assert issubclass(FeatureStoreError, Exception)

    def test_catch_all_catches_subtypes(self) -> None:
        with __import__("pytest").raises(FeatureStoreError):
            raise FeatureVersionExistsError("duplicate version")
