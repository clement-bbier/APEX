# APEX System Guardrails & Instructions

## Code Quality & Validation
- **Typing**: Tout nouveau code doit être strictement typé. Utilise `mypy . --strict` pour valider.
- **Linting**: Respecte les règles `ruff`. Tout code doit passer `ruff check` avant d'être considéré comme valide.
- **Pre-commit**: Lance toujours `make lint` et `make test-unit` avant de proposer un commit ou une PR.

## Architecture & Topology
- **ZMQ**: Seul S01_data_ingestion a le droit de faire un `bind=True` sur le port 5555. Tous les autres services (S02-S10) doivent faire `bind=False` (connect).
- **Redis**: Toujours utiliser l'argument `ttl` (et non `expire_seconds`) dans les appels `StateStore.set()`.
- **Windows Compatibility**: Si `sys.platform == 'win32'`, appeler `asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())` au début du point d'entrée.

## CI/CD (GitHub Actions)
- Le code doit être "Environment Agnostic".
- Vérifier systématiquement que le `PYTHONPATH` est bien défini dans les workflows pour résoudre le dossier `core/`.
