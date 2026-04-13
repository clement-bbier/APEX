"""Rough Vol validation report — Phase 3.5 synthetic-data scope.

Thin wrapper over :class:`ICResult` that formats Rough Vol-specific
validation output. Schema-compatible with HARRVValidationReport
(same summary() keys, same to_markdown() format).

Reference:
    PHASE_3_SPEC §2.5 success metrics.
    ADR-0004 (``docs/adr/ADR-0004-feature-validation-methodology.md``).
    Gatheral, J., Jaisson, T. & Rosenbaum, M. (2018). "Volatility is
    rough". Quantitative Finance, 18(6), 933-949.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from features.ic.base import ICResult


@dataclass(frozen=True)
class RoughVolValidationReport:
    """Validation report for Rough Vol on synthetic and (later) real data.

    In Phase 3.5, this produces IC results on synthetic fBm/GBM data.
    Real BTC/ETH/SPY/QQQ validation is scheduled for Phase 5.

    Schema compatibility with HARRVValidationReport:
    - summary() returns the same 4 keys
    - to_markdown() produces the same table format
    - is_significant=None renders as ``"n/a"`` (not ``"no"``)

    Reference:
        PHASE_3_SPEC §2.5.
        Gatheral et al. (2018). Quantitative Finance 18(6).
    """

    ic_results: tuple[ICResult, ...]
    """IC measurement results (one per horizon or asset)."""

    title: str = "Rough Vol Validation (Gatheral 2018)"
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
            name = r.feature_name if r.feature_name is not None else "rough_vol"
            horizon = r.horizon_bars if r.horizon_bars is not None else 1
            lines.append(
                f"| {name} | {horizon} | {r.ic:+.4f} | {r.ic_ir:.3f} | {r.p_value:.4f} | {sig} |"
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
