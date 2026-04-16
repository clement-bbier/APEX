## [EPIC] Alternative Data & NLP — Couverture du Risque Géopolitique (S01 -> S08)

**Priorité** : MOYENNE (Générateur d'Alpha conditionnel / Filtre de Beta)
**Composants** : `s01_data_ingestion`, `s08_macro_intelligence`, `s04_fusion_engine`, `s05_risk_manager`, FeatureStore

---

### 1. Contexte Industriel & Références

Dans la recherche quantitative (*Text as Data*, Kelly et al.), l'analyse du sentiment en temps réel supplante les flux d'actualités traditionnels. Les fonds de classe Tier-1 déploient des modèles de Traitement du Langage Naturel (NLP) sur des flux Alt-Data pour bloquer l'exposition directionnelle avant que le "cygne noir" ne se manifeste dans la microstructure du prix.

### 2. Opportunité & Problème

APEX est actuellement aveugle aux événements macros/géopolitiques asynchrones (guerres, alertes satellites) tant que la volatilité (VIX) ou le flux (OFI) n'a pas bougé. L'API worldmonitor.app expose plus de 400 flux d'informations structurés (Protobuf) qui permettraient d'implémenter un Risk Overlay préventif.

### 3. Architecture de la Solution (En 4 Phases)

**Phase 1 : Ingestion Déterministe (S01)**
- Implémenter un `WorldMonitorConnector` pour consommer le flux gRPC/Protobuf.
- Publier la donnée brute normalisée sur le topic `macro.geopolitics.raw`.

**Phase 2 : Quantification NLP & MLOps (S08)**
- Intégrer un modèle spécialisé (FinBERT ou LLM quantifié local) isolé de S02.
- Compiler le modèle via ONNX Runtime / TensorRT pour garantir une inférence rapide sans Garbage Collection.
- Transformer le texte en vecteur continu `GeopoliticalRiskScore [-1.0, 1.0]`. Sauvegarder dans TimescaleDB (Point-in-Time).

**Phase 3 : Modulation & Fail-Closed (S04 & S05)**
- S04 (Fusion Engine) pénalise la fraction de Kelly si le score de risque approche les extrêmes négatifs.
- S05 déploie une `GeopoliticalEventGuard`. À un score critique de -1.0, le circuit breaker s'active (VETO total). Si le modèle NLP crashe (absence de heartbeat > 60s), S05 passe en Fail-Closed.

**Phase 4 : Validation Mathématique (CPCV)**
- Prouver statistiquement l'apport du filtre via une Combinatorial Purged Cross-Validation sur l'historique macro.

### 4. Critères d'Acceptation (Definition of Done)

- [ ] **Test d'Intégration Latence** : Un événement géopolitique majeur injecté dans S01 doit traverser le pipeline NLP et déclencher l'état BLOCKED de S05 en moins de 250ms.
- [ ] **Gouvernance IA** : Documentation complète (`model_card_nlp_risk.json`) stipulant le biais, le temps d'inférence (p99) et la consommation VRAM du modèle.
- [ ] **Alpha/Beta Profiling** : Le rapport de backtest prouve une réduction du Maximum Drawdown (MDD) d'au moins 15% sur des périodes de crises ex-post.
- [ ] Topic ZMQ `macro.geopolitics.*` enregistré dans `core/topics.py`.

### Références

- Kelly, B. et al., « Text as Data » (Journal of Financial Economics)
- FinBERT (https://github.com/ProsusAI/finBERT)
- CLAUDE.md §3 : « S08 MacroIntelligence fires macro.catalyst.* events as they happen »
