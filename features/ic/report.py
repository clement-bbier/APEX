"""ICReport — structured IC report with JSON and Markdown output.

Aggregates :class:`ICResult` instances into a human-readable
Markdown table and a machine-readable JSON document.  Decision
thresholds follow ADR-0004:

- ``|IC| >= 0.02`` (noise floor)
- ``IC_IR >= 0.50`` (stability)

Reference:
    ADR-0004 (``docs/adr/ADR-0004-feature-validation-methodology.md``).
    Grinold, R. C. & Kahn, R. N. (1999). *Active Portfolio
    Management* (2nd ed.). McGraw-Hill, Ch. 6.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

import polars as pl

from features.ic.base import ICResult

# ADR-0004 acceptance thresholds.
_IC_THRESHOLD: float = 0.02
_IC_IR_THRESHOLD: float = 0.50


def _decision(result: ICResult) -> str:
    """Classify an ICResult as KEEP, WEAK, or REJECT per ADR-0004."""
    if abs(result.ic) >= _IC_THRESHOLD and result.ic_ir >= _IC_IR_THRESHOLD:
        return "KEEP"
    if abs(result.ic) >= _IC_THRESHOLD or result.ic_ir >= _IC_IR_THRESHOLD:
        return "WEAK"
    return "REJECT"


class ICReport:
    """Structured IC report — JSON + Markdown rendering.

    Reference:
        PHASE_3_SPEC Section 2.3, success metric A.5:
        "IC report is machine-readable (JSON + Markdown)".
    """

    def __init__(self, results: list[ICResult]) -> None:
        self._results = list(results)

    @property
    def results(self) -> list[ICResult]:
        """Underlying IC results."""
        return list(self._results)

    def to_json(self) -> str:
        """Serialize all results to a JSON string.

        Each result is a dict with all ICResult fields plus a
        ``decision`` field (KEEP / WEAK / REJECT).
        """
        records: list[dict[str, Any]] = []
        for r in self._results:
            d = asdict(r)
            d["decision"] = _decision(r)
            records.append(d)
        return json.dumps(records, indent=2, default=str)

    def to_markdown(self) -> str:
        """Render a Markdown table summarising all results.

        Columns: feature, horizon, IC, IC_IR, t-stat, p-value,
        95% CI, hit rate, turnover-adj IC, decision.
        """
        if not self._results:
            return "_No IC results._\n"

        header = (
            "| Feature | Horizon | IC | IC_IR | t-stat | p-value "
            "| 95% CI | Hit Rate | Adj IC | Decision |\n"
            "|---|---|---|---|---|---|---|---|---|---|\n"
        )
        rows: list[str] = []
        for r in self._results:
            ci = f"[{r.ci_low:.4f}, {r.ci_high:.4f}]"
            t_stat_str = f"{r.ic_t_stat:.3f}" if r.ic_t_stat is not None else "n/a"
            hit_str = f"{r.ic_hit_rate:.1%}" if r.ic_hit_rate is not None else "n/a"
            adj_str = f"{r.turnover_adj_ic:.4f}" if r.turnover_adj_ic is not None else "n/a"
            h_str = f"{r.horizon_bars}b" if r.horizon_bars is not None else "?"
            row = (
                f"| {r.feature_name or 'unknown'} | {h_str} "
                f"| {r.ic:.4f} | {r.ic_ir:.3f} | {t_stat_str} "
                f"| {r.p_value:.4f} | {ci} | {hit_str} | {adj_str} "
                f"| {_decision(r)} |"
            )
            rows.append(row)

        return header + "\n".join(rows) + "\n"

    def summary_table(self) -> pl.DataFrame:
        """Return a Polars DataFrame summarising all results."""
        if not self._results:
            return pl.DataFrame(
                schema={
                    "feature": pl.Utf8,
                    "horizon": pl.Int64,
                    "ic": pl.Float64,
                    "ic_ir": pl.Float64,
                    "t_stat": pl.Float64,
                    "p_value": pl.Float64,
                    "decision": pl.Utf8,
                }
            )
        return pl.DataFrame(
            {
                "feature": [r.feature_name or "unknown" for r in self._results],
                "horizon": [r.horizon_bars for r in self._results],
                "ic": [r.ic for r in self._results],
                "ic_ir": [r.ic_ir for r in self._results],
                "t_stat": [r.ic_t_stat for r in self._results],
                "p_value": [r.p_value for r in self._results],
                "decision": [_decision(r) for r in self._results],
            }
        )
