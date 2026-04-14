"""Feature activation configuration loaded from the Phase 3.12 report.

The :class:`FeatureActivationConfig` is the single source of truth for
*which* features are authorized to flow through the Phase 3.13 adapter
into (eventually) S02. It is produced by reading the JSON output of
``scripts/generate_phase_3_12_report.py`` -- never hardcoded.

Design notes:
    * Immutable (``frozen=True``). Loaded once at process startup.
    * No "override" mode: if a human wants to deactivate a kept
      feature, that decision belongs to a downstream config layer
      (Phase 4+), not to this class.
    * Every candidate feature is tracked -- kept or rejected --
      honouring the cherry-picking protection established in 3.12.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class FeatureActivationConfig:
    """Activation decisions sourced from the Phase 3.12 selection report.

    Attributes:
        activated_features: Feature names for which the Phase 3.12
            decision was ``keep``.
        rejected_features: Feature names for which the Phase 3.12
            decision was ``reject``.
        generated_at: Timestamp of the source report.
        pbo_of_final_set: PBO of the final kept set (if reported).
    """

    activated_features: frozenset[str]
    rejected_features: frozenset[str]
    generated_at: datetime
    pbo_of_final_set: float | None

    @classmethod
    def from_report_json(cls, path: Path) -> FeatureActivationConfig:
        """Load the activation config from a Phase 3.12 JSON report.

        Args:
            path: Path to ``feature_selection_report.json``.

        Returns:
            A frozen :class:`FeatureActivationConfig`.

        Raises:
            FileNotFoundError: If ``path`` does not exist.
            ValueError: If the JSON structure is malformed or a
                ``decision`` is neither ``keep`` nor ``reject``.
        """
        if not path.exists():
            raise FileNotFoundError(f"Phase 3.12 report not found: {path}")

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Phase 3.12 report is not valid JSON: {exc}") from exc

        if not isinstance(raw, dict) or "decisions" not in raw:
            raise ValueError("Phase 3.12 report must be a JSON object with a 'decisions' array")

        decisions = raw["decisions"]
        if not isinstance(decisions, list):
            raise ValueError("'decisions' must be a list of decision entries")

        activated: set[str] = set()
        rejected: set[str] = set()
        for entry in decisions:
            if not isinstance(entry, dict):
                raise ValueError("Each decision entry must be a JSON object")
            name = entry.get("feature_name")
            decision = entry.get("decision")
            if not isinstance(name, str) or not name:
                raise ValueError("Decision entry missing 'feature_name'")
            if decision == "keep":
                activated.add(name)
            elif decision == "reject":
                rejected.add(name)
            else:
                raise ValueError(
                    f"Unknown decision value {decision!r} for feature {name!r}; "
                    "expected 'keep' or 'reject'"
                )

        generated_at_raw = raw.get("generated_at")
        if not isinstance(generated_at_raw, str):
            raise ValueError("'generated_at' must be an ISO-8601 string")
        generated_at = _parse_iso8601(generated_at_raw)

        pbo_raw = raw.get("pbo_of_final_set")
        pbo: float | None
        if pbo_raw is None:
            pbo = None
        elif isinstance(pbo_raw, (int, float)):
            pbo = float(pbo_raw)
        else:
            raise ValueError("'pbo_of_final_set' must be a number or null")

        return cls(
            activated_features=frozenset(activated),
            rejected_features=frozenset(rejected),
            generated_at=generated_at,
            pbo_of_final_set=pbo,
        )

    def is_activated(self, feature_name: str) -> bool:
        """True iff ``feature_name`` was kept by Phase 3.12."""
        return feature_name in self.activated_features


def _parse_iso8601(value: str) -> datetime:
    """Parse an ISO-8601 timestamp, tolerating a trailing ``Z``."""
    normalised = value.replace("Z", "+00:00") if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(normalised)
    except ValueError as exc:
        raise ValueError(f"Invalid ISO-8601 timestamp: {value!r}") from exc
