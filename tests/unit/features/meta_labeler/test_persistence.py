"""Unit tests for :mod:`features.meta_labeler.persistence`.

Coverage target: ≥ 94 % on ``persistence.py``.

The tests run in an isolated, throwaway git repo created per-test
(``git_repo`` fixture) so the working-tree-clean guard and the
``git rev-parse HEAD`` lookup work deterministically without leaving
side effects in the host repo.

The bit-exact round-trip test - the ADR-0005 D6 deployment gate -
is ``test_load_roundtrip_bit_exact_predictions``.
"""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pytest
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression

from features.meta_labeler.persistence import (
    compute_dataset_hash,
    derive_artifact_stem,
    load_model,
    save_model,
)

_FEATURE_NAMES = [
    "gex_signal",
    "har_rv_signal",
    "ofi_signal",
    "regime_vol_code",
    "regime_trend_code",
    "realized_vol_28d",
    "hour_of_day_sin",
    "day_of_week_sin",
]


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


@pytest.fixture
def git_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a clean throwaway git repo and cd into it.

    Returns the repo path. ``monkeypatch.chdir`` means
    ``save_model`` / ``load_model`` pick this repo up via their
    default ``subprocess`` calls with ``cwd=None``.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)
    _run(["git", "init", "--quiet", "--initial-branch=main"], cwd=repo)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo)
    _run(["git", "config", "user.name", "Test"], cwd=repo)
    _run(["git", "config", "commit.gpgsign", "false"], cwd=repo)
    (repo / "README.md").write_text("test\n", encoding="utf-8")
    _run(["git", "add", "README.md"], cwd=repo)
    _run(["git", "commit", "--quiet", "-m", "init"], cwd=repo)
    return repo


def _head_sha(cwd: Path) -> str:
    return (
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(cwd)).decode("utf-8").strip()
    )


def _run(cmd: list[str], *, cwd: Path) -> None:
    subprocess.check_call(cmd, cwd=str(cwd), stdout=subprocess.DEVNULL)


