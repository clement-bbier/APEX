"""GEX validation report -- Phase 3.8 synthetic-data scope.

Thin wrapper over :class:`ICResult` that formats GEX-specific
validation output. Schema-compatible with HARRVValidationReport,
RoughVolValidationReport, OFIValidationReport, and
CVDKyleValidationReport (same summary() keys, same to_markdown()
format).

Reference:
    PHASE_3_SPEC Section 2.8 success metrics.
    ADR-0004 (``docs/adr/ADR-0004-feature-validation-methodology.md``).
    Barbon, A. & Buraschi, A. (2020). "Gamma Fragility".
    Working Paper, University of St. Gallen.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from features.ic.base import ICResult


@dataclass(frozen=True)
class GEXValidationReport:
    """Validation report for GEX on synthetic data.

    In Phase 3.8, this produces IC results on synthetic option chain
    data. Real SPY/QQQ validation is scheduled for Phase 5 (pending
    options data source decision).

    Schema compatibility with previous reports:
    - summary() returns the same 4 keys
    - to_markdown() produces the same table format
    - is_significant=None renders as ``"n/a"`` (not ``"no"``)

    Sign convention note:
        Dealer-adjusted (Barbon-Buraschi 2020): calls -1, puts +1.

    Reference:
        PHASE_3_SPEC Section 2.8.
        Barbon & Buraschi (2020). "Gamma Fragility".
    """

    ic_results: tuple[ICResult, ...]
    """IC measurement results (one per horizon or asset)."""

    title: str = "GEX Validation (Barbon & Buraschi 2020)"
    """Report title."""

    def to_json(self) -> str:
        """Serialize the report to a JSON string."""
        payload = {
            "title": self.title,
            "results": [asdict(r) for r in self.ic_results],
            "summary": self.summary(),
        }
        return json.dumps(payload, indent=2, default=str)

    def to_markdown(self) -> str:
        """Render a concise Markdown summary table."""
        lines: list[str] = [
            f"# {self.title}",
            "",
            "| Feature | Horizon | IC | IC_IR | p-value | Significant |",
            "|---------|--------:|----:|------:|--------:|:-----------:|",
        ]
        for r in self.ic_results:
            if r.is_significant is None:
                sig = "n/a"
            else:
                sig = "yes" if r.is_significant else "no"
            feat_name = r.feature_name if r.feature_name is not None else "gex"
            horizon = r.horizon_bars if r.horizon_bars is not None else 1
            lines.append(
                f"| {feat_name} | {horizon} "
                f"| {r.ic:+.4f} | {r.ic_ir:.3f} "
                f"| {r.p_value:.4f} | {sig} |"
            )
        lines.append("")
        return "\n".join(lines)

    def summary(self) -> dict[str, object]:
        """Return aggregate metrics for quick inspection."""
        if not self.ic_results:
            return {
                "n_results": 0,
                "mean_ic": 0.0,
                "mean_ic_ir": 0.0,
                "any_significant": False,
            }
        ics = [r.ic for r in self.ic_results]
        ic_irs = [r.ic_ir for r in self.ic_results]
        return {
            "n_results": len(self.ic_results),
            "mean_ic": sum(ics) / len(ics),
            "mean_ic_ir": sum(ic_irs) / len(ic_irs),
            "any_significant": any(r.is_significant for r in self.ic_results),
        }
