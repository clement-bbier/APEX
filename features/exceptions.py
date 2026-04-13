"""Feature store exceptions.

Hierarchy:
    FeatureStoreError
    ├── FeatureVersionExistsError
    ├── FeatureVersionNotFoundError
    └── LookAheadViolationError
"""

from __future__ import annotations


class FeatureStoreError(Exception):
    """Base exception for all feature store errors."""


class FeatureVersionExistsError(FeatureStoreError):
    """Raised when attempting to overwrite an immutable feature version.

    Versions are append-only — re-computation must create a new version.
    """


class FeatureVersionNotFoundError(FeatureStoreError):
    """Raised when a requested feature version does not exist."""


class LookAheadViolationError(FeatureStoreError):
    """Raised if load() would return rows with computed_at > as_of.

    This should be structurally impossible via the SQL WHERE clause.
    If raised, it indicates a bug in the query logic.

    Reference:
        PHASE_3_SPEC Section 5.1 — Look-Ahead Bias.
    """
