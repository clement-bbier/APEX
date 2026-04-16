## [TECH DEBT] Résilience Réseau — Remplacement du SPOF ZMQ par un bus Peer-to-Peer

**Priorité** : MOYENNE (Goulet d'étranglement de l'infrastructure)
**Composants** : `core/zmq_broker.py`, couche de transport (`core/bus.py`)

---

### 1. Contexte Industriel & Références

Les infrastructures du CME Group et des Prop Shops HFT n'utilisent jamais de broker de messagerie centralisé (topologie hub-and-spoke) à cause du risque de point de défaillance unique (SPOF) et du doublement de la latence réseau (saut supplémentaire). Ils déploient des topologies distribuées (Aeron, UDP Multicast).

### 2. Opportunité & Problème

Le système APEX dépend d'un unique processus proxy XSUB/XPUB (`zmq_broker.py`). Si le broker crash, subit un ralentissement matériel ou est redémarré, 100% du pipeline de trading est paralysé et aveuglé.

### 3. Architecture de la Solution (En 2 Phases)

**Phase 1 : Topologie Distribuée (Service Discovery)**
- Supprimer le processus broker central.
- Chaque Publisher (ex: S01) lie (`BIND`) son propre port éphémère et publie son adresse dans Redis (Service Registry).
- Chaque Subscriber (ex: S02) lit Redis et se connecte (`CONNECT`) en direct (Peer-to-Peer) aux publishers requis.

**Phase 2 : Évaluation Aeron (Optionnelle)**
- Préparer une interface abstraite permettant le remplacement futur de ZeroMQ par le protocole Aeron IPC (Real Logic) pour les déploiements bare-metal.

### 4. Critères d'Acceptation (Definition of Done)

- [ ] **Tolérance aux Pannes** : Un test de résilience prouve que l'on peut détruire aléatoirement des conteneurs S01 ou S08 sans jamais interrompre la communication entre S02 et S05.
- [ ] **Réduction Latence Réseau** : Baisse mesurable de la latence de transport grâce à la suppression du saut (hop) réseau intermédiaire.
- [ ] Service Registry dans Redis avec TTL et heartbeat.
- [ ] Interface abstraite `TransportLayer` permettant le swap ZMQ / Aeron.

### Références

- CME Group infrastructure whitepapers
- Real Logic Aeron (https://github.com/real-logic/aeron)
- CLAUDE.md §2 : « ZMQ topics are defined in core/topics.py »
