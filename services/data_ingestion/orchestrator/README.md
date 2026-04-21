# Backfill Orchestrator (Phase 2.11)

Centralized scheduler that drives all Phase 2.4-2.9 connectors via cron
patterns, with retry/state/gap detection.

## Architecture

```
jobs.yaml
    |
    v
OrchestratorConfig ----> BackfillScheduler
                              |
                    (one asyncio task per job)
                              |
                              v
                         JobRunner
                         /   |   \
              lock(Redis) retry  state(Redis)
                              |
                              v
                    ConnectorFactory.create()
                              |
                              v
                    DataConnector / MacroConnector / CalendarConnector / FundamentalsConnector
                              |
                              v
                    TimescaleRepository.insert_*()
```

### Design Patterns

- **Registry** (ConnectorFactory): 13 connectors auto-registered at import time
- **Factory** (ConnectorFactory.create): instantiate connectors from string names
- **Template Method** (JobRunner.run): lock -> retry -> fetch -> insert -> state
- **Command** (CLI): each sub-command is an isolated Command object
- **Strategy** (connectors): interchangeable via the factory
- **Dependency Injection**: JobRunner receives factory, repo, state, settings

### OCP compliance

Adding a new connector:

1. Implement the connector (DataConnector / MacroConnector / etc.)
2. Add one `ConnectorFactory.register("name", lambda s: MyConnector(s))` call in `connector_factory.py`
3. Add a job entry in `jobs.yaml`
4. Add the connector name to the appropriate `_*_CONNECTORS` frozenset in `job_runner.py`

No modification to JobRunner, Scheduler, or StateManager is needed.

## Usage

### Daemon mode

```bash
python -m services.data_ingestion.orchestrator.main
```

### CLI

```bash
# List all jobs
python -m services.data_ingestion.orchestrator.cli list

# Run a specific job immediately
python -m services.data_ingestion.orchestrator.cli run --job binance_btcusdt_1m

# Check job status
python -m services.data_ingestion.orchestrator.cli status --job binance_btcusdt_1m

# Reset job state (clear lock + history)
python -m services.data_ingestion.orchestrator.cli reset --job binance_btcusdt_1m

# Detect data gaps
python -m services.data_ingestion.orchestrator.cli gaps
```

### Docker

```bash
docker compose up s01-orchestrator
```

## Debugging a failing job

1. Check status: `python -m ...cli status --job <name>`
2. Look at recent history for error messages
3. Reset state if stuck: `python -m ...cli reset --job <name>`
4. Run manually: `python -m ...cli run --job <name>`
5. Check Redis keys: `redis-cli KEYS "apex:orchestrator:*"`

## Configuration

Jobs are defined in `jobs.yaml`. Each job has:

| Field | Description | Default |
|-------|------------|---------|
| name | Unique identifier | required |
| connector | Registered connector name | required |
| schedule | 5-field cron expression | required |
| enabled | Whether to schedule this job | true |
| params | Connector-specific parameters | {} |
| retry.max_attempts | Max retry attempts | 3 |
| retry.backoff_seconds | Base backoff delay | 30 |
| dependencies | Jobs that must succeed first | [] |
| timeout_seconds | Max wall-clock time per run | 3600 |
| on_failure | Action on failure: skip or raise | skip |

## References

- Kleppmann, M. (2017). *Designing Data-Intensive Applications*, Ch. 10-12.
- Akidau, T. et al. (2015). *The Dataflow Model*.
- Hunt, A. & Thomas, D. (2019). *The Pragmatic Programmer*, Ch. 5.
