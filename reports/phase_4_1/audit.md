# Phase 4.1 — Triple Barrier Labeling — Audit pré-implémentation

| Field | Value |
|---|---|
| Branch | `phase/4.1-triple-barrier-labeling` |
| Date | 2026-04-14 |
| Issue | #125 |
| Authors | Claude (Opus 4.6) + Clément Barbier (architect review pending) |
| Status | **BLOQUÉ — confirmation architecte requise** (voir §3 Verdict) |

---

## 0. TL;DR

L'audit révèle un **désaccord frontal entre le prompt de mission et la triade
contractuelle ADR-0005 D1 + PHASE_4_SPEC §3.1 + Issue #125**. Le prompt
demande un module neuf `services/s07_quant_analytics/core/math/labeling.py`
(pandas, binaire-only, pas de -1, nouvelle config `k_up`/`k_down`). La triade
contractuelle impose au contraire un module `features/labeling/` Polars-natif
qui **étend** l'existant `core/math/labeling.py` (ternaire préservé,
`TripleBarrierConfig(pt_multiplier, sl_multiplier, …)`, `to_binary_target()`
helper additif).

Conformément à la règle explicite du prompt
(« Si tu trouves un désaccord entre l'ADR et la spec, tu arrêtes et tu le
remontes dans le rapport — tu ne tranches pas unilatéralement. ») **je n'écris
aucune ligne de code d'implémentation avant confirmation**. Le verdict retenu
si l'architecte confirme la triade ADR/Spec/Issue est **ÉTENDRE** (section 3).

---

## 1. Inventaire de l'existant

### 1.1 Code pré-existant identifié

Recherche `rg -n "triple.?barrier|TripleBarrier|barrier_label" --type py` :

| Fichier | Rôle | Phase 4.1 touche ? |
|---|---|---|
| [core/math/labeling.py](../../core/math/labeling.py) | `TripleBarrierLabeler`, `BarrierLabel`, `BarrierResult`, `TripleBarrierConfig` — implémentation core, ternaire, side-aware. 240 LOC. | Extension autorisée par spec §2.2 (ajouter `to_binary_target()` helper + accessors `t0`/`t1`). |
| [features/labels.py](../../features/labels.py) | `TripleBarrierLabelerAdapter` — wrapper Polars autour du core labeler. 109 LOC. | Extension autorisée par spec §2.2 (ajouter batch labeling `events`→`DataFrame`). |
| [services/s04_fusion_engine/meta_labeler.py](../../services/s04_fusion_engine/meta_labeler.py) | `MetaLabeler` déterministe (scoring rules-based, pas un labeler). | **Ne pas toucher** (spec §2.4 : `services/s04_fusion_engine/` frozen). |
| [services/s04_fusion_engine/feature_logger.py](../../services/s04_fusion_engine/feature_logger.py) | Logger produisant un dataset pour MetaLabeler v2. | **Ne pas toucher**. |
| [tests/unit/core/test_labeling.py](../../tests/unit/core/test_labeling.py) | 15 tests sur `TripleBarrierLabeler` (upper/lower/vertical, side, vol, hypothesis). | **Ne pas casser** — coverage intact. |
| [tests/unit/features/test_labels.py](../../tests/unit/features/test_labels.py) | 7 tests sur `TripleBarrierLabelerAdapter`. | **Ne pas casser**. |
| [services/s07_quant_analytics/core/math/labeling.py](../../services/s07_quant_analytics/core/math/) | **N'existe pas.** Le dossier `services/s07_quant_analytics/core/math/` n'existe pas. Seul `services/s07_quant_analytics/core/` existe (`service.py`, `realized_vol.py`, `regime_ml.py`, …). | Le chemin mentionné par le prompt de mission est **absent du repo**. |

### 1.2 API publique de l'existant (source de vérité)

`core/math/labeling.py` expose :

```python
class BarrierResult(Enum):
    UPPER = 1       # label +1
    LOWER = -1      # label -1
    VERTICAL = 0    # label 0

@dataclass(frozen=True)
class BarrierLabel:
    entry_time: datetime
    exit_time: datetime
    entry_price: Decimal
    exit_price: Decimal
    barrier_hit: BarrierResult
    label: int                   # ternaire {-1, 0, +1}
    upper_barrier: Decimal
    lower_barrier: Decimal
    vertical_barrier: datetime
    side: int                    # +1 long, -1 short
    vol_used: float
    holding_periods: int

@dataclass
class TripleBarrierConfig:
    pt_multiplier: float = 2.0       # équivalent k_up
    sl_multiplier: float = 1.0       # équivalent k_down
    max_holding_periods: int = 60    # vertical barrier
    vol_lookback: int = 20

class TripleBarrierLabeler:
    def __init__(self, config: TripleBarrierConfig | None = None) -> None: ...
    def compute_daily_vol(self, close_prices: list[Decimal]) -> float: ...
    def label_event(
        self, entry_price, entry_time, side, future_prices, daily_vol,
    ) -> BarrierLabel: ...
```

