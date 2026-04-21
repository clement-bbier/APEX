"""Backfill Orchestrator for APEX S01 Data Ingestion.

Centralized scheduler that drives all Phase 2.4-2.9 connectors via cron
patterns, with retry/state/gap detection.

Architecture: Registry-based ConnectorFactory (OCP) + JobRunner with
template method (retry, lock, state) + BackfillScheduler with croniter.

Refs: Kleppmann (2017) Ch. 10-12, Akidau et al. (2015) Dataflow Model.
"""

from __future__ import annotations
