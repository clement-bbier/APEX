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

Phase 4.2 additions (ADR-0005 D2 - sample weights):

- :func:`compute_concurrency` - bar-indexed concurrency count ``c_t``.
- :func:`uniqueness_weights` - uniqueness weight ``u_i``.
- :func:`return_attribution_weights` - return-attribution weight ``r_i``.
- :func:`combined_weights` - final training weight ``w_i = u_i * r_i``.

References:
    Lopez de Prado (2018), Advances in Financial Machine Learning,
    Chapter 3.4 - 3.6 and Chapter 4.4 - 4.5.
    ADR-0005 D1 - Triple Barrier Method contract.
    ADR-0005 D2 - Sample weights contract.
    PHASE_4_SPEC section 3.1 and 3.2 - module structure and public API.
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
from features.labeling.sample_weights import (
    combined_weights,
    compute_concurrency,
    return_attribution_weights,
    uniqueness_weights,
)
from features.labeling.triple_barrier import label_events_binary

__all__ = [
    "BarrierLabel",
    "BarrierResult",
    "LabelDiagnostics",
    "TripleBarrierConfig",
    "TripleBarrierLabeler",
    "build_events_from_signals",
    "combined_weights",
    "compute_concurrency",
    "compute_label_diagnostics",
    "label_events_binary",
    "return_attribution_weights",
    "to_binary_target",
    "uniqueness_weights",
]
