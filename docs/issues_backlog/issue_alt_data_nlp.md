## [EPIC] Alternative Data & NLP — Geopolitical Risk Overlay (S01 -> S08)

**Priorité** : MOYENNE (Générateur d'Alpha conditionnel / Filtre de Beta)
**Composants** : `s01_data_ingestion`, `s08_macro_intelligence`, `s04_fusion_engine`, `s05_risk_manager`, FeatureStore
**Rewrite note (2026-04-17)** : Per [STRATEGIC_AUDIT_2026-04-17](../audits/STRATEGIC_AUDIT_2026-04-17_PHASE_5_AND_GLOBAL.md) §4.3, the proprietary `WorldMonitorConnector` (paid gRPC feed) is **replaced** with open-source substitutes: GDELT 2.0 (free HTTP feed, 15-min cadence, 300-language event-coded corpus) + FinBERT compiled to ONNX Runtime. This honors Principle 3 (acknowledged constraints, intelligent alternatives) without sacrificing institutional-grade methodology (Principle 2).

---

### 1. Contexte Industriel & Références

Dans la recherche quantitative (*Text as Data*, Kelly et al.), l'analyse du sentiment en temps réel supplante les flux d'actualités traditionnels. Les fonds de classe Tier-1 déploient des modèles de Traitement du Langage Naturel (NLP) sur des flux Alt-Data pour bloquer l'exposition directionnelle avant que le "cygne noir" ne se manifeste dans la microstructure du prix. Pour un opérateur solo sans budget Bloomberg/Refinitiv/WorldMonitor, la **GDELT Project 2.0** (Global Database of Events, Language and Tone) offre le même type de signal au coût de 0 USD/mois.

### 2. Opportunité & Problème

APEX est actuellement aveugle aux événements macros/géopolitiques asynchrones (guerres, alertes satellites) tant que la volatilité (VIX) ou le flux (OFI) n'a pas bougé. GDELT 2.0 expose un flux public d'événements mondiaux codés (CAMEO events, tone scores, actor identification) mis à jour toutes les 15 minutes, ce qui permet d'implémenter un Risk Overlay préventif sans dépendance à un fournisseur propriétaire.

### 3. Architecture de la Solution (En 4 Phases)

**Phase 1 : Ingestion Déterministe (S01)**
- Implémenter un `GDELTConnector` pour consommer le flux HTTP/CSV de GDELT 2.0 (événements globaux GKG + EVENT).
- Publier la donnée brute normalisée sur le topic `macro.geopolitics.raw`.

**Phase 2 : Quantification NLP & MLOps (S08)**
- Intégrer **FinBERT** (ProsusAI/finBERT, open-source) — compilé en ONNX Runtime pour inférence CPU déterministe, sans dépendance GPU.
- Isoler l'inférence en sous-processus (pas d'accès aux clés API broker).
- Transformer le texte/GKG en vecteur continu `GeopoliticalRiskScore [-1.0, 1.0]`. Sauvegarder dans TimescaleDB (Point-in-Time).
- Latence cible : p99 < 50 ms par chunk.

**Phase 3 : Modulation & Fail-Closed (S04 & S05)**
- S04 (Fusion Engine) pénalise la fraction de Kelly si le score de risque approche les extrêmes négatifs (asymétrie : `geo_score > 0` n'augmente PAS Kelly).
- S05 déploie une `GeopoliticalEventGuard`. À un score critique de -1.0, le circuit breaker s'active (VETO total). Si le modèle NLP crashe (absence de heartbeat > 60s), S05 passe en Fail-Closed (réutilise le pattern ADR-0006).

**Phase 4 : Validation Mathématique (CPCV)**
- Prouver statistiquement l'apport du filtre via une Combinatorial Purged Cross-Validation sur l'historique GDELT (remontant à 2015).

### 4. Critères d'Acceptation (Definition of Done)

- [ ] **Test d'Intégration Latence** : Un événement géopolitique majeur injecté dans S01 doit traverser le pipeline NLP et déclencher l'état BLOCKED de S05 en moins de 250ms.
- [ ] **Gouvernance IA** : Documentation complète (`model_card_nlp_risk.json`) stipulant le biais, le temps d'inférence (p99), et la taille du modèle (pas de VRAM — FinBERT ONNX CPU).
- [ ] **Alpha/Beta Profiling** : Le rapport de backtest prouve une réduction du Maximum Drawdown (MDD) d'au moins 15% sur des périodes de crises ex-post (crise COVID-03/2020, invasion Ukraine-02/2022, etc.).
- [ ] Topic ZMQ `macro.geopolitics.*` enregistré dans `core/topics.py`.
- [ ] **Coût opérationnel** : 0 USD/mois (GDELT gratuit, FinBERT open-source, pas de GPU).

### Références

- Kelly, B. et al., « Text as Data » (Journal of Financial Economics)
- GDELT Project 2.0 (https://www.gdeltproject.org/)
- FinBERT (https://github.com/ProsusAI/finBERT)
- CAMEO Event Codes (conflict and mediation event observations)
- CLAUDE.md §3 : « S08 MacroIntelligence fires macro.catalyst.* events as they happen »
- STRATEGIC_AUDIT_2026-04-17_PHASE_5_AND_GLOBAL.md §4.3 (Principle 3 justification)
