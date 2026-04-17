> **⚠️ DEFERRED — 2026-04-17**
>
> Moved **out of Phase 5** and into the new **Phase 7.5 Infrastructure Hardening backlog**
> per [STRATEGIC_AUDIT_2026-04-17](../audits/STRATEGIC_AUDIT_2026-04-17_PHASE_5_AND_GLOBAL.md) §4.2.
>
> **Rationale (Principle 1, 3, 7).** A Rust FFI hot-path migration (sub-phase 5.9) was premature for a solo operator running ten
> containers on a single host with no live trading yet. It solves a latency / SPOF / HFT-scale
> problem the operator does not have today. Revisit **only if** live-trading benchmarks from
> Phase 8 prove this is a production bottleneck.

---

## [EPIC] Architecture Polyglotte — Migration du "Hot Path" vers Rust via FFI

**Priorité** : STRATÉGIQUE (Fondation obligatoire pour le HFT et traitement des carnets L2)
**Composants** : Coeur d'exécution (`s01`, `s04`, `s05`, `s06`), crates `apex_mc`, `apex_risk`

---

### 1. Contexte Industriel & Références

Comme expliqué par Marcos Lopez de Prado (*Advances in Financial Machine Learning*), les architectures quantitatives d'élite séparent la recherche de la production. Python est réservé à l'Alpha, au Machine Learning et au CPCV. C++ / Rust sont réservés au flux d'exécution en temps réel (déterminisme à la nanoseconde, gestion manuelle de la mémoire).

### 2. Opportunité & Problème

Malgré une excellente architecture asynchrone, APEX est bridé par le Global Interpreter Lock (GIL) de Python, empêchant un vrai parallélisme CPU. Lors de rafales massives de Ticks de microstructure (carnets d'ordres L2), Python ne pourra pas suivre le débit.

### 3. Architecture de la Solution (En 3 Phases)

**Phase 1 : Ingestion & Risque en Rust Natif**
- Réécrire intégralement S01 (Market Data) et S05 (Risk) en Rust (en s'appuyant sur les modules existants `apex_mc` et `apex_risk`).

**Phase 2 : FFI (Foreign Function Interface)**
- Conserver S02 (Signal) et S08 (Macro) en Python pour la flexibilité (PyTorch, SciKit).
- Créer un pont FFI Zero-Copy via mémoire partagée (Shared Memory / Ring Buffer) pour transmettre les Ticks du moteur Rust vers le moteur Python.

**Phase 3 : Consolidation (Monolithe Modulaire)**
- Fusionner le Hot Path dans un seul binaire exécutable natif (Rust) instanciant plusieurs threads, éliminant totalement la latence IPC (Inter-Process Communication).

### 4. Critères d'Acceptation (Definition of Done)

- [ ] **ADR Validé** : Publication d'un Architecture Decision Record détaillant le pont FFI (PyO3 vs SHM).
- [ ] **Débit Nanoseconde** : Le moteur Rust consolidé doit prouver sa capacité à ingérer et valider au risque plus d'un million de Ticks/seconde par coeur logique.
- [ ] Benchmark comparatif Python vs Rust sur le hot path (latence P50/P99/P999).
- [ ] Tests d'intégration prouvant la transparence du pont FFI pour S02/S08.

### Références

- López de Prado, M. (2018), *Advances in Financial Machine Learning*, Wiley
- PyO3 (https://pyo3.rs/) — Rust bindings for Python
- CLAUDE.md §5 : « CPU-bound math goes in Rust (apex_mc, apex_risk crates) — not in Python »
