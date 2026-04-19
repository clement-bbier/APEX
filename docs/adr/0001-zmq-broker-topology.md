# ADR-0001 — ZMQ Broker (XSUB/XPUB) Topology

> *Note (2026-04-18): This ADR continues to govern its respective subsystem. See [APEX Multi-Strat Charter](../strategy/ALPHA_THESIS_AND_MULTI_STRAT_CHARTER.md) §12.4 for the inventory of existing and anticipated ADRs in the multi-strat context.*

Status: Accepted
Date: 2026-04-08
Decider: clement-bbier

## Context
APEX has 10 microservices that need many-to-many pub/sub messaging. The first iteration tried `S01 bind / S02-S10 connect`, which silently dropped every message published by S02-S10 (a bound PUB socket only delivers messages it produced itself).

## Decision
Use the canonical ZeroMQ Forwarder pattern: a single broker process (`core/zmq_broker.py`) binds an XSUB socket on `ZMQ_PUB_PORT` (5555) and an XPUB socket on `ZMQ_SUB_PORT` (5556). All services CONNECT — none binds. The broker is the only process allowed to bind ZMQ ports.

## Consequences
- Any service can publish AND subscribe simultaneously.
- The broker must start BEFORE any other service (handled by supervisor/orchestrator.py).
- A slow-joiner problem exists: subscribers must register before publishers send. The supervisor handles this by starting S01 last (or after a 200ms grace period).
- Adding new services requires zero topology change.

## Alternatives rejected
- S01 binds, others connect → silently broken (see Context).
- ROUTER/DEALER → too low-level, no native pub/sub semantics.
- Redis Pub/Sub → adds latency, no message ordering guarantees per topic.
