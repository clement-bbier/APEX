## [HAUTE] Mechanical Sympathy — Architecture "Event Sourcing / In-Memory" pour le Hot Path

**Priorité** : HAUTE (Prérequis pour stabiliser la gigue de latence sous les 5ms)
**Composants** : `s05_risk_manager/service.py`, `core/state.py`

---

### 1. Contexte Industriel & Références

La notion de Mechanical Sympathy (Martin Thompson, Disruptor) stipule que les requêtes I/O (réseau/disque) sont strictement prohibées dans un chemin critique d'exécution. L'architecture LMAX démontre que la latence la plus basse est obtenue via des machines à état en mémoire (RAM) traitant les événements de manière séquentielle.

### 2. Opportunité & Problème

Pour chaque ordre reçu, le S05 utilise `asyncio.gather` pour effectuer 8 requêtes réseau vers Redis. Cela introduit un jitter (gigue de latence) inacceptable induit par le réseau et force des allocations mémoire qui déclenchent le Garbage Collector (GC) de Python.

### 3. Architecture de la Solution (En 2 Phases)

**Phase 1 : Transition vers l'Event Sourcing**
- S05 doit s'abonner passivement aux topics ZMQ diffusant les exécutions (fills) et le Mark-to-Market (M2M).
- À chaque événement, S05 met à jour un dictionnaire d'état local (Python natif) de manière asynchrone.

**Phase 2 : Évaluation CPU-Bound**
- La validation d'un ordre ne nécessite plus d'I/O. Elle lit directement les variables en mémoire (optimisation L1/L2 cache).

### 4. Critères d'Acceptation (Definition of Done)

- [ ] **Benchmark P99** : Le test de charge démontre une latence de validation du risque P99 < 100 microsecondes (contre ~5ms auparavant).
- [ ] **Zéro I/O** : L'analyseur de profilage (profiler) confirme qu'aucun appel réseau ou socket n'est initié par S05 lors de l'évaluation d'un ordre.
- [ ] État local synchronisé via ZMQ PUB/SUB (pas de lecture Redis dans le hot path).
- [ ] Tests de cohérence prouvant que l'état en mémoire converge vers l'état Redis après rattrapage.

### Références

- Martin Thompson, « Mechanical Sympathy » (blog series)
- LMAX Exchange Architecture (Disruptor pattern)
- CLAUDE.md §5 : « Hot paths must avoid object allocation in inner loops »