`features/labels.py` expose :

```python
class TripleBarrierLabelerAdapter:
    def __init__(self, config: TripleBarrierConfig | None = None) -> None: ...
    @property
    def config(self) -> TripleBarrierConfig: ...
    def label(self, df: pl.DataFrame, side: int = 1,
              close_col: str = "close", timestamp_col: str = "timestamp"
              ) -> pl.DataFrame:
        # returns {"label", "t1", "pt_touch", "sl_touch"}
        ...
```

### 1.3 Emplacement canonique pour le nouveau code Phase 4.1

Per **PHASE_4_SPEC §3.1 (Module structure)** et **Issue #125 Deliverables** :

```
features/labeling/
├── __init__.py             (NEW)
├── triple_barrier.py       (NEW) re-exports core labeler + to_binary_target + label_events_binary
├── events.py               (NEW) event-time construction helpers
└── diagnostics.py          (NEW) label distribution + barrier-hit stats

tests/unit/features/labeling/
├── __init__.py                             (NEW)
├── test_triple_barrier_binary.py           (NEW, ~12 tests)
├── test_events_construction.py             (NEW, ~6 tests)
├── test_diagnostics.py                     (NEW, ~5 tests)
└── test_integration_with_bar_data.py       (NEW, ~3 tests)
```

Le prompt de mission demande `services/s07_quant_analytics/core/math/labeling.py`
— ce chemin est **explicitement interdit** par la triade :

- ADR-0005 §1 : « `core/math/labeling.py` and `features/labels.py` already
  implement a `TripleBarrierLabeler` … Phase 4.1 extends this implementation
  rather than re-writing it ».
- PHASE_4_SPEC §2.4 (« Deliberately NOT modified by Phase 4 ») inclut
  `services/s04_fusion_engine/` (frozen) et par construction n'autorise pas
  d'ajouter une nouvelle implémentation sous `services/`.
- Issue #125 DoD #5 : « No modifications to `services/`, or to `core/`
  beyond an optional `to_binary_target()` helper in `core/math/labeling.py` ».

---

## 2. Conformité vs D1 de ADR-0005