def _make_rf(seed: int = 42) -> tuple[RandomForestClassifier, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    x_mat = rng.standard_normal((200, len(_FEATURE_NAMES))).astype(np.float64)
    y = (x_mat[:, 0] + 0.3 * rng.standard_normal(200) > 0).astype(np.int64)
    rf = RandomForestClassifier(
        n_estimators=20, max_depth=4, min_samples_leaf=5, random_state=42, n_jobs=1
    )
    rf.fit(x_mat, y)
    return rf, x_mat, y


def _make_card(*, commit_sha: str, model_type: str = "RandomForestClassifier") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "model_type": model_type,
        "hyperparameters": {
            "n_estimators": 20,
            "max_depth": 4,
            "min_samples_leaf": 5,
            "random_state": 42,
            "n_jobs": 1,
        },
        "training_date_utc": "2026-05-01T14:30:00Z",
        "training_commit_sha": commit_sha,
        "training_dataset_hash": (
            "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
        "cpcv_splits_used": [[[0, 1, 2], [3, 4]]],
        "features_used": list(_FEATURE_NAMES),
        "sample_weight_scheme": "uniqueness_x_return_attribution",
        "gates_measured": {"G1": 0.58, "G3": 0.97, "G4": 0.05},
        "gates_passed": {"G1": True, "G3": True, "G4": True, "aggregate": True},
        "baseline_auc_logreg": 0.54,
        "notes": "test",
    }


# ----------------------------------------------------------------------
# save_model happy path + file layout
# ----------------------------------------------------------------------


def test_save_produces_both_files(git_repo: Path) -> None:
    model, _, _ = _make_rf()
    card = _make_card(commit_sha=_head_sha(git_repo))
    out_dir = git_repo / "models"

    model_path, card_path = save_model(model, card, out_dir)

    assert model_path.exists()
    assert card_path.exists()
    assert model_path.suffix == ".joblib"
    assert card_path.suffix == ".json"
    # Both files share the same stem (date + sha8).
    assert model_path.stem == card_path.stem


def test_save_filename_follows_date_sha8_grammar(git_repo: Path) -> None:
    model, _, _ = _make_rf()
    sha = _head_sha(git_repo)
    card = _make_card(commit_sha=sha)
    model_path, _ = save_model(model, card, git_repo / "models")

    expected_stem = f"2026-05-01T14-30-00Z_{sha[:8]}"
    assert model_path.stem == expected_stem


def test_save_creates_output_dir_if_missing(git_repo: Path) -> None:
    model, _, _ = _make_rf()
    card = _make_card(commit_sha=_head_sha(git_repo))
    out_dir = git_repo / "nested" / "output"
    assert not out_dir.exists()
    save_model(model, card, out_dir)
    assert out_dir.is_dir()


# ----------------------------------------------------------------------
# save_model — dirty tree + SHA guards
# ----------------------------------------------------------------------


def test_save_raises_on_dirty_working_tree(git_repo: Path) -> None:
    model, _, _ = _make_rf()
    card = _make_card(commit_sha=_head_sha(git_repo))
    (git_repo / "dirty.txt").write_text("uncommitted change\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"dirty"):
        save_model(model, card, git_repo / "models")


def test_save_rejects_mismatched_commit_sha(git_repo: Path) -> None:
    model, _, _ = _make_rf()
    card = _make_card(commit_sha="a" * 40)  # not the real HEAD

    with pytest.raises(ValueError, match=r"does not match current HEAD"):
        save_model(model, card, git_repo / "models")


def test_save_rejects_wrong_model_type_in_card(git_repo: Path) -> None:
    model, _, _ = _make_rf()  # RandomForest
    card = _make_card(commit_sha=_head_sha(git_repo), model_type="LogisticRegression")
    with pytest.raises(ValueError, match=r"does not match the supplied model type"):
        save_model(model, card, git_repo / "models")


def test_save_rejects_unsupported_model_instance(git_repo: Path) -> None:
    card = _make_card(commit_sha=_head_sha(git_repo))
    with pytest.raises(TypeError, match=r"model must be"):
        save_model("not a sklearn model", card, git_repo / "models")


def test_save_propagates_card_schema_violation(git_repo: Path) -> None:
    model, _, _ = _make_rf()
    bad_card = _make_card(commit_sha=_head_sha(git_repo))
    bad_card["schema_version"] = 2
    with pytest.raises(ValueError, match=r"schema_version must be 1"):
        save_model(model, bad_card, git_repo / "models")


# ----------------------------------------------------------------------
# load_model — happy path + cross-checks
# ----------------------------------------------------------------------


def test_load_roundtrip_bit_exact_predictions(git_repo: Path) -> None:
    # ADR-0005 D6 deployment gate: save -> load -> predict on a fixed
    # 1000-row batch must be bit-exact (tolerance 0.0).
    model, _, _ = _make_rf()
    card = _make_card(commit_sha=_head_sha(git_repo))
    model_path, card_path = save_model(model, card, git_repo / "models")

    loaded_model, loaded_card = load_model(model_path, card_path)

    rng = np.random.default_rng(42)
    x_fixture = rng.standard_normal((1000, len(_FEATURE_NAMES)))
    proba_before = model.predict_proba(x_fixture)
    proba_after = loaded_model.predict_proba(x_fixture)

    assert np.array_equal(proba_before, proba_after)
    assert loaded_card["training_commit_sha"] == card["training_commit_sha"]


def test_load_raises_on_model_type_mismatch(git_repo: Path) -> None:
    model, _, _ = _make_rf()
    card = _make_card(commit_sha=_head_sha(git_repo))
    model_path, card_path = save_model(model, card, git_repo / "models")

    # Swap the saved joblib with a LogisticRegression so the declared
    # type no longer matches the loaded object.
    lr = LogisticRegression().fit([[0.0], [1.0]], [0, 1])
    joblib.dump(lr, model_path)

    with pytest.raises(ValueError, match=r"model/card type mismatch"):
        load_model(model_path, card_path)


def test_load_raises_on_schema_violation(git_repo: Path) -> None:
    model, _, _ = _make_rf()
    card = _make_card(commit_sha=_head_sha(git_repo))
    model_path, card_path = save_model(model, card, git_repo / "models")

    # Corrupt the on-disk card to violate schema_version.
    data = json.loads(card_path.read_text(encoding="utf-8"))
    data["schema_version"] = 2
    card_path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")

    with pytest.raises(ValueError, match=r"schema_version must be 1"):
        load_model(model_path, card_path)


def test_load_raises_on_malformed_json(tmp_path: Path) -> None:
    bad_card = tmp_path / "card.json"
    bad_card.write_text("{ not json", encoding="utf-8")
    fake_model = tmp_path / "model.joblib"
    fake_model.write_bytes(b"")

    with pytest.raises(ValueError, match=r"not valid JSON"):
        load_model(fake_model, bad_card)


def test_load_rejects_wrong_suffixes(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"model_path must have suffix"):
        load_model(tmp_path / "model.pkl", tmp_path / "card.json")
    with pytest.raises(ValueError, match=r"card_path must have suffix"):
        load_model(tmp_path / "model.joblib", tmp_path / "card.yaml")


def test_load_rejects_unsupported_estimator(git_repo: Path, tmp_path: Path) -> None:
    # Write a non-estimator object into a .joblib to simulate a
    # corrupted or mislabelled artifact.
    fake_model_path = tmp_path / "weird.joblib"
    joblib.dump({"not": "an estimator"}, fake_model_path)
    card = _make_card(commit_sha=_head_sha(git_repo))
    card_path = tmp_path / "weird.json"
    card_path.write_text(json.dumps(card, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"not a supported estimator"):
        load_model(fake_model_path, card_path)


# ----------------------------------------------------------------------
# Card JSON on-disk format
# ----------------------------------------------------------------------


def test_card_json_is_deterministic_bytewise(git_repo: Path) -> None:
    # Two saves of the same (model, card) must produce byte-identical
    # JSON on disk. Sorted keys + ensure_ascii=False + trailing newline
    # is the canonical form.
    model, _, _ = _make_rf()
    card = _make_card(commit_sha=_head_sha(git_repo))

    _, card_path_1 = save_model(model, card, git_repo / "models")
    bytes_1 = card_path_1.read_bytes()

    # Delete and re-save - the stem collides intentionally; we assert
    # the disk bytes are byte-identical for a repeatable save.
    card_path_1.unlink()
    model_path_1 = card_path_1.with_suffix(".joblib")
    model_path_1.unlink()

    _, card_path_2 = save_model(model, card, git_repo / "models")
    bytes_2 = card_path_2.read_bytes()
    assert bytes_1 == bytes_2
    assert bytes_1.endswith(b"\n")


def test_card_json_round_trip_is_lossless(git_repo: Path) -> None:
    model, _, _ = _make_rf()
    card = _make_card(commit_sha=_head_sha(git_repo))
    _, card_path = save_model(model, card, git_repo / "models")
    reloaded = json.loads(card_path.read_text(encoding="utf-8"))
    assert reloaded == card


# ----------------------------------------------------------------------
# compute_dataset_hash
# ----------------------------------------------------------------------


def test_dataset_hash_has_sha256_prefix_and_64_hex() -> None:
    x_mat = np.arange(12, dtype=np.float64).reshape(4, 3)
    y = np.array([0, 1, 0, 1], dtype=np.int64)
    h = compute_dataset_hash(["a", "b", "c"], x_mat, y)
    assert h.startswith("sha256:")
    assert len(h) == len("sha256:") + 64
    assert all(c in "0123456789abcdef" for c in h[len("sha256:") :])


def test_dataset_hash_is_stable_for_fixed_xy() -> None:
    # Two calls with identical inputs give identical output; idempotency
    # catches any accidental non-deterministic code path in the hasher.
    x_mat = np.zeros((2, 2), dtype=np.float64)
    y = np.zeros(2, dtype=np.int64)
    h1 = compute_dataset_hash(["a", "b"], x_mat, y)
    h2 = compute_dataset_hash(["a", "b"], x_mat, y)
    assert h1 == h2


def test_dataset_hash_differs_on_permuted_feature_names() -> None:
    x_mat = np.arange(12, dtype=np.float64).reshape(4, 3)
    y = np.array([0, 1, 0, 1], dtype=np.int64)
    h1 = compute_dataset_hash(["a", "b", "c"], x_mat, y)
    h2 = compute_dataset_hash(["c", "b", "a"], x_mat, y)
    assert h1 != h2


def test_dataset_hash_differs_on_perturbed_x() -> None:
    rng = np.random.default_rng(0)
    x1 = rng.standard_normal((10, 3))
    x2 = x1.copy()
    x2[0, 0] += 1e-12
    y = np.zeros(10, dtype=np.int64)
    h1 = compute_dataset_hash(["a", "b", "c"], x1, y)
    h2 = compute_dataset_hash(["a", "b", "c"], x2, y)
    assert h1 != h2


def test_dataset_hash_rejects_non_string_feature_names() -> None:
    x_mat = np.zeros((1, 1))
    y = np.zeros(1)
    with pytest.raises(TypeError, match=r"list of strings"):
        compute_dataset_hash(["a", 1], x_mat, y)


def test_dataset_hash_handles_noncontiguous_arrays() -> None:
    # A F-contiguous slice must still hash identically to its
    # C-contiguous copy because the hasher ascontiguousarray-s.
    x_c = np.arange(12, dtype=np.float64).reshape(4, 3)
    x_f = np.asfortranarray(x_c)
    y = np.array([0, 1, 0, 1], dtype=np.int64)
    h_c = compute_dataset_hash(["a", "b", "c"], x_c, y)
    h_f = compute_dataset_hash(["a", "b", "c"], x_f, y)
    assert h_c == h_f


# ----------------------------------------------------------------------
# derive_artifact_stem
# ----------------------------------------------------------------------


def test_derive_artifact_stem_replaces_colons() -> None:
    stem = derive_artifact_stem(
        training_date_utc="2026-05-01T14:30:00Z",
        training_commit_sha="4cbbdfca9f2e1d7a6e3b0c8f9a2d1e4b5c6a7f8d",
    )
    assert stem == "2026-05-01T14-30-00Z_4cbbdfca"
    assert ":" not in stem  # Windows-safe


# ----------------------------------------------------------------------
# LogisticRegression round-trip (second allowed model type)
# ----------------------------------------------------------------------


def test_logreg_roundtrip_predicts_identically(git_repo: Path) -> None:
    rng = np.random.default_rng(0)
    x_mat = rng.standard_normal((100, 3))
    y = (x_mat[:, 0] > 0).astype(np.int64)
    lr = LogisticRegression(random_state=42).fit(x_mat, y)

    card = _make_card(commit_sha=_head_sha(git_repo), model_type="LogisticRegression")
    card["features_used"] = ["f0", "f1", "f2"]

    model_path, card_path = save_model(lr, card, git_repo / "models")
    loaded, _ = load_model(model_path, card_path)
    proba_before = lr.predict_proba(x_mat)
    proba_after = loaded.predict_proba(x_mat)
    assert np.array_equal(proba_before, proba_after)


# ----------------------------------------------------------------------
# Determinism + defensive-copy guards on the card
# ----------------------------------------------------------------------


def test_save_does_not_mutate_input_card(git_repo: Path) -> None:
    model, _, _ = _make_rf()
    card = _make_card(commit_sha=_head_sha(git_repo))
    snapshot = copy.deepcopy(card)
    save_model(model, card, git_repo / "models")
    assert card == snapshot
