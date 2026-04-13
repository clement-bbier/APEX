"""Cross-Validation sub-package -- CPCV and feature validation.

Phase 3.10: CombinatoriallyPurgedKFold (CPCV splitter).
Phase 3.11: DSR/PBO (planned).
"""

from features.cv.cpcv import CombinatoriallyPurgedKFold
from features.cv.embargo import apply_embargo
from features.cv.purging import purge_train_indices

__all__ = [
    "CombinatoriallyPurgedKFold",
    "apply_embargo",
    "purge_train_indices",
]
