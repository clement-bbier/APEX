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

        For each sample *i*, uniqueness at time *t* is defined as
        1 / (number of concurrent labels at *t*).  The weight of
        sample *i* is the average uniqueness over its lifespan.

        Args:
            entry_times: Entry timestamp for each sample.
            exit_times: Exit timestamp (t1) for each sample.

        Returns:
            1-D array of non-negative weights, same length as inputs.
            All weights > 0 when inputs are valid.

        Raises:
            ValueError: If inputs have different lengths or are empty.
        """
        n = len(entry_times)
        if n != len(exit_times):
            raise ValueError(
                f"entry_times ({n}) and exit_times ({len(exit_times)}) must have the same length."
            )
        if n == 0:
            return np.array([], dtype=np.float64)

        # Build the concurrency matrix.
        # For each sample i, count how many other samples are alive
        # at each point in sample i's lifespan.
        weights = np.zeros(n, dtype=np.float64)

        for i in range(n):
            # Time points within sample i's lifespan: all entry/exit
            # times that fall within [entry_i, exit_i].
            t_start = entry_times[i]
            t_end = exit_times[i]

            # O(n^2) approach: count concurrent labels for sample i.
            n_concurrent = 0
            total_uniqueness = 0.0

            for j in range(n):
                # j overlaps with i if entry_j <= exit_i AND exit_j >= entry_i
                if entry_times[j] <= t_end and exit_times[j] >= t_start:
                    n_concurrent += 1

            if n_concurrent > 0:
                # Average uniqueness = 1 / n_concurrent for each point
                total_uniqueness = 1.0 / n_concurrent
            else:
                total_uniqueness = 1.0

            weights[i] = total_uniqueness

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
            Full implementation deferred to a later sub-phase.
            Currently delegates to :meth:`uniqueness_weights`.

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
