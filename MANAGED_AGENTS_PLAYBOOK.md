# APEX × Claude Managed Agents — Playbook

Comment utiliser Claude Managed Agents (`platform.claude.com`) en complément du workflow Claude Code principal pour automatiser, paralléliser, et industrialiser le développement et l'opération d'APEX.

**Date de rédaction** : Avril 2026  
**Statut Managed Agents** : Beta publique  
**Maintainer** : Clement Barbier (orchestrator)

---

## Table des matières

- [Partie A — Setup et intégration dans le repo](#partie-a--setup-et-intégration-dans-le-repo)
  - [A.1 Quand utiliser Managed Agents vs Claude Code](#a1-quand-utiliser-managed-agents-vs-claude-code)
  - [A.2 Architecture cible](#a2-architecture-cible)
  - [A.3 Setup compte et CLI](#a3-setup-compte-et-cli)
  - [A.4 Convention de nommage et organisation](#a4-convention-de-nommage-et-organisation)
  - [A.5 Gestion des secrets](#a5-gestion-des-secrets)
  - [A.6 Permissions et sandboxing](#a6-permissions-et-sandboxing)
  - [A.7 Intégration MCP avec APEX](#a7-intégration-mcp-avec-apex)
  - [A.8 Coûts et budget](#a8-coûts-et-budget)
- [Partie B — Cas d'usage par phase du projet](#partie-b--cas-dusage-par-phase-du-projet)
  - [B.1 Phase 2 (Data Infrastructure) — quoi paralléliser, quoi NE PAS paralléliser](#b1-phase-2-data-infrastructure)
  - [B.2 Agents périphériques utilisables MAINTENANT](#b2-agents-périphériques-utilisables-maintenant)
  - [B.3 Phase 3 (Feature validation harness)](#b3-phase-3-feature-validation-harness)
  - [B.4 Phase 4-5 (Signal Engine + Backtesting)](#b4-phase-4-5-signal-engine--backtesting)
  - [B.5 Phase 6-7 (Risk Manager + Order Manager)](#b5-phase-6-7-risk-manager--order-manager)
  - [B.6 Phase 8+ (Live Trading) — agents critiques 24/7](#b6-phase-8-live-trading--agents-critiques-247)
  - [B.7 Veille permanente et research support](#b7-veille-permanente-et-research-support)
- [Partie C — Templates d'agents prêts à déployer](#partie-c--templates-dagents-prêts-à-déployer)

---

# Partie A — Setup et intégration dans le repo

## A.1 Quand utiliser Managed Agents vs Claude Code

**Règle absolue** : Claude Code reste le moteur de développement principal d'APEX. Managed Agents est un **complément**, pas un remplacement.

| Situation | Outil |
|---|---|
| Développer une nouvelle phase qui touche le repo principal | **Claude Code** |
| Faire un refactor qui modifie plusieurs fichiers existants | **Claude Code** |
| Hotfix après review Copilot | **Claude Code** |
| Tâches indépendantes du code source | **Managed Agents** |
| Tâches récurrentes (veille, monitoring, reporting) | **Managed Agents** |
| Tâches longues qui doivent survivre à la fermeture du laptop | **Managed Agents** |
| Workflows multi-étapes en background | **Managed Agents** |
| Production live (alerting, watchdog) | **Managed Agents** |

**Pourquoi cette séparation** : Claude Code a accès direct au filesystem et au git du repo APEX, ce que Managed Agents n'a pas. Inversement, Managed Agents tourne en cloud avec sessions persistantes, ce que Claude Code ne fait pas.

## A.2 Architecture cible
┌─────────────────────────────────────────────────────────────┐
│                      APEX                       │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  Repo principal (10 services S01-S10)               │    │
│  │  Développement séquentiel via Claude Code           │    │
│  └─────────────────────────────────────────────────────┘    │
│                            ▲                                │
│                            │ git, fichiers, commits         │
│                            │                                │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  Couche Managed Agents (cloud, parallèles)          │    │
│  │  ┌────────────┐ ┌────────────┐ ┌────────────┐       │    │
│  │  │  Veille    │ │  Backfill  │ │  Watchdog  │  ...  │    │
│  │  │  quant     │ │  data      │ │  prod      │       │    │
│  │  └────────────┘ └────────────┘ └────────────┘       │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
└─────────────────────────────────────────────────────────────┘

## A.3 Setup compte et CLI

Le compte est créé automatiquement avec ton compte Anthropic existant. Accès direct via `platform.claude.com/workspaces/default/agent-quickstart`.

### Installation CLI (recommandé pour scripting)

```powershell
# Sur Windows via Scoop ou direct
# (vérifier la doc officielle si Homebrew n'est pas dispo)
npm install -g @anthropic-ai/cli

# Ou en Python
pip install anthropic

# Variable d'environnement (à mettre dans .env ou profile PowerShell)
$env:ANTHROPIC_API_KEY = "ta_cle_api_anthropic_console"
```

**Note** : ta clé API Anthropic console est différente de tes clés Alpaca/Massive/FRED. Elle se génère sur `console.anthropic.com` → Settings → API Keys.

### Vérification

```powershell
python -c "import anthropic; c = anthropic.Anthropic(); print('OK', c)"
```

## A.4 Convention de nommage et organisation

Tous les agents APEX doivent suivre cette convention pour rester organisés :

- **Nom** : `apex-<role>-<scope>` (ex: `apex-veille-quant`, `apex-backfill-binance`, `apex-watchdog-circuit-breaker`)
- **Tag** : ajouter tag `project=apex` dans la metadata
- **Repo de configs** : créer un dossier `agents/` à la racine du repo qui contient un fichier YAML par agent (ex: `agents/veille_quant.yaml`) avec system prompt + outils + environment config. Versionnés dans git.

### Structure proposée
APEX/
├── agents/
│   ├── README.md                     # Inventaire des agents APEX
│   ├── veille_quant.yaml             # Agent de veille recherche
│   ├── backfill_data.yaml            # Agent de backfill data en background
│   ├── watchdog_prod.yaml            # Agent watchdog (Phase 8+)
│   ├── nightly_backtest.yaml         # Agent nightly backtest (Phase 5+)
│   └── _shared/
│       └── system_prompts/           # Prompts partagés/imports
├── scripts/
│   ├── deploy_agent.py               # Script de déploiement YAML → Managed Agent
│   └── list_agents.py                # Liste tes agents APEX actifs
└── ...

## A.5 Gestion des secrets

**Règle critique** : ne JAMAIS coller tes vraies clés API dans la config d'un Managed Agent ou dans un fichier YAML versionné.

### Méthodes par ordre de sécurité

1. **Vault Anthropic intégré** (recommandé) — Managed Agents fournit un système de vault. Stocke tes clés une fois côté plateforme, référence par nom dans l'agent (ex: `${secrets.alpaca_api_key}`).
2. **Variables d'environnement injectées au démarrage de session** — moins sécurisé mais OK pour clés à scope limité.
3. **MCP server custom qui sert les secrets** — overkill pour solo, utile en équipe.

Aucune clé en clair dans `agents/*.yaml`. Tous les fichiers YAML doivent passer le check `git diff` sans révéler de secret.

## A.6 Permissions et sandboxing

Pour APEX, voici les politiques recommandées par type d'agent :

| Type d'agent | bash | file_write | file_read | web_search | web_fetch | MCP tools |
|---|---|---|---|---|---|---|
| Veille quant (read-only) | ❌ | ❌ | always_allow | always_allow | always_allow | always_ask |
| Backfill data | always_allow | always_allow (data/) | always_allow | always_allow | always_allow | always_ask |
| Nightly backtest | always_allow | always_allow (results/) | always_allow | ❌ | ❌ | always_ask |
| Watchdog prod | ❌ | ❌ | always_allow | ❌ | always_allow | always_ask |
| Reporting | ❌ | always_allow (reports/) | always_allow | always_allow | always_allow | always_ask |

**Règle d'or** : tout agent qui peut écrire dans le repo APEX doit avoir `always_ask` sur file_write, sauf s'il écrit dans un dossier dédié (`data/`, `reports/`, `logs/`).

## A.7 Intégration MCP avec APEX

Tu peux exposer APEX comme serveur MCP pour que tes agents Managed Agents y accèdent. Cas d'usage :

- **MCP server `apex-data`** : expose `query_bars(symbol, start, end)`, `query_quality_log()`, `latest_ingestion_runs()`. Utilisable par les agents reporting et watchdog.
- **MCP server `apex-backtest`** : expose `run_backtest(strategy, start, end)`, `get_results(run_id)`. Utilisable par le nightly backtest agent.
- **MCP server `apex-risk`** : (Phase 6+) expose `current_circuit_breaker_state()`, `live_positions()`. Utilisable par le watchdog.

Anthropic fournit un SDK Python MCP : `pip install mcp-sdk`. Implémenter ces servers prendra ~200 lignes par server, à faire en Phase 7-8.

## A.8 Coûts et budget

**Tarification Managed Agents** (à jour Avril 2026, vérifier sur platform.claude.com) :
- **Runtime de session** : $0.08/heure (mesuré à la milliseconde, idle gratuit)
- **Tokens Claude Sonnet 4.6** : $3/M input, $15/M output
- **Tokens Claude Opus 4.6** : $15/M input, $75/M output
- **Web Search** : $10/1000 recherches

**Budget mensuel estimé pour APEX (configuration recommandée)** :

| Agent | Fréquence | Durée typique | Modèle | Coût mensuel estimé |
|---|---|---|---|---|
| Veille quant hebdo | 1/sem | 30 min | Sonnet | ~$2 |
| Backfill data background | 2/sem | 1h | Sonnet | ~$3 |
| Nightly backtest (Phase 5+) | 1/jour | 20 min | Sonnet | ~$5 |
| Watchdog prod (Phase 8+) | 24/7 idle + check 1/min | minimale | Sonnet | ~$15 |
| Reporting hebdo | 1/sem | 15 min | Sonnet | ~$1 |

**Total réaliste pour Phase 2-5** : ~$10/mois  
**Total pour Phase 8+ avec watchdog 24/7** : ~$25-40/mois

C'est négligeable comparé à la valeur (1h de veille manuelle économisée par semaine = $50+ d'opportunity cost à ton taux).

---

# Partie B — Cas d'usage par phase du projet

## B.1 Phase 2 (Data Infrastructure)

### Ce qu'on PEUT paralléliser maintenant (zero risque)

| Tâche | Pourquoi c'est safe en parallèle |
|---|---|
| **Backfill historique massif** des 13 symbols crypto sur 5 ans (BTCUSDT, ETHUSDT, etc.) | Aucune modif de code, juste écriture en DB |
| **Backfill historique** des 10 equities US (SPY, AAPL, NVDA...) sur 5 ans via Alpaca/Massive | Idem |
| **Backfill historique** des indices/FX/ETFs Yahoo sur 10 ans | Idem |
| **Cross-validation Alpaca vs Massive** : agent qui télécharge le même range sur les deux providers et flag les divergences | Lecture seule, écriture dans `data/cross_validation_reports/` |
| **Veille papers académiques** quant arXiv/SSRN sur HAR-RV, Rough Vol, OFI | 100% indépendant du repo |

### Ce qu'on NE peut PAS paralléliser dans Phase 2

| Tâche | Pourquoi c'est dangereux |
|---|---|
| Deux sub-phases qui modifient `core/config.py` simultanément | Merge conflict garanti, mypy peut casser |
| Deux sub-phases qui modifient `normalizers/router.py` | Idem |
| Sub-phases qui modifient `pyproject.toml` ou `requirements.txt` en même temps | Conflits Python deps |
| Toute modification simultanée de fichiers communs S01 | Risque de régression sur les 935 tests |

**Verdict Phase 2** : continue le workflow Claude Code séquentiel pour les 6 sub-phases restantes (2.7 → 2.12). Lance en parallèle les agents de backfill historique et de veille — ils tournent en background sans toucher au code.

### Action immédiate pour Phase 2

Déploie **dès maintenant** en parallèle de Phase 2.7 (FRED) :

1. **Agent `apex-backfill-historical`** — backfill 5 ans BTCUSDT/ETHUSDT/SPY/AAPL en background pendant que tu codes 2.7-2.12
2. **Agent `apex-veille-quant`** — brief hebdo automatique des nouveaux papers HAR-RV / OFI / GEX

Templates fournis en Partie C.

## B.2 Agents périphériques utilisables MAINTENANT

Indépendants du code, déployables aujourd'hui sans risque :

### Agent `apex-veille-quant`
- **Quoi** : Scanne arXiv (q-fin.ST, q-fin.TR), SSRN, Bridgewater Daily Observations, AQR Insights, Two Sigma blog, Man AHL papers, Hudson River Trading, Renaissance public talks
- **Quand** : Tous les lundis 8h
- **Output** : Markdown brief dans `docs/veille/YYYY-MM-DD-quant-brief.md` + résumé email
- **Coût** : ~$2/mois

### Agent `apex-veille-data-providers`
- **Quoi** : Surveille les changements de pricing/limits d'Alpaca, Massive, FRED, Yahoo. Détecte breaking changes API
- **Quand** : 1/semaine
- **Output** : Notion page mise à jour
- **Coût** : ~$1/mois

### Agent `apex-backfill-historical`
- **Quoi** : Lance les backfills volumineux (5 ans 1m de 20 symbols) en background. Reprend sur erreur via checkpointing
- **Quand** : À la demande (déclenché manuellement ou par webhook)
- **Output** : Données dans TimescaleDB + rapport dans `data/backfill_runs/`
- **Coût** : ~$3-5 par run complet

### Agent `apex-dep-auditor` *(ajouté par audit #59)*
- **Quoi** : Lance `pip-audit` hebdomadaire sur `requirements.txt`. Crée automatiquement des issues GitHub pour les CVEs critiques. Produit un résumé des vulnérabilités connues.
- **Quand** : 1/semaine (lundi matin)
- **Output** : Issues GitHub pour nouvelles CVEs, résumé dans `docs/security/`
- **Coût** : ~$1/mois (Haiku 4.5, tâche simple)
- **Justification** : 19 CVEs trouvées par l'audit #55 dans 10 packages. Sans scan automatisé, les vulnérabilités s'accumulent silencieusement.

### Agent `apex-convention-checker` *(ajouté par audit #59)*
- **Quoi** : Vérifie sur chaque PR que les commit messages suivent Conventional Commits, que les docstrings citent les références académiques requises, que les conventions de nommage sont respectées, et qu'aucun pattern interdit (float pour prix, print(), threading) n'est introduit.
- **Quand** : Manuel ou déclenché par PR
- **Output** : Commentaire sur la PR avec violations trouvées
- **Coût** : ~$1-2/mois (Sonnet 4.6, 5min par PR, ~10 PRs/mois)
- **Justification** : Complète le CI qui ne couvre pas les conventions de commit, naming, et format de docstrings.

### Agent `apex-fixture-generator`
- **Quoi** : Génère et met à jour les fixtures de test (téléchargement réel de données récentes pour les tests)
- **Quand** : 1/mois ou avant chaque release
- **Output** : Fichiers dans `tests/fixtures/`
- **Coût** : ~$1/mois

## B.3 Phase 3 (Feature validation harness)

Phase 3 = mesure d'IC (Information Coefficient) sur 3 ans de données réelles pour valider les signaux S02.
Full specification: `docs/phases/PHASE_3_SPEC.md` (13 sub-phases, 60 references).

### Agents Phase 3 spécifiques

#### Agent `apex-paper-watcher` (P0 — $2-4/mois)

- **Quoi** : Scanne arXiv q-fin.ST, q-fin.TR, SSRN Financial Economics pour les nouveaux papers pertinents aux features Phase 3 (HAR-RV, rough vol, OFI, microstructure, GEX). Produit un brief hebdo filtré par pertinence APEX.
- **Quand** : Tous les lundis 8:00 UTC
- **Model** : Claude Sonnet 4.6
- **Output** : `docs/veille/YYYY-MM-DD-phase3-brief.md`
- **Coût** : ~$2-4/mois
- **Priorité** : P0 — déployable immédiatement
- **ROI** : Attrape les améliorations méthodologiques avant que la validation soit finalisée. Un seul paper pertinent peut éviter un mois de travail inutile.
- **Activation** : Déployer pendant Phase 3.1

#### Agent `apex-codebase-analyzer` (P0 — $1-3/mois)

- **Quoi** : Audit incrémental hebdomadaire du package `features/` ajouté pendant Phase 3. Vérifie : couverture de tests, conformité mypy, présence de docstrings, violations SOLID, patterns interdits (float, print, threading).
- **Quand** : Tous les dimanches 20:00 UTC
- **Model** : Claude Haiku 4.5
- **Output** : `docs/audits/incremental/YYYY-MM-DD-phase3-audit.md`
- **Coût** : ~$1-3/mois
- **Priorité** : P0 — déployer après merge de Phase 3.1
- **ROI** : Détecte la dérive qualité avant qu'elle ne s'accumule. Chaque finding P1 évité en amont = 30 min de refactor économisées.
- **Activation** : Déployer après Phase 3.1 (le code existe pour auditer)

#### Agent `apex-feature-tester` (P1 — $10-15/mois)

- **Quoi** : Lance le pipeline IC sur un feature spécifique contre les dernières données. Produit un rapport IC et compare à la baseline précédente. Alerte si IC dégrade > 20%.
- **Quand** : À la demande (quand nouvelles données arrivent ou feature modifié)
- **Model** : Claude Sonnet 4.6
- **Inputs** : Nom du feature, symbol, date range
- **Output** : IC report JSON + Markdown dans `data/ic_reports/`
- **Coût** : ~$3-5/run (~$10-15/mois si déclenché bi-hebdo)
- **Priorité** : P1 — **ATTENTION : peut pousser le budget total à $15-22/mois, près du plafond.** Considérer de lancer manuellement si le budget est serré.
- **Activation** : Déployer après Phase 3.3 (framework IC prêt)

#### Agent `apex-academic-coherence-checker` (P1 — $1-2/mois)

- **Quoi** : Vérifie sur chaque PR au package `features/` que chaque classe `FeatureCalculator` cite le paper académique source dans sa docstring, que la formule mathématique correspond au paper, et que l'implémentation est cohérente avec la référence citée.
- **Quand** : Sur chaque PR touchant `features/`
- **Model** : Claude Haiku 4.5
- **Output** : Commentaire sur la PR avec résultats du check de cohérence
- **Coût** : ~$1-2/mois
- **Priorité** : P1
- **Activation** : Déployer après Phase 3.4 (premier FeatureCalculator existe)

### Budget Phase 3

| Agent | Coût mensuel | Priorité |
|---|---|---|
| apex-paper-watcher | $2-4 | P0 |
| apex-codebase-analyzer | $1-3 | P0 |
| apex-feature-tester | $10-15 | P1 (peut dépasser budget) |
| apex-academic-coherence-checker | $1-2 | P1 |
| **Total P0** | **$3-7** | |
| **Total P0+P1** | **$14-24** | Proche du plafond budget |

**Recommandation** : Déployer les agents P0 immédiatement ($3-7/mois). Évaluer les P1 après Phase 3.3 en fonction du budget réel.

### Parallélisation possible (via Claude Code subagents)

- Un subagent par feature (HAR-RV, Rough Vol, OFI, CVD, Kyle lambda, GEX). Chaque agent calcule l'IC sur son propre subset, indépendamment.
- **Output** : `data/ic_reports/<feature>/<symbol>/<date>.json`
- Coordination via un agent maître `apex-ic-aggregator` pattern fan-out / fan-in.

## B.4 Phase 4-5 (Signal Engine + Backtesting)

### Agent `apex-nightly-backtest`
- **Quoi** : Lance chaque nuit un backtest complet sur les dernières données ingérées. Compare les métriques (Sharpe, Sortino, max DD, Calmar) à la baseline. Alerte si dégradation > 5%.
- **Quand** : Tous les jours 2h du matin
- **Output** : Rapport JSON + Markdown dans `data/backtest_runs/`, alerte Slack/email si seuil dépassé
- **Coût** : ~$5/mois

### Agent `apex-strategy-tournament`
- **Quoi** : Test simultané de N variantes de paramètres d'une stratégie sur un grand range historique. Pattern grid search distribué.
- **Quand** : À la demande
- **Output** : Leaderboard CSV
- **Coût** : variable, ~$10-20 par tournament complet

### Agent `apex-walk-forward-validator`
- **Quoi** : Walk-forward analysis sur les stratégies validées, prévention overfitting
- **Quand** : Avant chaque promotion d'une stratégie en paper trading
- **Output** : Rapport CPCV/PBO dans `data/validation_runs/`

## B.5 Phase 6-7 (Risk Manager + Order Manager)

### Agent `apex-risk-stress-tester`
- **Quoi** : Simule en continu des scénarios de stress (flash crash, liquidity crunch, gap d'ouverture, halt) sur le Risk Manager. Vérifie que les circuit breakers déclenchent bien
- **Quand** : 1/semaine
- **Output** : Rapport stress dans `data/risk_stress_reports/`

### Agent `apex-order-replay`
- **Quoi** : Rejoue les ordres de la journée précédente sur paper trading et compare à l'exécution simulée pour détecter des anomalies de slippage / fill rate
- **Quand** : 1/jour fin de marché
- **Output** : Rapport CSV

## B.6 Phase 8+ (Live Trading) — agents critiques 24/7

À partir du moment où APEX trade vraiment de l'argent, ces agents deviennent **indispensables** :

### Agent `apex-watchdog-circuit-breaker` (CRITIQUE)
- **Quoi** : Vérifie toutes les 30 secondes l'état du Circuit Breaker via MCP server `apex-risk`. Si OPEN ou HALF_OPEN, ping immédiatement par SMS/email/Slack
- **Permissions** : read-only sur état, write sur alertes
- **Coût** : ~$15/mois (toujours actif)
- **Type** : à déployer en `always_allow` pour les outils de notification

### Agent `apex-watchdog-data-feed` (CRITIQUE)
- **Quoi** : Vérifie toutes les minutes que les feeds Binance/Alpaca live envoient des messages. Détecte les freeze, déconnexions, lag anormal. Restart automatique du feed si possible, sinon alerte humain
- **Coût** : ~$15/mois

### Agent `apex-incident-commander` (template Sentry-like)
- **Quoi** : Quand une alerte Sentry/PagerDuty arrive, l'agent triage automatiquement, ouvre un ticket dans ton outil (Linear/Notion), poste dans le channel war room, et propose un diagnostic initial basé sur les logs structlog
- **Coût** : variable, ~$5-10/mois

### Agent `apex-daily-pnl-reporter`
- **Quoi** : Génère chaque soir un rapport markdown avec : positions ouvertes, P&L jour/semaine/mois, drawdown actuel, comparaison vs benchmark (SPY/BTC), top trades gagnants/perdants
- **Coût** : ~$2/mois

### Agent `apex-compliance-logger`
- **Quoi** : Audit trail de tous les trades, vérifie qu'ils sont conformes aux contraintes documentées dans les ADRs (taille max position, exposure max par asset class, etc.). Génère un rapport mensuel signé pour archivage légal
- **Coût** : ~$2/mois

## B.7 Veille permanente et research support

Indépendant des phases techniques, à mettre en place dès maintenant pour accélérer ton apprentissage :

### Agent `apex-paper-summarizer`
- **Quoi** : Quand tu lui pousses un PDF de paper, il extrait le pseudocode, la formulation mathématique, les datasets utilisés, et te génère un mini ADR template "Implémentation candidate dans APEX"
- **Coût** : ~$1 par paper

### Agent `apex-competitor-monitor`
- **Quoi** : Surveille QuantConnect, Lean, Backtrader, Nautilus Trader, vectorbt, hummingbot. Détecte les nouvelles features, met à jour un tableau comparatif vs APEX
- **Coût** : ~$2/mois

### Agent `apex-conference-tracker`
- **Quoi** : Surveille les annonces de conférences quant (QuantMinds, AI in Capital Markets, RiskMinds, NeurIPS workshops sur finance). Pousse les CFP et les talks pertinents
- **Coût** : ~$1/mois

---

# Partie C — Templates d'agents prêts à déployer

## Template 1 : `apex-veille-quant` (déployable AUJOURD'HUI)

```yaml
# agents/veille_quant.yaml
name: apex-veille-quant
model: claude-sonnet-4-6
description: Veille hebdomadaire des publications académiques et industrielles quant
schedule: "0 8 * * MON"  # Lundi 8h

system_prompt: |
  Tu es l'analyste de veille quantitative d'APEX, un projet de système de trading
  algorithmique institutionnel. Ton rôle est de produire un brief hebdomadaire
  des nouveautés pertinentes pour le développement d'APEX.

  ## Sources à scanner

  ### Académique
  - arXiv q-fin.ST (Statistical Finance) — papers de la semaine écoulée
  - arXiv q-fin.TR (Trading and Market Microstructure) — papers de la semaine
  - SSRN — Financial Economics Network, Quantitative Finance Network
  - Journal of Financial Economics — table of contents récente
  - Review of Financial Studies — table of contents récente

  ### Industrielle
  - Bridgewater Daily Observations (publiques)
  - AQR Insights (insights.aqr.com)
  - Two Sigma blog (twosigma.com/articles)
  - Man AHL Tech Blog
  - Hudson River Trading blog
  - Jane Street tech blog
  - Renaissance Technologies (talks publics)

  ### Outils et open source
  - Nouveautés QuantConnect/Lean
  - Releases vectorbt, Nautilus, Backtrader
  - Papers with Code section finance

  ## Filtrage prioritaire APEX

  Concentre-toi sur les sujets directement applicables à APEX :
  - HAR-RV (Heterogeneous Autoregressive Realized Volatility) et extensions
  - Rough Volatility (Bayer, Friz, Gatheral)
  - Order Flow Imbalance, Kyle lambda, VPIN
  - Gamma exposure, dealer hedging
  - Meta-labeling (Lopez de Prado)
  - PSR/DSR/PBO/CPCV (Bailey et al.)
  - Bayesian Kelly, regime detection
  - Microstructure crypto (Makarov & Schoar)
  - Risk management institutionnel (Markowitz extensions, Black-Litterman)

  Ignore : papers ML pure sans application finance, papers crypto promotionnels,
  contenus générés par IA sans valeur, marketing déguisé.

  ## Format du brief

  Produis un fichier markdown structuré ainsi :

  # APEX Veille Quant — Semaine du [DATE]

  ## TL;DR
  3-5 bullets ultra-condensés des découvertes les plus importantes pour APEX

  ## Papers académiques pertinents
  Pour chaque paper (max 5) :
  - **Titre** + lien
  - **Auteurs / Institution**
  - **Résumé en 3 phrases**
  - **Pertinence APEX** : sur quelle phase / quel module ça pourrait s'appliquer
  - **Action recommandée** : Lire en détail / Implémenter en POC / Watch / Skip

  ## Insights industriels
  Pour chaque post de blog institutionnel pertinent (max 3) :
  - **Source + titre + lien**
  - **Idée clé en 2 phrases**
  - **Lien avec APEX**

  ## Outils et releases
  Liste des nouvelles versions/features pertinentes des outils open source

  ## Recommandations actionables
  3 actions concrètes que je devrais envisager cette semaine pour APEX

tools:
  - type: web_search
    permission: always_allow
  - type: web_fetch
    permission: always_allow
  - type: file_write
    permission: always_allow
    allowed_paths: ["docs/veille/"]

environment:
  type: cloud
  packages:
    pip: ["requests", "feedparser", "arxiv"]
```

**Déploiement** : Crée cet agent sur platform.claude.com → Blank Agent → colle le system prompt. Active web_search + web_fetch. Sauvegarde. Lance ta première session manuellement avec "Génère le brief de cette semaine".

## Template 2 : `apex-backfill-historical`

```yaml
# agents/backfill_historical.yaml
name: apex-backfill-historical
model: claude-sonnet-4-6
description: Backfill massif de données historiques en background

system_prompt: |
  Tu es l'agent de backfill historique d'APEX. Ton rôle est de télécharger
  de grandes quantités de données historiques en background sans bloquer
  le développement principal.

  ## Symbols cibles

  ### Crypto (Binance public archive — pas de clé requise)
  BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT, ADAUSDT, AVAXUSDT,
  DOGEUSDT, DOTUSDT, MATICUSDT, LINKUSDT, UNIUSDT
  Période : 2020-01-01 → aujourd'hui
  Résolutions : 1m + 1h + 1d

  ### US Equities (Alpaca paper — clés via vault)
  SPY, QQQ, AAPL, MSFT, NVDA, GOOGL, TSLA, META, AMZN, AMD
  Période : 2020-01-01 → aujourd'hui
  Résolutions : 1m + 5m + 1h + 1d

  ### Indices et ETFs (Yahoo Finance — pas de clé)
  ^GSPC, ^IXIC, ^VIX, ^FCHI, ^GDAXI, ^N225,
  EWJ, EWZ, EWG, EFA, EEM, GLD, SLV, USO
  Période : 2015-01-01 → aujourd'hui
  Résolutions : 1d uniquement (limitation Yahoo)

  ## Pipeline

  Pour chaque symbol, lance le script de backfill APEX correspondant :
  - Crypto : python -m scripts.backfill_binance --symbol X --start ... --end ...
  - US Equities : python -m scripts.backfill_equities --provider alpaca --symbol X ...
  - Indices : python -m scripts.backfill_yahoo --symbol X --asset-class index ...

  ## Comportement

  - Procède séquentiellement par symbol (pas de parallélisme à l'intérieur de l'agent
    pour respecter les rate limits providers)
  - Checkpointing : note dans ingestion_runs DB l'avancement
  - Resume on failure : si ton run plante, reprends au dernier checkpoint
  - Reporting : à la fin de chaque symbol, log le nombre de bars insérées et le temps
  - Si erreur persistante (> 3 retries) sur un symbol, skip et notifier

  ## Output final

  Rapport markdown dans data/backfill_runs/YYYY-MM-DD-backfill-report.md avec :
  - Symbols traités vs échoués
  - Total bars insérées
  - Durée totale
  - Erreurs rencontrées
  - Recommandation pour les symbols échoués

tools:
  - type: bash
    permission: always_allow
  - type: file_read
    permission: always_allow
  - type: file_write
    permission: always_allow
    allowed_paths: ["data/backfill_runs/", "logs/"]

environment:
  type: cloud
  packages:
    pip: ["asyncpg", "httpx", "structlog", "tqdm", "pandas", "yfinance",
          "alpaca-py", "boto3", "pydantic", "pydantic-settings"]
  secrets:
    - ALPACA_API_KEY
    - ALPACA_API_SECRET
    - MASSIVE_API_KEY
    - MASSIVE_S3_ACCESS_KEY
    - MASSIVE_S3_SECRET_KEY
    - TIMESCALE_HOST
    - TIMESCALE_USER
    - TIMESCALE_PASSWORD
```

## Template 3 : `apex-nightly-backtest` (Phase 5+)

À déployer après que Phase 5 (Backtesting Engine) soit en place. Skeleton :

```yaml
name: apex-nightly-backtest
schedule: "0 2 * * *"  # 2h du matin tous les jours

system_prompt: |
  Tu es l'agent de backtest nightly d'APEX. Chaque nuit tu lances un
  backtest complet sur les stratégies actives, compares les métriques
  à la baseline, et alertes en cas de dégradation.

  ## Workflow

  1. Pull les dernières données ingérées (depuis ingestion_runs)
  2. Lance python -m scripts.backtest_nightly pour chaque stratégie active
  3. Parse les résultats : Sharpe, Sortino, max DD, Calmar, PSR, DSR
  4. Compare à la baseline stockée dans data/baselines/
  5. Si dégradation > 5% sur Sharpe ou > 10% sur PSR, alerte immédiate
  6. Génère rapport markdown dans data/nightly_reports/
  7. Push notification Slack/email
```

## Template 4 : `apex-watchdog-circuit-breaker` (Phase 8+ CRITIQUE)

À déployer uniquement quand APEX trade vraiment. Skeleton :

```yaml
name: apex-watchdog-circuit-breaker
runtime: persistent  # toujours actif
check_interval: 30s

system_prompt: |
  Tu surveilles l'état du Circuit Breaker d'APEX en production 24/7.

  Toutes les 30 secondes :
  1. Query le MCP server apex-risk pour current_circuit_breaker_state()
  2. Si state == CLOSED : tout va bien, log silencieux
  3. Si state == HALF_OPEN : alerte WARNING immédiate
  4. Si state == OPEN : alerte CRITICAL immédiate + page humain

  Format alerte CRITICAL :
  - Slack channel #apex-prod-alerts
  - Email à clement@example.com
  - SMS via Twilio si configuré

  Inclure dans l'alerte :
  - Timestamp UTC précis
  - Raison de l'ouverture (depuis Redis state)
  - Positions ouvertes au moment de l'ouverture
  - Lien vers dashboard S10
```

---

## Annexes

### Annexe 1 : Liens utiles

- Console Managed Agents : https://platform.claude.com/workspaces/default/agent-quickstart
- Documentation officielle : https://platform.claude.com/docs/en/managed-agents/overview
- API Reference Sessions : https://platform.claude.com/docs/en/api/beta/sessions
- MCP SDK Python : https://github.com/anthropic/mcp-sdk-python
- Templates communautaires : https://platform.claude.com/templates

### Annexe 2 : Checklist avant de déployer un nouvel agent APEX

- [ ] Le YAML de config est dans `agents/` et versionné dans git
- [ ] Le system prompt est explicite, scope-limité, et inclut la convention APEX
- [ ] Aucun secret en clair dans le YAML
- [ ] Les permissions sont bien `always_ask` pour les outils dangereux (write hors dossiers dédiés, MCP tiers)
- [ ] Le coût mensuel estimé est documenté dans `agents/README.md`
- [ ] Un test manuel de la première session a été effectué
- [ ] L'output de l'agent va dans un dossier dédié (`data/`, `docs/veille/`, `logs/`)
- [ ] Il y a un mécanisme de désactivation (pause schedule ou kill switch)

### Annexe 3 : Anti-patterns à éviter

1. **Agent qui modifie le code source APEX automatiquement** — toujours passer par Claude Code + PR review
2. **Agent qui exécute des trades** — c'est le rôle de S07 Order Manager, jamais d'un Managed Agent
3. **Agent qui partage un même fichier de config avec un autre agent** — chaque agent isolé
4. **Agent sans schedule ni kill switch** — risque de runaway costs
5. **Agent sans monitoring de coût** — vérifie le dashboard 1/semaine

### Annexe 4 : Roadmap d'adoption Managed Agents pour APEX

| Date | Action | Statut |
|---|---|---|
| Aujourd'hui | Lire ce playbook | ✅ |
| Semaine 1 | Déployer `apex-veille-quant` (template 1) | ⏳ |
| Semaine 1 | Déployer `apex-dep-auditor` (ajouté par audit #59) | ⏳ |
| Semaine 2 | Déployer `apex-backfill-historical` (template 2) | ⏳ |
| Phase 3 | Agent `apex-feature-ic-runner` (multi-agent fan-out) | ⏳ |
| Phase 5 | `apex-nightly-backtest` (template 3) | ⏳ |
| Phase 6 | `apex-risk-stress-tester` | ⏳ |
| Phase 8 | `apex-watchdog-circuit-breaker` + `apex-watchdog-data-feed` (CRITIQUE) | ⏳ |
| Phase 8+ | Suite complète live trading (5 agents) | ⏳ |

---

**Document maintenu par** : Clement Barbier  
**Dernière mise à jour** : Avril 2026  
**Prochaine review** : Après chaque phase APEX terminée