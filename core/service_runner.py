"""Common entry-point helper for APEX service modules.

Every ``services/sNN_xxx/service.py`` file uses
:func:`run_service_module` from its ``__main__`` block. The helper:

1. Forces the Windows selector event-loop policy (pyzmq is incompatible
   with the default proactor loop on Windows).
2. Adds the project root to ``sys.path`` so the module can be launched as
   ``python services/s01_data_ingestion/service.py`` *or* as
   ``python -m services.s01_data_ingestion.service``.
3. Discovers the unique :class:`BaseService` subclass declared in the
   caller module via introspection (no manual class name registration).
4. Runs the service inside a hardened ``try/except`` that prints a full
   ``traceback.format_exc()`` instead of failing silently — that single
   change made the previous health-gate timeouts diagnosable.

The helper exists in ``core`` (rather than being copy-pasted at the bottom
of each service) so a future fix only needs to be applied in one place.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import sys
import traceback
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

if TYPE_CHECKING:
    from core.base_service import BaseService


def _ensure_repo_on_syspath(module_file: str) -> None:
    """Insert the project root in ``sys.path`` if it is missing.

    Args:
        module_file: ``__file__`` of the calling service module.
    """
    repo_root = Path(module_file).resolve().parent.parent.parent
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)


def _resolve_service_class(module: ModuleType) -> type[BaseService]:
    """Return the unique :class:`BaseService` subclass defined in *module*.

    Args:
        module: Imported service module to inspect.

    Returns:
        The single concrete subclass of :class:`BaseService` found.

    Raises:
        RuntimeError: If zero or more than one matching class is found.
    """
    from core.base_service import BaseService

    candidates: list[type[BaseService]] = []
    for _name, obj in inspect.getmembers(module, inspect.isclass):
        if issubclass(obj, BaseService) and obj is not BaseService:
            # Only count classes defined in this exact module to avoid
            # picking up re-exports from base_service or shared mixins.
            if obj.__module__ == module.__name__:
                candidates.append(obj)

    if not candidates:
        raise RuntimeError(f"No BaseService subclass found in module {module.__name__!r}")
    if len(candidates) > 1:
        names = ", ".join(c.__name__ for c in candidates)
        raise RuntimeError(f"Multiple BaseService subclasses found in {module.__name__!r}: {names}")
    return candidates[0]


async def _run(service: BaseService) -> None:
    """Run a service until shutdown is requested or the loop is cancelled."""
    try:
        await service.start()
        # ``start()`` already calls ``run()`` and only returns once the
        # service stops itself; the loop below covers the (rare) case where
        # ``run()`` returns immediately so the heartbeat task keeps the
        # process alive.
        while service._running:
            await asyncio.sleep(1.0)
    finally:
        await service.stop()


def run_service_module(module_file: str) -> None:
    """Bootstrap and run the unique service defined in *module_file*.

    This is the only function service ``__main__`` blocks need to call::

        if __name__ == "__main__":
            from core.service_runner import run_service_module
            run_service_module(__file__)

    Args:
        module_file: ``__file__`` from the calling service module.
    """
    _ensure_repo_on_syspath(module_file)

    module_name = "services." + Path(module_file).resolve().parent.name + ".service"
    module = importlib.import_module(module_name)

    try:
        service_cls = _resolve_service_class(module)
    except RuntimeError as exc:
        sys.stderr.write(f"[service-runner] {exc}\n")
        sys.exit(2)

    # Each concrete APEX service overrides ``__init__`` to take no
    # arguments and pass its own ``service_id`` up to ``BaseService``;
    # mypy still sees the abstract signature, so silence the call.
    service = service_cls()  # type: ignore[call-arg]

    try:
        asyncio.run(_run(service))
    except KeyboardInterrupt:
        sys.stderr.write(f"[{service.service_id}] Interrupted by user, shutting down...\n")
    except Exception:
        # Surface the *full* traceback so health-gate failures stop being
        # silent. The orchestrator captures stdout+stderr and tags each line
        # with the service id.
        sys.stderr.write(
            f"[{service.service_id}] Fatal error during execution:\n"
            + traceback.format_exc()
            + "\n"
        )
        sys.exit(1)
