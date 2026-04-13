"""HAR-RV validation report — Phase 3.4 synthetic-data scope.

Thin wrapper over :class:`ICResult` that formats HAR-RV-specific
validation output. In Phase 3.4 this produces IC results on synthetic
GBM + jumps data to demonstrate the pipeline end-to-end. Real
BTC/ETH/SPY/QQQ validation is scheduled for Phase 5.

Reference:
    PHASE_3_SPEC §2.4 A.5 success metrics.
    ADR-0004 (``docs/adr/ADR-0004-feature-validation-methodology.md``).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from features.ic.base import ICResult


@dataclass(frozen=True)
class HARRVValidationReport:
    """Validation report for HAR-RV on synthetic and (later) real data.

    In Phase 3.4, this produces IC results on synthetic GBM + jumps data
    to demonstrate the pipeline end-to-end. Real BTC/ETH/SPY/QQQ validation
    is scheduled for Phase 5 (when backtest data provisioning is complete).

    Reference:
        PHASE_3_SPEC §2.4 A.5 success metrics.
    """

    ic_results: tuple[ICResult, ...]
    """IC measurement results (one per horizon or asset)."""

    title: str = "HAR-RV Validation (Corsi 2009)"
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
            sig = "yes" if r.is_significant else "no"
            lines.append(
                f"| {r.feature_name or 'har_rv'} "
                f"| {r.horizon_bars or 1} "
                f"| {r.ic:+.4f} "
                f"| {r.ic_ir:.3f} "
                f"| {r.p_value:.4f} "
                f"| {sig} |"
            )
        lines.append("")
        return "\n".join(lines)

    def summary(self) -> dict[str, object]:
        """Return aggregate metrics for quick inspection."""
        if not self.ic_results:
            return {"n_results": 0, "mean_ic": 0.0, "mean_ic_ir": 0.0}
        ics = [r.ic for r in self.ic_results]
        ic_irs = [r.ic_ir for r in self.ic_results]
        return {
            "n_results": len(self.ic_results),
            "mean_ic": sum(ics) / len(ics),
            "mean_ic_ir": sum(ic_irs) / len(ic_irs),
            "any_significant": any(r.is_significant for r in self.ic_results),
        }
