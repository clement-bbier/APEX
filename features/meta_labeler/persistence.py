"""Phase 4.6 - Meta-Labeler model persistence with schema-versioned card.

Serialises a validated Meta-Labeler (post-Phase-4.5 PASS verdict) to
disk as a ``.joblib`` binary with a schema-v1 JSON model card
alongside it. Load is symmetric: both files are read together, the
card is re-validated, and a ``model_type`` cross-check guards against
loading a model with the wrong card (or vice versa).

Per ADR-0005 D6 + PHASE_4_SPEC §3.6:

- ``joblib`` is the serialization format; ``.joblib`` is the mandatory
  extension. ONNX is deferred (D6 allows it when a consumer requires
  interoperability; none exists in Phase 4).
- The model card is JSON, sorted-keys, UTF-8 encoded, with a trailing
  newline. This makes two saves of the same card byte-identical on
  disk (a determinism test asserts this).
- ``training_commit_sha`` is sourced from ``git rev-parse HEAD`` at
  save time; the working tree MUST be clean. A dirty tree would mean
  the committed SHA cannot reproduce the artifact.
- ``training_dataset_hash`` is a library-agnostic SHA-256 digest over
  a fixed-order byte serialisation of ``(feature_names, X, y)``; see
  :func:`compute_dataset_hash` for the exact protocol.
- The bit-exact round-trip test lives in
  ``tests/unit/features/meta_labeler/test_persistence.py``: on 1,000
  fixed rows, ``load(save(model)).predict_proba == model.predict_proba``
  under ``np.array_equal`` (tolerance 0.0). Non-determinism is a
  deployment blocker per ADR-0005 D6.

References:
    ADR-0005 (Meta-Labeling and Fusion Methodology), D6.
    PHASE_4_SPEC §3.6.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import numpy.typing as npt
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression

from features.meta_labeler.model_card import ModelCardV1, validate_model_card

__all__ = [
    "MetaLabelerModel",
    "compute_dataset_hash",
    "derive_artifact_stem",
    "get_head_commit_sha",
    "is_working_tree_clean",
    "load_model",
    "save_model",
]

# Public alias for the two sklearn estimators that schema v1 accepts.
# The PEP-695 ``type`` statement is the project's preferred style
# (Python 3.12 target in pyproject.toml); mypy --strict recognises it
# as a type, and ruff UP040 enforces it over ``typing.TypeAlias``.
type MetaLabelerModel = RandomForestClassifier | LogisticRegression

_MODEL_SUFFIX = ".joblib"
_CARD_SUFFIX = ".json"


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------


def save_model(
    model: MetaLabelerModel,
    card: ModelCardV1,
    output_dir: Path,
) -> tuple[Path, Path]:
    """Persist a Meta-Labeler model + card to ``output_dir``.

    Writes two files side-by-side:

        {training_date_iso_no_colons}_{commit_sha8}.joblib
        {training_date_iso_no_colons}_{commit_sha8}.json

    Args:
        model: Trained ``RandomForestClassifier`` or
            ``LogisticRegression`` (the only two types allowed by
            schema v1).
        card: Fully populated :class:`~features.meta_labeler.model_card.ModelCardV1`.
            The dict is validated before any disk write, so a bad
            card never leaves a half-written artifact on disk.
        output_dir: Target directory. Created if missing.

    Returns:
        ``(model_path, card_path)`` with absolute paths to the two
        written files.

    Raises:
        ValueError: on invalid card, dirty working tree, or a
            mismatch between the supplied ``training_commit_sha`` and
            the current ``git HEAD``.
        TypeError: if ``model`` is not one of the allowed sklearn
            estimators.
    """
    if not isinstance(model, (RandomForestClassifier, LogisticRegression)):
        raise TypeError(
            f"model must be RandomForestClassifier or LogisticRegression; "
            f"got {type(model).__name__}"
        )

    validated = validate_model_card(dict(card))

    # Card must agree with the model it describes. We check both
    # directions here so save_model fails before writing anything
    # rather than relying on load_model to catch it later.
    actual_model_type = type(model).__name__
    if validated["model_type"] != actual_model_type:
        raise ValueError(
            f"card.model_type={validated['model_type']!r} does not match "
            f"the supplied model type {actual_model_type!r}"
        )

    # Reproducibility: require a clean tree and a matching HEAD SHA.
    # Either dirty or mismatched means the stored commit_sha cannot
    # reproduce the artifact, which defeats the purpose of the card.
    if not is_working_tree_clean():
        raise ValueError(
            "save_model refuses to write while the git working tree is "
            "dirty; commit or stash your changes to guarantee the stored "
            "training_commit_sha reproduces the training run (ADR-0005 D6)"
        )
    head_sha = get_head_commit_sha()
    if head_sha != validated["training_commit_sha"]:
        raise ValueError(
            f"card.training_commit_sha={validated['training_commit_sha']!r} "
            f"does not match current HEAD={head_sha!r}"
        )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    stem = derive_artifact_stem(
        training_date_utc=validated["training_date_utc"],
        training_commit_sha=validated["training_commit_sha"],
    )
    model_path = output_dir / f"{stem}{_MODEL_SUFFIX}"
    card_path = output_dir / f"{stem}{_CARD_SUFFIX}"

    # joblib first, then card: if the card write fails for any reason,
    # we leave the (still reproducible) joblib behind rather than a
    # dangling card claiming to describe a model that was never saved.
    joblib.dump(model, model_path)
    _write_card_json(validated, card_path)

    return model_path, card_path


def load_model(
    model_path: Path,
    card_path: Path,
) -> tuple[MetaLabelerModel, ModelCardV1]:
    """Load a Meta-Labeler model and re-validate its card.

    Args:
        model_path: Path to the ``.joblib`` artifact.
        card_path: Path to the sibling ``.json`` card.

    Returns:
        ``(model, card)``.

    Raises:
        ValueError: on missing / invalid extensions, card schema
            violation, or a ``type(model).__name__`` that does not
            match ``card["model_type"]``.
    """
    model_path = Path(model_path)
    card_path = Path(card_path)

    if model_path.suffix != _MODEL_SUFFIX:
        raise ValueError(
            f"model_path must have suffix {_MODEL_SUFFIX!r}; got {model_path.suffix!r}"
        )
    if card_path.suffix != _CARD_SUFFIX:
        raise ValueError(f"card_path must have suffix {_CARD_SUFFIX!r}; got {card_path.suffix!r}")

    card_text = card_path.read_text(encoding="utf-8")
    try:
        card_raw = json.loads(card_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"card at {card_path} is not valid JSON: {exc}") from exc
    card = validate_model_card(card_raw)

    model = joblib.load(model_path)
    if not isinstance(model, (RandomForestClassifier, LogisticRegression)):
        raise ValueError(
            f"loaded object at {model_path} is not a supported estimator; "
            f"got {type(model).__name__}"
        )

    loaded_type = type(model).__name__
    if loaded_type != card["model_type"]:
        raise ValueError(
            f"model/card type mismatch: loaded {loaded_type!r} but card "
            f"declares {card['model_type']!r}"
        )

    return model, card


def compute_dataset_hash(
    feature_names: list[str],
    X: npt.NDArray[Any],  # noqa: N803 - sklearn convention
    y: npt.NDArray[Any],
) -> str:
    """Compute the canonical SHA-256 training dataset hash.

    The hasher is library-agnostic (no pandas, no pyarrow) and stable
    across numpy versions because ``tobytes(order="C")`` is defined
    by ``(shape, dtype)`` alone. Consumes, in this exact order:

    1. UTF-8 of ``json.dumps(feature_names, sort_keys=True,
       separators=(",", ":"))``.
    2. UTF-8 of ``json.dumps({"shape": list(X.shape), "dtype":
       str(X.dtype)}, sort_keys=True, separators=(",", ":"))``.
    3. ``np.ascontiguousarray(X).tobytes(order="C")``.
    4. UTF-8 of ``json.dumps({"shape": list(y.shape), "dtype":
       str(y.dtype)}, sort_keys=True, separators=(",", ":"))``.
    5. ``np.ascontiguousarray(y).tobytes(order="C")``.

    Args:
        feature_names: Ordered list of column names used during
            training. Order matters: permuting names changes the hash.
        X: Training design matrix, any shape/dtype.
        y: Training labels, any shape/dtype.

    Returns:
        ``"sha256:" + hashlib.sha256(...).hexdigest()``.

    Raises:
        TypeError: if ``feature_names`` is not a list of strings.
    """
    if not isinstance(feature_names, list) or not all(isinstance(f, str) for f in feature_names):
        raise TypeError("feature_names must be a list of strings")

    hasher = hashlib.sha256()
    hasher.update(json.dumps(feature_names, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    x_meta = {"shape": list(X.shape), "dtype": str(X.dtype)}
    hasher.update(json.dumps(x_meta, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    hasher.update(np.ascontiguousarray(X).tobytes(order="C"))
    y_meta = {"shape": list(y.shape), "dtype": str(y.dtype)}
    hasher.update(json.dumps(y_meta, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    hasher.update(np.ascontiguousarray(y).tobytes(order="C"))
    return "sha256:" + hasher.hexdigest()


def derive_artifact_stem(
    *,
    training_date_utc: str,
    training_commit_sha: str,
) -> str:
    """Produce the filename stem shared by the ``.joblib`` and ``.json``.

    Replaces ``:`` with ``-`` so the name is valid on Windows (CI runs
    on Linux but local devs on Windows would otherwise choke on the
    path). Example:

        2026-05-01T14:30:00Z, 4cbbdfc...  →  2026-05-01T14-30-00Z_4cbbdfca

    Args:
        training_date_utc: ISO-8601 UTC timestamp with ``Z`` suffix.
        training_commit_sha: 40-char lowercase git SHA.

    Returns:
        Stem without extension.
    """
    date_token = training_date_utc.replace(":", "-")
    sha8 = training_commit_sha[:8]
    return f"{date_token}_{sha8}"


def get_head_commit_sha(cwd: Path | None = None) -> str:
    """Return the 40-char SHA of ``git HEAD`` in ``cwd`` (or ``$PWD``).

    Args:
        cwd: Optional working directory override. Useful in tests
            that spin up a throwaway repo.

    Returns:
        40-char lowercase hex SHA.

    Raises:
        RuntimeError: if ``git`` is not available or ``cwd`` is not
            a git repository.
    """
    try:
        raw = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],  # noqa: S607 - git on PATH by CI contract
            cwd=str(cwd) if cwd is not None else None,
            stderr=subprocess.STDOUT,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f"git rev-parse HEAD failed in {cwd or Path.cwd()}: {exc}") from exc
    return raw.decode("utf-8").strip()


def is_working_tree_clean(cwd: Path | None = None) -> bool:
    """Return True iff ``git status --porcelain`` in ``cwd`` is empty.

    Args:
        cwd: Optional working directory override.

    Returns:
        True when no tracked changes and no untracked files are
        reported; False otherwise.
    """
    try:
        raw = subprocess.check_output(
            ["git", "status", "--porcelain"],  # noqa: S607 - git on PATH by CI contract
            cwd=str(cwd) if cwd is not None else None,
            stderr=subprocess.STDOUT,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f"git status --porcelain failed in {cwd or Path.cwd()}: {exc}") from exc
    return raw.decode("utf-8").strip() == ""


# ----------------------------------------------------------------------
# Internal helpers
# ----------------------------------------------------------------------


def _write_card_json(card: ModelCardV1, path: Path) -> None:
    """Emit the card as deterministic UTF-8 JSON with trailing newline.

    ``sort_keys=True`` + ``ensure_ascii=False`` + fixed indent gives
    byte-identical output for two saves of the same card, which lets
    ``test_card_json_is_deterministic_bytewise`` pass.
    """
    payload = json.dumps(card, sort_keys=True, ensure_ascii=False, indent=2)
    path.write_text(payload + "\n", encoding="utf-8")
