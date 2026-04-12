"""SampleWeighter — uniqueness-weighted samples for ML training.

Overlapping labels (common with the Triple Barrier Method) cause
samples to share information, violating IID assumptions.  The
uniqueness weighter downweights samples that overlap in time.

Reference:
    Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*.
    Wiley, Ch. 4, Sections 4.2-4.4.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import numpy.typing as npt


class SampleWeighter:
    """Compute sample weights based on label uniqueness.

    When labels overlap in time (e.g. Triple Barrier with
    ``max_holding_periods > 1``), samples are not independent.
    Uniqueness weighting ensures that the effective sample size
    reflects the true information content.

    Reference:
        Lopez de Prado, M. (2018). *Advances in Financial Machine
        Learning*. Wiley, Ch. 4, Section 4.2 ("Average Uniqueness
        of a Label").
    """

    def uniqueness_weights(
        self,
        entry_times: list[datetime],
        exit_times: list[datetime],
    ) -> npt.NDArray[np.float64]:
        """Compute average-uniqueness sample weights.

        For each sample *i*, concurrency c(t) is the number of active
        labels at time *t*.  Uniqueness u(t, i) = 1 / c(t).  The
        weight of sample *i* is the duration-weighted average of
        u(t, i) over its lifespan [entry_i, exit_i].

        Concurrency is piecewise-constant between sorted unique
        entry/exit timestamps, so we integrate over segments.

        Args:
            entry_times: Entry timestamp for each sample.
            exit_times: Exit timestamp (t1) for each sample.

        Returns:
            1-D array of non-negative weights, same length as inputs.
            All weights > 0 when inputs are valid.

        Raises:
            ValueError: If inputs have different lengths.

        Notes:
            Returns an empty float64 array when both inputs are empty.

        Reference:
            Lopez de Prado, M. (2018). *Advances in Financial Machine
            Learning*. Wiley, Ch. 4, Section 4.2, formula for average
            uniqueness ū_i = (1/|T_i|) Σ_{t∈T_i} (1/c_t).
        """
        n = len(entry_times)
        if n != len(exit_times):
            raise ValueError(
                f"entry_times ({n}) and exit_times ({len(exit_times)}) must have the same length."
            )
        if n == 0:
            return np.array([], dtype=np.float64)

        # Sorted unique endpoints define piecewise-constant segments.
        endpoints = sorted(set(entry_times + exit_times))
        weights = np.zeros(n, dtype=np.float64)

        for i in range(n):
            t_start = entry_times[i]
            t_end = exit_times[i]

            # Zero-duration sample: fallback to point-in-time concurrency.
            if t_start == t_end:
                n_concurrent = sum(
                    1 for j in range(n) if entry_times[j] <= t_start <= exit_times[j]
                )
                weights[i] = 1.0 / n_concurrent if n_concurrent > 0 else 1.0
                continue

            # Duration-weighted average of 1/c(t) over [t_start, t_end].
            total_uniqueness = 0.0
            total_duration = 0.0

            for k in range(len(endpoints) - 1):
                seg_start, seg_end = endpoints[k], endpoints[k + 1]
                overlap_start = max(t_start, seg_start)
                overlap_end = min(t_end, seg_end)
                seg_duration = (overlap_end - overlap_start).total_seconds()
                if seg_duration <= 0.0:
                    continue
                # Count labels active during this segment (open interval).
                n_concurrent = sum(
                    1
                    for j in range(n)
                    if entry_times[j] < overlap_end and exit_times[j] > overlap_start
                )
                if n_concurrent > 0:
                    total_uniqueness += seg_duration * (1.0 / n_concurrent)
                    total_duration += seg_duration

            weights[i] = total_uniqueness / total_duration if total_duration > 0 else 1.0

        return weights

    def return_attribution_weights(
        self,
        entry_times: list[datetime],
        exit_times: list[datetime],
        returns: npt.NDArray[np.float64],
    ) -> npt.NDArray[np.float64]:
        """Compute return-attribution sample weights.

        Extends uniqueness weighting by attributing returns to each
        sample proportionally to its uniqueness contribution.

        .. note::
            Raises ``NotImplementedError`` in Phase 3.1.  Use
            :meth:`uniqueness_weights` directly until wired in a
            later sub-phase.

        Reference:
            Lopez de Prado, M. (2018). *Advances in Financial Machine
            Learning*. Wiley, Ch. 4, Section 4.4.

        Raises:
            NotImplementedError: Full return-attribution is deferred.
        """
        raise NotImplementedError(
            "Return-attribution weighting is deferred to a later "
            "sub-phase.  Use uniqueness_weights() for Phase 3.1."
        )
