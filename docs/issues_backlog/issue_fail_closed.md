## [CRITIQUE] Sécurité Financière — Transition du modèle "Fail-Open" vers "Fail-Closed" (Pre-Trade Risk Controls)

**Priorité** : CRITIQUE (Bloquant pour tout déploiement de capital réel)
**Composants** : `s05_risk_manager/service.py`, `core/state.py`

---

### 1. Contexte Industriel & Références

En 2012, la faillite de Knight Capital Group (perte de 440M$ en 45 minutes) a prouvé qu'un système d'exécution ne doit jamais présumer d'un état sain en l'absence de données. La réglementation SEC Rule 15c3-5 (Market Access Rule) exige des contrôles de risque pré-négociation déterministes, inflexibles et instantanés.

### 2. Opportunité & Problème

Actuellement, le Risk Manager (S05) utilise une méthode asynchrone de repli (`_safe()`) qui injecte des valeurs par défaut fictives (ex: Capital = 100 000) si le cache Redis échoue ou subit un timeout. Ce comportement d'échec permissif (Fail-Open) est inacceptable en production : le système pourrait autoriser une position massive alors que le capital réel est épuisé.

### 3. Architecture de la Solution (En 2 Phases)

**Phase 1 : Suppression des heuristiques de repli**
- Éliminer toute logique d'imputation de valeurs par défaut pour les métriques critiques (Capital, Exposition, PnL) dans S05.

**Phase 2 : Implémentation du système "Fail-Closed"**
- Créer un gestionnaire d'état `SystemRiskState`.
- Si la lecture de l'état (Redis/Mémoire) renvoie un statut `DEGRADED` ou `TIMEOUT`, la fonction `process_order_candidate` doit intercepter l'anomalie en O(1) et émettre immédiatement un `RiskDecision` avec le statut `REJECTED_SYSTEM_UNAVAILABLE`.

### 4. Critères d'Acceptation (Definition of Done)

- [ ] **Ingénierie du Chaos** : Une suite de tests prouve qu'une coupure réseau avec Redis entraîne le rejet absolu de 100% des `OrderCandidate` entrants en moins de 1ms.
- [ ] **Auditabilité** : Chaque rejet lié au système génère un log structuré critique remonté au système de monitoring (S10) pour alerter les opérateurs.
- [ ] Aucune valeur par défaut fictive ne subsiste dans S05 pour Capital, Exposition ou PnL.
- [ ] ADR documentant le pattern Fail-Closed et la suppression du Fail-Open.

### Références

- SEC Rule 15c3-5 (Market Access Rule)
- Knight Capital Group post-mortem (2012)
- CLAUDE.md §2 : « Risk Manager (S05) is a VETO — it cannot be bypassed under any circumstance »
