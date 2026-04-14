# Phase 4.2 — Sample Weights (uniqueness × return attribution) — Audit pré-implémentation

| Field | Value |
|---|---|
| Branch | `phase/4.2-sample-weights` |
| Date | 2026-04-14 |
| Issue | #126 |
| Predecessor | Phase 4.1 (PR #138 merged) |
| Authors | Claude (Opus 4.6) + Clément Barbier (architect review pending) |
| Status | **READY — verdict CRÉER (new sibling module) ; plan §4 prêt à exécuter** |

---

## 0. TL;DR

Contrairement à la Phase 4.1 (qui ÉTENDAIT un labeler existant),
Phase 4.2 **crée un module canonique neuf** `features/labeling/sample_weights.py`
conformément à **PHASE_4_SPEC §2.3** qui liste explicitement ce module
dans la colonne « To create (no pre-existing equivalent) » avec la
justification : *« Uniqueness + return-attribution weights do not exist
anywhere in the repo »*.

Cela **ne contredit pas** l'existence de `features/weights.py::SampleWeighter`
(143 LOC, Phase 3.1), qui est une **API duration-weighted datetime-based**
consommée par `features/pipeline.py` et 21 tests. Les deux modules coexistent
de façon explicite :

| Aspect | `features/weights.py::SampleWeighter` (existant, Phase 3.1) | `features/labeling/sample_weights.py` (neuf, Phase 4.2) |
|---|---|---|
| Canonicalité | Prototype duration-weighted — pas la formule López de Prado §4.4 stricte | **Canonique** — formule LdP §4.4 `u_i = mean(1/c_t)` bar-indexée |
| API | `(entry_times: list[datetime], exit_times: list[datetime]) -> np.ndarray` | `(t0: pl.Series, t1: pl.Series, bars: pl.Series, log_returns: pl.Series) -> pl.Series` |
| Return attribution | `raise NotImplementedError` ([features/weights.py:140](../../features/weights.py)) | **Implémenté** per ADR-0005 D2 |
| Consommateurs actuels | `features/pipeline.py:31`, `tests/unit/features/test_weights.py` (21 tests), `test_pipeline{,_with_store}.py` | Sub-phases 4.3 (training), 4.4 (tuning), 4.5 (validation) |
| Phase 4.2 touche ? | **Non** — zéro modification, tests existants doivent rester verts | **Crée** intégralement |

La coexistence est **documentée dans le docstring** du nouveau module et
dans le rapport `weights_distribution.md`. Une dette technique est ouverte
implicitement : à la fin de Phase 4 (ou début Phase 5), `features/weights.py`
deviendra redondant et pourra être supprimé après migration de
`features/pipeline.py`. **Hors scope Phase 4.2.**

Aucune divergence entre le prompt de mission (issue #126), ADR-0005 D2
(reproduit §2 ci-dessous), et PHASE_4_SPEC §3.2 : la triade converge.
Verdict **CRÉER** unanime.

---

## 1. Inventaire de l'existant

### 1.1 Code pré-existant identifié

Recherche `rg -n "sample_weight|SampleWeight|uniqueness" --type py` :

| Fichier | Rôle | Phase 4.2 touche ? |
|---|---|---|
| [features/weights.py](../../features/weights.py) | `SampleWeighter` — duration-weighted average uniqueness sur `list[datetime]`. 143 LOC. Prototype Phase 3.1. | **Non** — laissé intact. Le nouveau module est un sibling canonique. |
| [features/pipeline.py](../../features/pipeline.py) | Ligne 31 : `from features.weights import SampleWeighter`. Ligne 57 : `weighter: SampleWeighter` dans la signature. | **Non** — pipeline Phase 3 préservé. |
| [tests/unit/features/test_weights.py](../../tests/unit/features/test_weights.py) | 21 tests sur `SampleWeighter.uniqueness_weights()`. | **Non** — doit rester vert. |
| [tests/unit/features/test_pipeline.py](../../tests/unit/features/test_pipeline.py), [test_pipeline_with_store.py](../../tests/unit/features/test_pipeline_with_store.py) | Injection `SampleWeighter()` dans le pipeline Phase 3. | **Non** — intact. |
| [core/math/labeling.py](../../core/math/labeling.py) | `BarrierLabel.entry_time`, `BarrierLabel.exit_time` — source des `t0` / `t1` consommés par 4.2. | **Non** — lecture seule. API stable. |
| [features/labeling/triple_barrier.py](../../features/labeling/triple_barrier.py) | `label_events_binary()` retourne schema `{symbol, t0, t1, entry_price, exit_price, ternary_label, binary_target, barrier_hit, holding_periods}` avec `t0` / `t1` en `pl.Datetime("us", "UTC")`. | **Non** — consommateur aval. |
| [features/cv/cpcv.py](../../features/cv/cpcv.py) | `CombinatoriallyPurgedKFold.split(X, t1)` — accepte déjà `t1` pour le purging. Pas de `sample_weight` en paramètre (ADR-0005 D2 : « weights live inside `.fit()`, pas dans CPCV »). | **Non** — contrat D2 respecté. |

### 1.2 Schéma d'entrée canonique (source de vérité)

Le livrable 4.1 (`features/labeling/triple_barrier.py::label_events_binary`)
produit un `pl.DataFrame` dont Phase 4.2 consomme les colonnes `t0`, `t1` :

```python
schema = {
    "symbol": pl.Utf8,
    "t0": pl.Datetime("us", "UTC"),       # <--- consommé par 4.2
    "t1": pl.Datetime("us", "UTC"),       # <--- consommé par 4.2
    "entry_price": pl.Float64,
    "exit_price": pl.Float64,
    "ternary_label": pl.Int8,
    "binary_target": pl.Int8,
    "barrier_hit": pl.Utf8,
    "holding_periods": pl.Int32,
}
```

Les `bars` et `log_returns` sont alignés sur le même pl.DataFrame de
barres OHLC utilisé par 4.1. 4.2 ne recalcule pas les log-returns : ils
sont fournis en entrée (colonne `log_return` pré-calculée par l'appelant
ou via `polars.col("close").log().diff()`).

### 1.3 Emplacement canonique pour le nouveau code

Per **PHASE_4_SPEC §3.2 (Module structure)** et **Issue #126 Deliverables** :

```
features/labeling/
├── sample_weights.py          (NEW)

tests/unit/features/labeling/
├── test_sample_weights_uniqueness.py    (NEW, ~10 tests)
├── test_sample_weights_attribution.py   (NEW, ~8 tests)
└── test_sample_weights_combined.py      (NEW, ~6 tests)
```

**Aucune modification** de :
- `features/weights.py` (prototype Phase 3.1 intact — coexistence documentée).
- `features/labeling/__init__.py` (sauf ajout des re-exports des 4 nouvelles fonctions, additif).
- `core/math/labeling.py` (lecture seule).
- `features/cv/cpcv.py` (D2 : weights dans `.fit()`, pas dans CPCV).
- `services/*` (spec §2.4 frozen — inchangé).

---

## 2. Conformité vs D2 de ADR-0005

D2 (reproduit intégralement pour référence) :

> **D2 — Sample weights: uniqueness × return attribution**
>
> Every sample carries two weights (López de Prado §4.4–4.5) computed
> in sub-phase 4.2:
>
> - **Uniqueness weight** `u_i`: inverse of the average concurrency
>   count of label-span `[t0_i, t1_i]` with other label spans.
>   Formally, `u_i = mean(1 / c_t for t in [t0_i, t1_i])` where `c_t`
>   is the number of labels whose span covers bar `t`. This prevents
>   oversampling periods with many overlapping labels.
> - **Return attribution weight** `r_i`:
>   `r_i = |sum(ret_t / c_t for t in [t0_i, t1_i])|` where `ret_t` is
>   the log return of bar `t`. Weights samples by the P&L magnitude
>   attributable to the label span, not just the hit/miss outcome.
>
> **Final training weight**: `w_i = u_i × r_i`, then normalized so that
> `sum(w_i) = n_samples`. Weights are passed through
> `sklearn.fit(X, y, sample_weight=w)`. CPCV fold construction itself
> is NOT weighted; weights live inside `.fit()`.

### 2.1 Scorecard de conformité (cible — pas encore écrit)

| Paramètre D2 | Plan Phase 4.2 | Conforme ? |
|---|---|---|
| Formule `u_i = mean(1 / c_t for t in [t0_i, t1_i])` | Implémentée dans `uniqueness_weights()` en Polars vectorisé | ✅ cible |
| Formule `r_i = |sum(ret_t / c_t for t in [t0_i, t1_i])|` | Implémentée dans `return_attribution_weights()` (valeur absolue obligatoire) | ✅ cible |
| `w_i = u_i × r_i`, normalisé `sum(w_i) = n_samples` | Implémentée dans `combined_weights()` avec renormalisation explicite | ✅ cible |
| Consommé via `sklearn.fit(X, y, sample_weight=w)` | Contrat aval 4.3 ; 4.2 livre `pl.Series[Float64]` convertible `.to_numpy()` | ✅ cible |
| CPCV fold construction **pas** weighted | 4.2 ne modifie pas `features/cv/cpcv.py` | ✅ cible |
| Anti-leakage : weights ne dépendent que de `[t0_i, t1_i]`, bars, log_returns intra-span | Property test dédié (shuffle post-t1 returns → weights inchangés) | ✅ cible |
| Fail-loud : `c_t == 0` → `ValueError` | Guard explicite, message avec timestamp | ✅ cible |

**Aucune dérogation prévue.** Conformité cible : 100%.

### 2.2 Contraintes additionnelles issues d'Issue #126 et PHASE_4_SPEC §3.2

- **Coverage ≥ 92%** sur `features/labeling/sample_weights.py` (issue #126
  DoD §1 — plus strict que les 85% globaux de la CI).
- **mypy --strict clean** (issue #126 DoD §2 — annotations complètes,
  `pl.Series[datetime]`, `pl.Series[float]` via `pl.Series` + runtime
  dtype check).
- **ruff clean** (DoD §3).
- **Perf : 10,000 samples × 100,000 bars ≤ 30 s sur 1 CPU** (DoD §5).
  Cela **interdit** les doubles boucles Python ; plan vectorisé Polars/
  NumPy obligatoire. Le `SampleWeighter` existant (O(n² × endpoints) via
  triple boucle Python) **ne tient pas** ce budget au-delà de quelques
  milliers d'events — raison supplémentaire pour un module neuf plutôt
  qu'une extension.
- **Test de référence contre López de Prado §4.4 Table 4.1** (DoD §6).
  La Table 4.1 LdP est un scénario à 5 observations, je l'encode
  littéralement dans `test_uniqueness_matches_reference_table_LdP_4_4`
  avec les valeurs numériques attendues (computées à la main + commentées).

---

## 3. Verdict

### 3.1 Verdict retenu : **CRÉER** (module neuf sibling, conservation de l'existant)

**Justification (≥ 5 lignes exigées) :**

1. La triade contractuelle (ADR-0005 D2, PHASE_4_SPEC §2.3 ligne
   `features/labeling/sample_weights.py | 4.2 | Uniqueness + return-attribution
   weights do not exist anywhere in the repo`, Issue #126 Deliverables)
   converge explicitement vers **CRÉER** dans `features/labeling/`.
2. Le prototype existant `features/weights.py::SampleWeighter` a trois
   incompatibilités techniques avec D2 : (a) API `list[datetime]` vs Polars
   série bar-indexée requise par la pipeline Phase 4 ; (b) formule
   duration-weighted vs formule bar-indexée `mean(1/c_t)` de LdP §4.4 ;
   (c) `return_attribution_weights` est `NotImplementedError`.
3. Un refactor destructeur de `features/weights.py` casserait
   `features/pipeline.py` (Phase 3) et 21 tests stables. Inacceptable
   (CLAUDE.md §6 : « never suggest merging if CI is red »). Un refactor
   additif rallongerait l'API existante avec une seconde signature — plus
   confus que la coexistence explicite.
4. La coexistence de deux modules est temporaire : le prototype Phase 3.1
   deviendra redondant une fois les Phase 4.3/4.4 wired sur le module
   canonique. Nettoyage prévu en Phase 4.9 closure report comme dette
   technique identifiée.
5. La perf 10 000 × 100 000 ≤ 30 s (Issue #126 DoD §5) impose un
   algorithme fondamentalement différent du prototype (vectorisation
   Polars, bitmap concurrency via `group_by_dynamic` ou numpy broadcast).
   Réutiliser l'ossature du prototype handicaperait le budget perf.

### 3.2 Verdict implicite du prompt de mission : identique

Issue #126 et PHASE_4_SPEC §3.2 spécifient toutes deux
`features/labeling/sample_weights.py` comme module **NEW**. Pas de
contradiction avec ma recommandation. **Aucune demande de confirmation
requise** — j'enchaîne sur le plan §4.

### 3.3 Décisions micro-design à consigner

| Point | Décision | Justification |
|---|---|---|
| Inclusion du bar `t0` dans le span | `[t0, t1]` inclusif des deux bornes | Cohérent avec `label_event` qui considère `entry_time` comme le premier bar de l'event window, et avec LdP §4.4 qui indexe sur `T_i = {t : t0_i ≤ t ≤ t1_i}` |
| Inclusion du bar `t1` dans le span | `[t0, t1]` inclusif des deux bornes | Idem LdP §4.4 |
| Convention égalité `c_t == 0` hors span | `c_t` n'est calculé que sur les bars couverts par ≥ 1 sample ; un bar sans couverture n'apparaît jamais dans `T_i` donc `c_t == 0` n'arrive que si un sample référence un bar hors de la plage des autres samples → `ValueError` fail-loud |
| Ordre de normalisation | Après calcul de `u × r` : `w *= n_samples / sum(w)`, tolérance `1e-9` | Spec §3.2 Algorithm notes |
| Type d'output | `pl.Series[Float64]` (pas `np.ndarray`) | Cohérent avec la pipeline Polars Phase 4.1 ; conversion `.to_numpy()` triviale pour sklearn |
| `log_returns` calculés ou fournis ? | **Fournis** en paramètre ; API accepte `pl.Series[Float64]` pré-calculée | Séparation de responsabilité ; 4.1 ne calcule pas les log-returns non plus ; permet au caller de choisir entre log-diff de close vs fracdiff vs autre |
| Intra-bar alignment `bars` vs `t0`/`t1` | Tous les `t0`/`t1` doivent exister dans `bars.timestamp` ; sinon `ValueError` avec timestamp orphelin | Fail-loud (pattern Phase 4.1) |
| Dtype `t0` / `t1` | `pl.Datetime("us", "UTC")` strict — naïf raise | Cohérent avec 4.1 output |
| Support multi-symbole | MVP Phase 4.2 : mono-symbole ; multi-symbole = regrouper par `symbol` côté caller | PHASE_4_SPEC §3.2 silence sur le multi-symbole ; 4.1 normalise aussi mono-symbole |

---

## 4. Plan d'implémentation

### 4.1 Fichiers à créer / modifier

| Fichier | Action | LOC est. | # tests |
|---|---|---|---|
| `features/labeling/sample_weights.py` | **Create** : `compute_concurrency`, `uniqueness_weights`, `return_attribution_weights`, `combined_weights` + internes vectorisés. | ~270 | - |
| `features/labeling/__init__.py` | **Extend** (additif) : re-exporte les 4 fonctions publiques. | +8 | - |
| `tests/unit/features/labeling/test_sample_weights_uniqueness.py` | **Create**. | ~260 | 10 |
| `tests/unit/features/labeling/test_sample_weights_attribution.py` | **Create**. | ~200 | 8 |
| `tests/unit/features/labeling/test_sample_weights_combined.py` | **Create**. | ~170 | 6 |
| `reports/phase_4_2/audit.md` | **Create** (ce document). | ~400 | - |
| `reports/phase_4_2/weights_distribution.md` | **Create** (généré post-tests via fixture). | ~100 | - |
| `docs/claude_memory/SESSIONS.md` | **Append** : entrée Session 031. | +40 | - |
| `docs/claude_memory/CONTEXT.md` | **Update** : statut Phase 4.2. | diff | - |
| `docs/claude_memory/DECISIONS.md` | **Append** : décision coexistence `features/weights.py` vs `features/labeling/sample_weights.py`. | +20 | - |

**Total estimé** : ~700 LOC implementation (module + diagnostics) + ~630 LOC
tests. 24 tests nouveaux (cible ≥ 24 per issue §Tests). Zéro modification
sous `services/`, `core/`, `features/pipeline.py`, `features/weights.py`.
Une seule addition additive dans `features/labeling/__init__.py` (4
re-exports).

### 4.2 Ordre d'implémentation recommandé

1. `features/labeling/sample_weights.py` — skeleton + `compute_concurrency`
   (le primitif) + tests concurrency (3-4 cas).
2. `uniqueness_weights` + tests LdP §4.4 Table 4.1 + edge cases.
3. `return_attribution_weights` + tests anti-leakage (shuffle post-t1 returns).
4. `combined_weights` + test normalisation `sum == n_samples`.
5. Fail-loud path : UTC check, alignment check, `c_t == 0` raise, misaligned
   bars raise, naive datetime raise.
6. Re-exports dans `features/labeling/__init__.py`.
7. Génération `reports/phase_4_2/weights_distribution.md` via fixture
   synthétique (seed 42, 100 events × 1000 bars, distribution overlap moyenne).
8. `make lint` (ruff + mypy strict + bandit) puis `pytest tests/unit/features/labeling/`.
9. Budget perf : test dédié avec `n_samples=10_000`, `n_bars=100_000`, assert
   `duration < 30.0` (seuil issue #126 DoD §5) — `@pytest.mark.slow` pour ne
   pas bloquer le CI default.

### 4.3 Edge cases critiques

Les trois edge cases à prioriser dans les tests :

1. **Anti-leakage (ADR-0005 D2 + Issue §Anti-leakage)** — shuffler les log
   returns après `t1_max` ne doit **pas** altérer les weights. Property
   test Hypothesis avec 100 exemples suffisent (perf budget).
2. **Normalisation `sum(w) == n_samples`** — tolérance `1e-9`. Cas
   dégénéré : tous les events disjoints → chaque `u_i = 1`, `r_i = |ret_total_i|` ;
   après normalisation `w_i = n * |r_i| / sum(|r_j|)`. Formule vérifiable
   à la main.
3. **`c_t == 0` fail-loud** — un sample avec `t0` ou `t1` hors de la plage
   couverte par les autres samples (et donc hors de `bars`) doit raise avec
   timestamp explicite, pas silencieusement skip.

Edge cases secondaires :

4. Empty events / bars → retourne `pl.Series` vide, pas d'erreur.
5. Single event disjoint → `u_1 = 1`, `r_1 = |sum ret_t|`, après normalisation
   `w_1 = 1.0` exactement.
6. Tous events parfaitement identiques (mêmes `t0`/`t1`) → `c_t` constant,
   `u_i = 1/n` pour tous, weights tous égaux après normalisation.
7. Naive datetime dans `t0`/`t1`/`bars` → `ValueError` immédiat.
8. `log_returns` non alignés sur `bars` (tailles différentes) → `ValueError`.
9. `log_returns` contient NaN / Inf → `ValueError` fail-loud (pas de ffill
   silencieux — pattern Phase 4.1).
10. Concurrency géante (1 bar couvert par 1000 samples) → weight très
    faible mais strictement > 0, pas de division par zéro.
11. Zero-length span `t0 == t1` : par convention inclusive `[t0, t0]` =
    1 bar → `u_i = 1/c_{t0}`. Cas documenté.
12. Events ordonnés vs non-ordonnés : l'API ne requiert pas d'ordre
    particulier sur les events ; tests parametrisés avec random shuffle.
13. `ret_t = 0` exactement sur toute la span → `r_i = 0` → contribution
    nulle au combined weight → après normalisation sum(w) peut devenir 0 si
    **tous** les events ont ret nul → cas limite documenté, potentiel
    `ValueError` ou retour all-zero series (décision : retourner all-zero
    et laisser le caller décider — plus utile pour debugging qu'un raise).

### 4.4 Risques résiduels et mitigations

| Risque | Probabilité | Impact | Mitigation |
|---|---|---|---|
| Budget perf 10k × 100k ≤ 30s non tenu | Moyenne | Bloquant (DoD §5) | Algorithme cible : concurrency via `pl.int_range` + `group_by_dynamic`, ou numpy bitmap `(n_samples, n_bars)` si memory OK (1e9 bytes = 8 GB pour bool → pas OK, partitionner en chunks de 10k bars). Fallback : algorithme O(n_samples * avg_span) en numpy vectorisé. |
| Mémoire peak > 4 GB lors du test perf | Faible | Faible | Chunker par 10k bars si bitmap ; alternative O(n log n) via tri + balayage d'événements (scanline) |
| Drift numérique entre float32/float64 sur `sum(1/c_t)` | Faible | Faible | Forcer `pl.Float64` partout ; `@pytest.mark.parametrize` tolérance adaptée |
| Test LdP §4.4 Table 4.1 — divergence de ±1 sur les counts selon la convention inclusive/exclusive | Moyenne | Moyen | Documenter la convention `[t0, t1]` inclusive dans le docstring + commenter chaque ligne du test avec son counting manuel |
| `features/weights.py::SampleWeighter.uniqueness_weights` diverge du nouveau module sur le même scénario | Haute (par design) | Nul | Documenté : les deux formules sont différentes (duration-weighted vs bar-indexed). Aucun test de parité. |
| Ajout additif dans `features/labeling/__init__.py` casse l'import order | Faible | Faible | Tests existants Phase 4.1 doivent rester verts après ajout des re-exports |
| Hypothesis property test trop lent (>5s) | Faible | Faible | Budget `@settings(max_examples=50, deadline=None)` |

---

## 5. Décision

**Aucune confirmation architecte requise** (triade ADR/Spec/Issue
convergente). Le plan §4 est exécuté immédiatement dans un commit
`phase(4.2): sample weights module per ADR-0005 D2` sur cette même
branche `phase/4.2-sample-weights`, suivi des commits tests + diagnostics
+ mise à jour mémoire puis push + PR.

Dette technique ouverte à porter dans `docs/claude_memory/DECISIONS.md` :
*« `features/weights.py::SampleWeighter` (prototype Phase 3.1) coexiste
avec `features/labeling/sample_weights.py` (canonique Phase 4.2). La
migration de `features/pipeline.py` vers le module canonique est reportée
à la closure Phase 4 (issue #133) ou à Phase 5 ; cette coexistence est
temporaire et explicitement documentée pour éviter la confusion DRY. »*