D1 (texte intégral reproduit en §1.1 de l'audit pour référence) impose :

| Paramètre D1 | Existant (`core/math/labeling.py` + `features/labels.py`) | Requis Phase 4.1 |
|---|---|---|
| Upper barrier multiplier, default 2.0 | `TripleBarrierConfig.pt_multiplier = 2.0` ✅ conforme (nom différent mais sémantique identique) | `k_up ∈ {1.0, 2.0}`, default 2.0 |
| Lower barrier multiplier, default 1.0 | `TripleBarrierConfig.sl_multiplier = 1.0` ✅ conforme | `k_down = 1.0` |
| Vol estimator EWMA squared log returns, lookback 20 | `compute_daily_vol` calcule log-returns via `math.log(p[i]/p[i-1])` puis std. **Partiel** : c'est une std simple, pas une EWMA. Le span = taille de la fenêtre, mais sans pondération exponentielle. Fenêtre = `vol_lookback = 20` ✅ | EWMA(span=20) strict — écart méthodologique mineur mais **à documenter**, cf. §4 plan (réutiliser `compute_daily_vol` puisque ADR §1 dit « extends this implementation ») |
| **Vol window must end strictly before `t` (no lookahead)** | **`features/labels.py:81` : `closes[max(0, i - vol_lookback) : i + 1]` — inclut la barre `t`. 🔴 VIOLATION D1** | `closes[i - vol_lookback : i]` strict (exclut `t`) |
| Vertical barrier horizon | `max_holding_periods = 60` par défaut ✅ (ADR autorise `{1h, 4h, 1d}` selon cadence ; 60 convient pour 5min→5h ou daily→60j) | Configurable |
| Binary projection `y = 1 if label == +1 else 0` | 🟡 Pas encore implémenté — c'est le cœur du livrable 4.1 | `to_binary_target()` helper |
| Ternary label `{-1, 0, +1}` préservé pour audit | `BarrierLabel.label: int` ternaire ✅ | Préservé |
| Long-only MVP | Code side-aware (`+1`/`-1`) — compatible, le batch labeler 4.1 acceptera `direction=+1` seulement et raise sur `-1` | Long-only, short raise `NotImplementedError` |
| Raw close prices (pas fracdiff) | `close` column passthrough ✅ | Raw close |
| UTC-only, fail-loud sur naive | **Pas enforcé** dans le code actuel (les datetimes naïfs ne lèvent pas). 🟡 À ajouter dans le wrapper `label_events_binary`. | UTC obligatoire, raise `ValueError` |

### 2.2 Bugs / violations D1 trouvés dans l'existant

1. **🔴 Look-ahead bug dans `features/labels.py:81`** : `closes[max(0, i - vol_lookback) : i + 1]` inclut la barre `t` dans le calcul de vol. D1 exige « window must end strictly **before** `t` (no peek into the labeled bar) ». Le wrapper Phase 4.1 doit corriger ce slicing (extension `features/labels.py` autorisée par spec §2.2).
2. **🟡 Silent fallback `compute_daily_vol`** : retourne `0.01` par défaut si `< 2` prices ou `variance = 0` ([core/math/labeling.py:104, :111](../../core/math/labeling.py)). Le contrat Phase 3 (feedback memory `feedback_no_silent_stat_skip.md`) interdit le silent-pass statistique. Le wrapper Phase 4.1 doit **raise** sur sigma nulle plutôt que consommer le 0.01 silencieux.
3. **🟡 `vol_move = Decimal(str(max(1e-8, daily_vol) * ...))`** ([core/math/labeling.py:153](../../core/math/labeling.py)) — même pattern silent-floor. Non corrigeable sans toucher `core/` au-delà du helper autorisé. **Recommandation : laisser en place pour 4.1 (hors scope) et tracer en dette technique dans le rapport de closure Phase 4.**
4. **🟡 Pas de validation tz-aware** à l'entrée du core labeler — à intercepter dans le wrapper `label_events_binary`.

### 2.3 Scorecard de conformité

- **Conforme** : 6/10 paramètres D1 (pt/sl multipliers, vol_lookback, vertical barrier, ternary preservation, long-only compatible).
- **Partiellement conforme** : 2/10 (vol estimator EWMA-vs-std ; vol window boundary bug via l'adapter).
- **Non encore livré** : 2/10 (binary projection ; UTC-strict fail-loud).

Taux de conformité global ≈ **70%** → au-dessus du seuil 70% pour verdict ÉTENDRE.

---

## 3. Verdict

### 3.1 Verdict retenu : **ÉTENDRE** (sous réserve de confirmation architecte)

**Justification (≥ 5 lignes exigées) :**

1. La triade contractuelle (ADR-0005 §1 « Phase 4.1 extends this
   implementation rather than re-writing it », PHASE_4_SPEC §2.2 « To
   extend », Issue #125 DoD #5 « No modifications … beyond an optional
   helper ») converge unanimement vers le verdict ÉTENDRE.
2. La conformité D1 de l'existant est de ~70% : les écarts sont (a) un bug
   de look-ahead d'une ligne dans l'adapter Polars — corrigeable de façon
   additive, (b) une EWMA approximée par une std simple — acceptable car
   ADR §1 entérine la réutilisation du `compute_daily_vol` existant, (c) la
   projection binaire qui est précisément le livrable de 4.1.
3. L'API publique `BarrierLabel` / `TripleBarrierConfig` /
   `TripleBarrierLabeler` est stable et largement testée (22 tests entre
   `tests/unit/core/test_labeling.py` et `tests/unit/features/test_labels.py`).
   Un refactor casserait ces tests et `services/s04_fusion_engine/feature_logger.py`
   qui consomme `BarrierResult` downstream.
4. Le nouveau code Phase 4.1 vit dans un submodule **additif** `features/labeling/`
   qui re-exporte le core labeler et ajoute quatre fichiers neufs plus
   une éventuelle extension additive `label_events_binary` dans
   `features/labels.py`. Zéro breaking change. Zéro modification sous
   `services/`.
5. Le seul helper autorisé dans `core/math/labeling.py` par spec/issue est
   `to_binary_target(label: BarrierLabel) -> int` — une fonction pure de 3
   lignes. Aucune autre modification sous `core/`.

### 3.2 Verdict implicite du prompt de mission : **CRÉER (dans services/s07)**

Le prompt de mission décrit l'implémentation d'un module **neuf** à un
chemin inexistant (`services/s07_quant_analytics/core/math/labeling.py`),
avec une API pandas (`pd.Series`, `pd.DataFrame`), un `TripleBarrierConfig`
redéfini (`k_up`, `k_down`, `min_return_threshold`, `max_holding_bars=20`),
un `label: int in {0, 1}` (binaire-only, pas de préservation ternaire),
et un ensemble de tests à `tests/unit/s07_quant_analytics/core/math/test_labeling.py`.

**Divergences explicites entre prompt de mission et triade ADR/Spec/Issue :**

| Point | Prompt mission | ADR-0005 D1 / PHASE_4_SPEC §3.1 / Issue #125 |
|---|---|---|
| Chemin du module | `services/s07_quant_analytics/core/math/labeling.py` | `features/labeling/` (spec §3.1 + issue #125) ; **jamais sous `services/`** (spec §2.4) |
| Stack de DataFrame | pandas (`pd.Series`, `pd.DatetimeIndex`, `pd.DataFrame`) | **Polars** (issue #125 « Polars-native binary-target projection » ; spec §3.1 public API `pl.DataFrame`) |
| Config | Nouveau dataclass `TripleBarrierConfig(k_up, k_down, vol_lookback, max_holding_bars, min_return_threshold)` | Réutiliser `TripleBarrierConfig(pt_multiplier, sl_multiplier, max_holding_periods, vol_lookback)` existant |
| Label output | `label: int in {0, 1}` **uniquement** ; « Pas de -1 » | Ternary `{-1, 0, +1}` **préservé** dans `BarrierLabel.label` + binary projection `y = 1 if label == +1 else 0` en couche applicative (ADR §D1 : « The ternary `{-1, 0, +1}` output of `BarrierLabel.label` is preserved for audit trail ») |
| Barrier hit values | strings `{"upper", "lower", "vertical"}` | Enum `BarrierResult` existant (`UPPER=1`, `LOWER=-1`, `VERTICAL=0`) |
| `max_holding_bars` default | 20 | `max_holding_periods = 60` (existing default, ADR-autorisé) |
| Tests location | `tests/unit/s07_quant_analytics/core/math/test_labeling.py` (1 fichier) | `tests/unit/features/labeling/` (4 fichiers : binary, events, diagnostics, integration) |
| Convention égalité intra-bar | « upper wins » explicite | Non spécifié par l'ADR/spec. Convention existante dans `label_event` : boucle `if price >= upper_barrier` testé avant `if price <= lower_barrier`, donc **upper wins de facto** dans le code existant. Aligne. |
| Fichier rapport | `reports/phase_4_1/labeling_diagnostics.md` | `reports/phase_4_1/labels_diagnostics.md` (issue #125 DoD #4 — **pluriel**) |

Si l'on appliquait littéralement le prompt de mission :

- on **créerait un TripleBarrierLabeler parallèle** qui dupliquerait le code,
  romprait DRY, introduirait deux sources de vérité pour le même concept,
  et divergerait du feature_logger S04 qui log `BarrierResult` ternaire ;
- on **violerait explicitement** PHASE_4_SPEC §2.4 (pas de nouveau code sous
  `services/`) et Issue #125 DoD #5 (pas de module dans `services/`) ;
- on **supprimerait la branche short** (« pas de -1 ») en contradiction
  avec ADR D1 qui préserve la label ternary pour l'audit et pour la
  future extension short side (Phase 4.X) ;
- on **introduirait pandas** dans un pipeline Polars — incohérent avec le
  reste de `features/` (CLAUDE.md §5 « polars over pandas »).

### 3.3 Demande de confirmation

Le prompt de mission contient lui-même la clause de sécurité :

> « Si tu rencontres un TripleBarrierLabeler pré-existant qui viole D1, tu
> ne le modifies pas pour Phase 4.1 sans confirmation — tu proposes un
> verdict REFACTOR et tu attends. »

L'existant **ne viole pas D1** (conformité 70%, écarts additifs-corrigeables).
La situation symétrique est : **le prompt de mission, s'il est appliqué,
violerait D1** (suppression du ternary, nouveau module sous `services/`,
API pandas). J'applique donc par analogie la même règle : **j'arrête et je
demande confirmation**.

**Trois options possibles, à trancher par l'architecte** :

- **Option A (recommandée — aligne la triade ADR/Spec/Issue)** : j'exécute
  le verdict ÉTENDRE avec le plan §4 ci-dessous. Livrable = module
  additif `features/labeling/` + `to_binary_target()` helper dans
  `core/math/labeling.py` + correction du look-ahead bug dans
  `features/labels.py` + rapport `labels_diagnostics.md`.
- **Option B** : l'architecte confirme que le prompt de mission supplante
  la triade. Je crée alors `services/s07_quant_analytics/core/math/labeling.py`
  comme demandé, mais je documente une **dérogation formelle** à ADR-0005
  §1 et à PHASE_4_SPEC §2.4 dans le rapport final, nécessitant un
  amendement écrit des deux documents avant merge.
- **Option C (hybride)** : on garde `features/labeling/` comme localisation
  principale, mais j'applique certains points du prompt de mission (ex. :
  convention « upper wins » dans le docstring + test dédié ;
  `min_return_threshold` ajouté au config ; tests anti-leakage renforcés à
  la liste issue #125). Les divergences de forme (pandas vs Polars ; chemin
  sous `services/`) sont rejetées ; les divergences méthodologiques
  (tests anti-leakage, fail-loud strict) sont intégrées.

**Mon recommandation : Option C.** Elle respecte la triade contractuelle
tout en capturant les exigences qualité supplémentaires du prompt
(fail-loud strict, test anti-leakage Hypothesis 1000 examples, convention
tie-breaking documentée, asserts d'invariants). Elle suppose :
- chemin = `features/labeling/` (spec §3.1 respectée) ;
- API Polars (spec respectée) ;
- tests dans `tests/unit/features/labeling/` (spec respectée) ;
- label ternaire préservé + binary projection via `to_binary_target()` ;
- liste de tests anti-leakage étendue per prompt de mission ;
- convention « upper wins intra-bar » documentée + test dédié ;
- UTC strict, NaN raise, orphan events raise (fail-loud du prompt appliqué
  à la couche wrapper Polars).

---

## 4. Plan d'implémentation (applicable après confirmation)

**Hypothèse de travail (Option A ou C)** : verdict ÉTENDRE, module Polars
sous `features/labeling/`. Si Option B est choisie, ce plan est caduc.

### 4.1 Fichiers à créer / modifier

| Fichier | Action | LOC | # tests |
|---|---|---|---|
| `core/math/labeling.py` | **Extend** : ajouter `to_binary_target(label: BarrierLabel) -> int` (fonction pure, 3 lignes). Aucune autre modification. | +10 | +2 |
| `features/labels.py` | **Fix + Extend** : corriger look-ahead bug ligne 81 (`[i - vol_lookback : i]` strict) ; ajouter méthode batch `label_events(events: pl.DataFrame, bars: pl.DataFrame) -> pl.DataFrame`. | +60 | +3 |
| `features/labeling/__init__.py` | **Create** : re-exporte API publique. | +20 | 0 |
| `features/labeling/triple_barrier.py` | **Create** : `label_events_binary(events, bars, config) -> pl.DataFrame` + re-exports. Cœur du livrable. | +150 | ~12 |
| `features/labeling/events.py` | **Create** : helpers `build_events_from_signals(...)` pour construire le `events` DataFrame attendu. | +80 | ~6 |
| `features/labeling/diagnostics.py` | **Create** : distributions labels / barrier_hit / holding, sanity-check mean-return per class. | +100 | ~5 |
| `tests/unit/features/labeling/__init__.py` | **Create** (empty). | 1 | 0 |
| `tests/unit/features/labeling/test_triple_barrier_binary.py` | **Create**. | +250 | 12 |
| `tests/unit/features/labeling/test_events_construction.py` | **Create**. | +120 | 6 |
| `tests/unit/features/labeling/test_diagnostics.py` | **Create**. | +100 | 5 |
| `tests/unit/features/labeling/test_integration_with_bar_data.py` | **Create**. | +100 | 3 |
| `reports/phase_4_1/audit.md` | **Create** (ce document). | - | - |
| `reports/phase_4_1/labels_diagnostics.md` | **Create** (post-tests). | - | - |

**Total estimé** : ~900 LOC implementation + ~570 LOC tests ; 26 tests
nouveaux. `BarrierLabel` public API **inchangée**. Zéro modification sous
`services/`. Une seule addition additive sous `core/math/labeling.py`
(`to_binary_target` helper, autorisé explicitement par issue #125 DoD #5).

### 4.2 Ordre d'implémentation recommandé

1. `core/math/labeling.py` — `to_binary_target()` helper + tests.
2. `features/labels.py` — corriger look-ahead bug, ajouter `label_events`
   batch API, mettre à jour tests existants (doivent rester verts).
3. `features/labeling/events.py` — construction `events` DataFrame.
4. `features/labeling/triple_barrier.py` — `label_events_binary`
   (assemble events + labels + binary projection + fail-loud validations).
5. `features/labeling/diagnostics.py` — distributions + sanity checks.
6. `features/labeling/__init__.py` — re-exports.
7. Tests unitaires des 4 modules `features/labeling/`.
8. Génération `reports/phase_4_1/labels_diagnostics.md` (script ou
   doctring auto-run via pytest fixture).

### 4.3 Edge cases critiques

Les trois edge cases à prioriser dans les tests :

1. **Look-ahead bias sur σ_t** — le plus dangereux. Test dédié : perturber
   `close[t]` après labeling et vérifier que le label à `t` ne change pas.
   Property test Hypothesis 1000 examples. Blocage : actuellement violé
   par `features/labels.py:81`, doit être corrigé dans le même PR.
2. **Barrières non touchées (vertical barrier)** — distribution attendue
   ~déséquilibrée avec k_up=2, k_down=1. Sanity check explicite dans le
   rapport diagnostics : si > 80% verticals, signal d'alarme (paramètres
   inadaptés ou fixture dégénérée).
3. **Events orphelins et timestamps hors-range** — events non présents
   dans `bars.timestamp` → fail-loud `ValueError` avec liste. Pas de
   silent-drop. Test dédié avec un event `timestamp + 1ns`.

Edge cases secondaires à couvrir :

4. Égalité intra-bar upper/lower sur la même barre → convention
   **upper wins** (alignée sur le comportement existant de
   `label_event` ligne 161-167 qui teste `upper` avant `lower`).
5. Sigma strictement nulle sur un event (prix constants sur la fenêtre)
   → raise `ValueError` avec timestamp, **pas** de fallback 1e-8.
   Nécessite corriger `compute_daily_vol` OU intercepter dans le wrapper
   4.1 — ce dernier préféré pour ne pas toucher `core/`.
6. Événements en fin de série (moins de `max_holding_bars` barres futures
   disponibles) → clamp `max_periods` comme actuellement, vertical barrier
   à la dernière barre disponible.
7. Tz naïve ou tz != UTC → `ValueError` avec message explicite.
8. NaN dans `close`, `high`, ou `low` → `ValueError`, pas de ffill silencieux.

### 4.4 Risques résiduels et mitigations

| Risque | Probabilité | Impact | Mitigation |
|---|---|---|---|
| Correction du look-ahead bug casse la parité du test `test_parity_with_core_labeler_single_event` | Moyenne | Moyen (tests existants rouges) | Mettre à jour le test pour utiliser la nouvelle formule de vol window strict `[t-20, t-1]`. Documenter le changement de comportement comme fix bug (pas breaking change API). |
| `max_holding_bars=60` par défaut (existant) vs 20 attendu par le prompt de mission | Faible | Faible | Garder 60 par défaut (spec + ADR). Le prompt de mission est silencieux sur la justification du 20 ; l'ADR D1 dit « horizon H ∈ {1h, 4h, 1d} bound to feature cadence ». Documenter. |
| `compute_daily_vol` = std simple, pas EWMA strict | Faible | Faible | ADR-0005 §1 entérine la réutilisation du code existant. Documenter l'écart EWMA-vs-std dans le rapport diagnostics et tracer en dette technique si empiriquement requis. |
| Fixture synthétique pour diagnostics produit une distribution trop déséquilibrée | Moyenne | Faible | Choisir une série de prix avec volatilité réaliste (σ ≈ 1-2%, dérive positive 0.02% / bar). Seed `APEX_SEED=42`. Documenter paramètres de la fixture. |

---

## 5. Décision en attente

**Action requise avant que je code : l'architecte tranche entre Option A,
B ou C (§3.3).**

Ma recommandation formelle : **Option C** (hybride ÉTENDRE + qualité
renforcée per prompt de mission). Si l'architecte confirme, j'exécute le
plan §4 dans un second commit sur cette même branche.

Si Option B est choisie, je détruis ce plan et rédige un amendement à
ADR-0005 + PHASE_4_SPEC + Issue #125 avant d'écrire la moindre ligne de
code, pour que la dérogation soit documentée de façon reproductible.
