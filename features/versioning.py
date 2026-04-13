"""Feature versioning — immutable version records and deterministic hashing.

Provides content-addressable versioning for the Feature Store:
- ``FeatureVersion`` is an immutable record of a computed feature batch.
- ``compute_version_string`` produces a deterministic short identifier.
- ``compute_content_hash`` produces a SHA-256 digest of a Polars DataFrame.

Reference:
    Sculley, D. et al. (2015). "Hidden Technical Debt in Machine
    Learning Systems". *NeurIPS*, 2503-2511 — feature lineage is a
    first-class requirement for reproducible ML systems.
"""

from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import polars as pl


@dataclass(frozen=True)
class FeatureVersion:
    """Immutable feature version record.

    Each instance represents a single computation run of a feature
    calculator on a specific asset over a specific time range.

    Reference:
        Sculley, D. et al. (2015). "Hidden Technical Debt in Machine
        Learning Systems". *NeurIPS*, 2503-2511.
    """

    asset_id: UUID
    feature_name: str
    version: str
    computed_at: datetime
    content_hash: str
    calculator_name: str
    calculator_params: Mapping[str, Any]
    row_count: int
    start_ts: datetime
    end_ts: datetime


def compute_version_string(
    calculator_name: str,
    params: Mapping[str, Any],
    computed_at: datetime,
) -> str:
    """Produce a deterministic, short version identifier.

    Format: ``{calculator_name}-{hash8}`` where hash8 is derived from
    the canonical JSON of (calculator_name, params, computed_at_iso).

    Deterministic: same inputs always produce the same version string.

    Args:
        calculator_name: Name of the feature calculator.
        params: Calculator parameters (must be JSON-serializable).
        computed_at: Wall-clock timestamp of computation.

    Returns:
        Version string, e.g. ``'har_rv-a1b2c3d4'``.
    """
    canonical = json.dumps(
        {
            "calculator_name": calculator_name,
            "params": dict(sorted(params.items())) if params else {},
            "computed_at": computed_at.isoformat(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:8]
    return f"{calculator_name}-{digest}"


def compute_content_hash(df: pl.DataFrame) -> str:
    """Compute SHA-256 digest of a Polars DataFrame's IPC bytes.

    The DataFrame is sorted by the ``timestamp`` column (if present)
    before serialization to ensure deterministic output regardless of
    input row order.

    Args:
        df: Polars DataFrame to hash.

    Returns:
        Hex-encoded SHA-256 digest string (64 chars).
    """
    stable = df.sort("timestamp") if "timestamp" in df.columns else df
    buf = io.BytesIO()
    stable.write_ipc(buf)
    return hashlib.sha256(buf.getvalue()).hexdigest()
