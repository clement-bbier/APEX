"""Phase 4.1 - Triple Barrier labeling for the Meta-Labeler.

Thin, Polars-native batch wrapper on top of the existing
:class:`core.math.labeling.TripleBarrierLabeler`. Adds the binary
projection defined in ADR-0005 D1 without duplicating the core math.

Public API:

- :func:`to_binary_target` - re-exported ``BarrierLabel -> {0, 1}`` helper.
- :func:`label_events_binary` - batch labeler producing the schema
  consumed by sub-phase 4.3 training: ``symbol, t0, t1, entry_price,
  exit_price, ternary_label, binary_target, barrier_hit,
  holding_periods``.
- :func:`build_events_from_signals` - event-time construction helper.
- :func:`compute_label_diagnostics` - distribution + sanity stats.

References:
    Lopez de Prado (2018), Advances in Financial Machine Learning,
    Chapter 3.4 - 3.6.
    ADR-0005 D1 - Triple Barrier Method contract.
    PHASE_4_SPEC section 3.1 - module structure and public API.
"""

from __future__ import annotations

from core.math.labeling import (
    BarrierLabel,
    BarrierResult,
    TripleBarrierConfig,
    TripleBarrierLabeler,
    to_binary_target,
)
from features.labeling.diagnostics import LabelDiagnostics, compute_label_diagnostics
from features.labeling.events import build_events_from_signals
from features.labeling.triple_barrier import label_events_binary

__all__ = [
    "BarrierLabel",
    "BarrierResult",
    "LabelDiagnostics",
    "TripleBarrierConfig",
    "TripleBarrierLabeler",
    "build_events_from_signals",
    "compute_label_diagnostics",
    "label_events_binary",
    "to_binary_target",
]
