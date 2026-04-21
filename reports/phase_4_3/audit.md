# Phase 4.3 — Baseline Meta-Labeler (Random Forest + LogReg) — Pre-implementation audit

| Field | Value |
|---|---|
| Branch | `phase/4.3-baseline-meta-labeler` |
| Date | 2026-04-14 |
| Issue | #127 |
| Predecessors | Phase 4.1 (PR #138 merged), Phase 4.2 (PR #139 merged) |
| Authors | Claude (Opus 4.6) + Clément Barbier (architect review pending) |
| Status | **READY — verdict CRÉER (new module tree `features/meta_labeler/`) ; plan §5 prêt à exécuter** |

---

## 0. TL;DR

Phase 4.3 crée un **nouvel arbre** `features/meta_labeler/` (4 modules) qui
implémente l'entraînement baseline du Meta-Labeler per **ADR-0005 D3**
(Random Forest primaire, LogReg baseline obligatoire) et **PHASE_4_SPEC
§3.3**. Il consomme directement :

1. `features/labeling/triple_barrier.py::label_events_binary` (Phase 4.1)
   pour la cible binaire `y` et les spans `t0 / t1`.
2. `features/labeling/sample_weights.py::combined_weights` (Phase 4.2)
   pour `sample_weight` passé à `fit()`.
3. `features/cv/cpcv.py::CombinatoriallyPurgedKFold` (Phase 3.10) pour
   les N=6, k=2 splits outer avec `embargo_pct=0.02`.
4. `features/integration/config.py::FeatureActivationConfig` (Phase 3.13)
   pour restreindre les features Phase 3 autorisées à
   `{gex_signal, har_rv_signal, ofi_signal}`.

Aucun module `features/meta_labeler/` n'existe aujourd'hui
(`ls features/meta_labeler/` → absent). L'unique fichier lié au
Meta-Labeler actuellement présent est
`services/fusion_engine/meta_labeler.py` : **rules-based deterministic
scorer, pas un classifieur entraîné**. PHASE_4_SPEC §2.3 le liste
explicitement :

> `features/meta_labeler/baseline.py` | 4.3 | Existing
> `services/fusion_engine/meta_labeler.py` is a deterministic rules
> scorer, not a trained classifier. Phase 4 introduces the trained-
> classifier path as a sibling module that will eventually replace the
> deterministic scorer in Phase 5 wiring.

Verdict **CRÉER** unanime : issue #127, ADR-0005 D3, PHASE_4_SPEC §3.3
convergent.

Nouvelle dépendance externe : **`scikit-learn`** (`RandomForestClassifier`,
`LogisticRegression`, `roc_auc_score`, `brier_score_loss`,
`calibration_curve`). À ajouter à `requirements.txt`.

---

## 1. Contrat canonique (ADR-0005 D3 + PHASE_4_SPEC §3.3)

Entraînement d'un Random Forest binaire sur un jeu de **8 features**
contextuelles, avec baseline LogisticRegression obligatoire tournée en
parallèle. CPCV outer à 6 groupes, 2-par-test → 15 folds OOS. Aucune
optimisation d'hyperparamètres (réservée à 4.4), aucun gate dur DSR/PBO
(réservés à 4.5).

### 1.1 Feature set (ADR-0005 D6 reproduit ici pour la clarté)

| # | Feature | Source | Encodage | Look-ahead |
|---|---|---|---|---|
| 1 | `gex_signal` | Phase 3 calculator (activated) | brut Float64 | ≤ `t0 - 1` |
| 2 | `har_rv_signal` | Phase 3 calculator (activated) | brut Float64 | ≤ `t0 - 1` |
| 3 | `ofi_signal` | Phase 3 calculator (activated) | brut Float64 | ≤ `t0 - 1` |
| 4 | `regime_vol_code` | S03 `regime_history` as-of `t0` | Ordinal Int8 `{LOW=0, NORMAL=1, HIGH=2, CRISIS=3}` | ≤ `t0` (as-of) |
| 5 | `regime_trend_code` | S03 `regime_history` as-of `t0` | Ordinal Int8 `{TRENDING_DOWN=-1, RANGING=0, TRENDING_UP=+1}` | ≤ `t0` (as-of) |
| 6 | `realized_vol_28d` | log-returns bars window closing ≤ `t0 - 1` | Float64 standardisé per-fold | ≤ `t0 - 1` |
| 7 | `hour_of_day_sin` | `t0.hour` | `sin(2π·h/24)` | néant (dérivé de `t0` lui-même) |
| 8 | `day_of_week_sin` | `t0.weekday()` | `sin(2π·d/7)` | néant (dérivé de `t0` lui-même) |

Total 8 features, alignées avec ADR-0005 D6 `features_used`. La variante
`cos` est volontairement omise au MVP pour respecter le budget 8 et sera
réévaluée par ablation en 4.4 (PHASE_4_SPEC §3.3 explicit).

### 1.2 Anti-leakage contract

Pour chaque sample *i* avec span `[t0_i, t1_i]` :

```
feature_compute_window_end(i) < t0_i     (strict <)   pour features 1-6
feature(i) dérivé de t0_i uniquement                  pour features 7-8
```

- Features 1-3 (Phase 3 signals) : consommées à `bars.timestamp < t0_i`
  (joined via `asof` backward).
- Features 4-5 (regime) : `regime_history.filter(ts <= t0_i).tail(1)`.
  La valeur à `t0_i` (si présente) est retenue — elle reflète l'état à
  l'ouverture du trade, pas après.
- Feature 6 (realized vol 28d) : écart-type des log-returns sur bars
  `[t0_i - 28·bar_length, t0_i - 1·bar_length]`. **Strictement** avant
  `t0_i`.
- Features 7-8 (time encoding) : dérivés mathématiquement de `t0_i`,
  pas de look-ahead possible.

Validation par property test Hypothesis : permuter toutes les bars
**strictement après** `max(t1)` du dataset ne doit changer aucune
valeur du `X` construit (même invariant que Phase 4.2).

---

## 2. Inventaire de l'existant

### 2.1 Assets directement consommés

| Asset | Chemin | Rôle en 4.3 | Phase 4.3 modifie ? |
|---|---|---|---|
| `label_events_binary` | `features/labeling/triple_barrier.py` | Source de `y`, `t0`, `t1`. Colonnes consommées : `binary_target`, `t0`, `t1`. | **Non** — lecture seule. |
| `combined_weights` | `features/labeling/sample_weights.py` | Source de `sample_weight` passé à `fit()`. | **Non** — import only. |
| `CombinatoriallyPurgedKFold` | `features/cv/cpcv.py` | Outer CV, `n_splits=6, n_test_splits=2, embargo_pct=0.02`. Signature `split(X, t1, t0=...)` déjà compatible. | **Non** — lecture seule. |
| `FeatureActivationConfig` | `features/integration/config.py` | Garde-fou : rejette toute feature non activée en Phase 3.12. | **Non** — import only. |
| `VolRegime`, `TrendRegime` | `core/models/regime.py` | Enums sources pour encodage ordinal. | **Non** — lecture seule. |

### 2.2 Paths neufs créés

```
features/meta_labeler/
├── __init__.py                     (~30 LOC, re-exports)
├── feature_builder.py              (~230 LOC)
├── baseline.py                     (~180 LOC)
└── metrics.py                      (~90 LOC)

tests/unit/features/meta_labeler/
├── __init__.py                     (empty marker)
├── test_feature_builder.py         (~14 tests)
├── test_baseline_training.py       (~10 tests)
└── test_baseline_metrics.py        (~6 tests)

reports/phase_4_3/
├── audit.md                        (this file)
└── baseline_report.md              (diagnostic, post-implementation)

requirements.txt                    (scikit-learn added)
```

### 2.3 Assets explicitement **non touchés**

- `services/fusion_engine/meta_labeler.py` — le scorer rules-based
  reste en place, non modifié ; Phase 5 décidera du remplacement.
- `features/pipeline.py` — aucune consommation du nouveau module en
  Phase 4 MVP (entraînement offline).
- `features/weights.py::SampleWeighter` — déjà préservé en Phase 4.2 ;
  aucun nouveau consommateur.

---

## 3. Surface d'API publique proposée

Strictement conforme à PHASE_4_SPEC §3.3, sans ajout.

```python
# features/meta_labeler/feature_builder.py

@dataclass(frozen=True)
class MetaLabelerFeatureSet:
    X: np.ndarray                         # (n_samples, 8) float64
    feature_names: tuple[str, ...]        # len == 8
    t0: np.ndarray                        # (n_samples,) datetime64[us]
    t1: np.ndarray                        # (n_samples,) datetime64[us]


class MetaLabelerFeatureBuilder:
    def __init__(
        self,
        activation_config: FeatureActivationConfig,
        regime_history: pl.DataFrame,    # cols: timestamp, vol_regime, trend_regime
        realized_vol_window: int = 28,
    ) -> None: ...

    def build(
        self,
        labels: pl.DataFrame,            # cols: t0, t1, binary_target
        signals: pl.DataFrame,           # cols: timestamp, gex_signal, har_rv_signal, ofi_signal
        bars: pl.DataFrame,              # cols: timestamp, close
    ) -> MetaLabelerFeatureSet: ...


# features/meta_labeler/baseline.py

@dataclass(frozen=True)
class BaselineTrainingResult:
    rf_model: RandomForestClassifier
    logreg_model: LogisticRegression
    rf_auc_per_fold: tuple[float, ...]          # len == 15
    logreg_auc_per_fold: tuple[float, ...]      # len == 15
    rf_brier_per_fold: tuple[float, ...]        # len == 15
    rf_calibration_bins: tuple[tuple[float, float], ...]   # (mean_pred, frac_positives) × 10 bins
    feature_importances: dict[str, float]       # sums to ~1.0


class BaselineMetaLabeler:
    def __init__(
        self,
        cpcv: CombinatoriallyPurgedKFold,
        rf_hyperparameters: dict[str, Any] | None = None,
        seed: int = 42,
    ) -> None: ...

    def train(
        self,
        features: MetaLabelerFeatureSet,
        y: np.ndarray,
        sample_weights: np.ndarray,
    ) -> BaselineTrainingResult: ...


# features/meta_labeler/metrics.py

def fold_auc(y_true, y_prob, sample_weight=None) -> float: ...
def fold_brier(y_true, y_prob, sample_weight=None) -> float: ...
def calibration_bins(y_true, y_prob, n_bins: int = 10) -> list[tuple[float, float]]: ...
```

**Invariants publics :**

- Déterministe sous `seed` fixé (test `test_baseline_rf_training_deterministic_same_seed`).
- `feature_importances` somme à ~1.0 (test `test_baseline_feature_importances_sum_to_1_approx`).
- LogReg est **toujours** entraîné aux côtés du RF (test
  `test_baseline_logreg_baseline_always_trained` — garantit ADR-0005 D3).
- `sample_weights` doit être propagé à `fit()` via `sample_weight=` (test
  `test_baseline_sample_weights_propagated_to_fit` avec mock).
- `class_weight="balanced"` appliqué aux deux modèles (test direct sur
  `model.get_params()`).

---

## 4. Scope hors 4.3 (explicitement déféré)

| Hors-scope | Renvoyé à |
|---|---|
| Hyperparameter tuning (GridSearchCV nested) | 4.4 (#128) |
| DSR ≥ 0.95, PBO < 0.10 (gates durs ADR-0005 D5) | 4.5 (#129) |
| Persistence du `rf_model` + model card JSON | 4.6 (#130) |
| Fusion engine IC-weighted (D7) | 4.7 (#131) |
| End-to-end pipeline test | 4.8 (#132) |
| Audit de leakage mi-phase | #134 (déclenché post-4.3) |
| Wiring en S02/S04 live | Phase 5 |
| LogReg tuning | jamais (ADR-0005 D3 : baseline doit rester non-tuné) |

DoD smoke gate **AUC RF OOS ≥ 0.55** sur un scénario synthétique à alpha
calibré. Le hard gate `AUC ≥ 0.55 && RF - LogReg ≥ 0.03` est en 4.5, pas ici.

---

## 5. Plan d'exécution (5 étapes)

1. **Audit + branch** (ce commit) — pousser `reports/phase_4_3/audit.md`
   sur `phase/4.3-baseline-meta-labeler`.
2. **Dépendance** — ajouter `scikit-learn>=1.5.0,<2.0.0` à
   `requirements.txt` + `pyproject.toml` si section dependencies
   présente.
3. **Implémentation** — écrire les 4 modules + `__init__.py` dans
   l'ordre `metrics → feature_builder → baseline → __init__`.
4. **Tests** — minimum 30 tests :
   - 14 tests `test_feature_builder.py` (shape, as-of regime, realized
     vol window, cyclical wrap, fail-loud sur feature non activée,
     fail-loud sur regime absent, anti-leakage property test).
   - 10 tests `test_baseline_training.py` (déterminisme, LogReg toujours
     entraîné, AUC per fold retourné, feature_importances sum ≈ 1,
     sample_weights propagé, class_weight balanced appliqué,
     calibration bins monotone sur alpha synthétique, AUC > 0.55 sur
     fixture synthétique à alpha, RF − LogReg reporté, edge cases).
   - 6 tests `test_baseline_metrics.py` (fold_auc, fold_brier,
     calibration_bins shape & range, sample_weight pass-through).
   - Cible coverage **≥ 90 %** sur `features/meta_labeler/`
     (PHASE_4_SPEC §3.3 DoD #1).
5. **Rapport diagnostic** — `reports/phase_4_3/baseline_report.md`
   généré depuis fixture synthétique `APEX_SEED=42` :
   - Table per-fold RF AUC / LogReg AUC / RF Brier.
   - Feature importances triées.
   - 10-bin calibration curve (JSON bundled + ASCII table).
   - Smoke gate pass/fail (AUC ≥ 0.55).

Quality gates : `ruff check`, `ruff format --check`, `mypy --strict`,
pytest + coverage ≥ 90 %, même workflow que 4.2.

---

## 6. Risques identifiés

| Risque | Sévérité | Mitigation |
|---|---|---|
| Synthetic fixture n'atteint pas AUC ≥ 0.55 | Moyenne | Fixture calibrée : un des 3 signaux (`ofi_signal`) corrèle à ~0.12 avec le ternary_label via une fonction de drift contrôlée. Tuning de la force d'alpha avant gel du seed. |
| `regime_history` vide à `t0` pour un sample | Haute (fail-loud requis) | `test_feature_builder_missing_regime_at_t0_raises_fail_loud` — raise `ValueError("regime_history is empty at or before t0=...")`. Pas de silent ffill. |
| sklearn absent du sandbox CI | Moyenne | Ajout explicite dans `requirements.txt`. CI installe tout via `pip install -e .` ou `pip install -r requirements.txt`. |
| Coverage < 90 % sur `baseline.py` (beaucoup de code dans la boucle training) | Moyenne | Tester chaque branche via mocks de `RandomForestClassifier.fit` pour isoler la logique d'orchestration. Private helpers testés directement. |
| CRLF / LF noise sur Windows | Faible | Disciplined `git add <specific paths>` + `sed -i 's/\r$//'` si besoin (pattern Phase 4.2). |
| `np.float64` vs `np.float32` precision pour `feature_importances` sum | Faible | Tolérance `abs(sum - 1.0) < 1e-6`. |

---

## 7. Références

- Issue #127 (GitHub) — Baseline Meta-Labeler.
- [`docs/adr/ADR-0005-meta-labeling-fusion-methodology.md`](../../docs/adr/ADR-0005-meta-labeling-fusion-methodology.md) §§ D3, D4, D6.
- [`docs/phases/PHASE_4_SPEC.md`](../../docs/phases/PHASE_4_SPEC.md) §3.3 (pp. 415-605).
- López de Prado (2018), *Advances in Financial Machine Learning*, §3.6
  (pp. 50-55) Meta-Labeling.
- Breiman, L. (2001). *Random Forests*. Machine Learning 45, 5–32.
- [`reports/phase_4_2/audit.md`](../phase_4_2/audit.md) — patron de rédaction.
