## [PERFORMANCE] Couche de Sérialisation — Migration JSON vers Zero-Copy Binary (SBE)

**Priorité** : MOYENNE (Optimisation CPU et Garbage Collection)
**Composants** : Modèles Pydantic (`core/models/`), `core/bus.py`

---

### 1. Contexte Industriel & Références

Le standard SBE (Simple Binary Encoding) a été conçu par la FIX Trading Community pour éliminer les coûts colossaux d'encodage/décodage des formats textes (XML, JSON). Google FlatBuffers permet d'accéder aux données en mémoire sans aucune étape de désérialisation (Zero-Copy).

### 2. Opportunité & Problème

Le système sérialise actuellement les ticks et les ordres en JSON (`.model_dump_json()`). En environnement Python, la création continue de dizaines de milliers de strings (chaînes de caractères) par seconde sature la mémoire vive et force des pauses agressives du Garbage Collector, détruisant le déterminisme à basse latence.

### 3. Architecture de la Solution (En 2 Phases)

**Phase 1 : Définition des Schémas Binaires**
- Concevoir des schémas FlatBuffers ou SBE exclusifs pour le Hot Path : `Tick`, `Signal`, `OrderCandidate`, `RiskDecision`.
- Compiler les schémas pour générer les wrappers natifs en Python.

**Phase 2 : Implémentation Bus ZMQ**
- Modifier `MessageBus` pour transmettre et recevoir des flux d'octets purs (`bytes`) au lieu de chaînes UTF-8.

### 4. Critères d'Acceptation (Definition of Done)

- [ ] **Profilage CPU** : Un rapport montre une réduction de plus de 80% du temps CPU alloué à la sérialisation des messages `Tick`.
- [ ] **Stabilité GC** : Diminution drastique des pauses du Garbage Collector Python lors des tests de stress (chocs de volatilité simulés).
- [ ] Schémas FlatBuffers/SBE versionnés et documentés.
- [ ] Backward-compatible : les services non-migrés peuvent toujours consommer du JSON via un adapteur.

### Références

- FIX Trading Community — Simple Binary Encoding (SBE) specification
- Google FlatBuffers (https://google.github.io/flatbuffers/)
- CLAUDE.md §5 : « Hot paths must avoid object allocation in inner loops »
