## [EPIC RESEARCH] R&D — Évaluation du "Dynamic Model Averaging" (DMA) vs Meta-Labeling

**Priorité** : BASSE (Recherche pure, ne doit pas bloquer la mise en production du système actuel)
**Composants** : Environnement de Backtest (`features/pipeline.py`, Notebooks de recherche)

---

### 1. Contexte Industriel & Références

La littérature quant (ex: *Dynamic Model Averaging in Economics and Finance*) suggère qu'une allocation dynamique du capital entre plusieurs modèles dé-corrélés (Linéaire OLS vs Non-Linéaire Random Forest) selon le régime de marché (Regime-Switching) maximise l'extraction d'Alpha. L'architecture actuelle d'APEX utilise le Meta-Labeling (Lopez de Prado), qui est défensif (filtre de risque). L'objectif de cette recherche est d'évaluer si une architecture offensive (DMA) justifie son coût en complexité (Whipsaw risk, Overfitting).

### 2. Opportunité & Problème

APEX sous-performe potentiellement (en termes de Gross PnL) lors des changements de régime majeurs (chocs exogènes), car le Meta-Labeler se contente de couper les positions (Kelly = 0) au lieu de basculer sur un modèle capable de "shorter" la volatilité de manière non-linéaire.

### 3. Méthodologie de Recherche (En 3 Phases Strictes)

Cette Issue ne requiert **aucune modification du code de production** (services S01 à S10). Tout le travail doit se faire dans l'environnement de recherche (Backtest).

**Phase 1 : Modélisation des Cerveaux Isolés**
- Entraîner le Cerveau A (Pur Linéaire / Base Signal).
- Entraîner le Cerveau B (Pur Deep Learning / XGBoost, cherchant à générer un Alpha directionnel absolu, sans Meta-Labeling).

**Phase 2 : Simulation du Routeur (S03 DMA)**
- Créer un simulateur de portefeuille qui alloue le capital entre A et B en fonction de la probabilité du régime actuel (Hidden Markov Model - HMM).
- Intégrer une pénalité de transaction sévère (Slippage majoré) pour simuler le coût des faux-positifs lors des changements de régime (Whipsaw effect).

**Phase 3 : Confrontation CPCV (Champion vs Challenger)**
- Exécuter une Combinatorial Purged Cross-Validation sur le modèle APEX actuel (Champion : Meta-Labeling) contre le modèle DMA (Challenger : Regime-Switching).

### 4. Critères d'Acceptation pour passage en Ingénierie (Definition of Done)

Pour que la recherche soit validée et donne lieu à des tickets de développement dans le code de production de S04, le modèle DMA doit prouver sa supériorité de manière écrasante :

- [ ] **Amélioration du Sharpe** : Le Sharpe Ratio Out-of-Sample du DMA doit battre celui du Meta-Labeling d'au moins +0.50 net de frais.
- [ ] **Stabilité du PBO** : La Probability of Backtest Overfitting (PBO) du modèle DMA ne doit pas excéder 5%.
- [ ] **Drawdown** : Le Maximum Drawdown du DMA ne doit pas excéder de plus de 20% celui du Meta-Labeling.
- [ ] **Livrable** : Un rapport de recherche académique (Markdown/PDF) concluant sur un Go/No-Go.

### Références

- Raftery, A. E. et al., « Dynamic Model Averaging in Economics and Finance »
- López de Prado, M. (2018), *Advances in Financial Machine Learning*, Wiley
- Hamilton, J. D. (1989), « A New Approach to the Economic Analysis of Nonstationary Time Series » (HMM)
