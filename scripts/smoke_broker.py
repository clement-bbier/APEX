"""End-to-end smoke test for the APEX XSUB/XPUB broker.

This script proves the new topology actually delivers messages from one
service to another through the broker. It is the regression test for the
"S02 silently dropped messages" bug that the broker was introduced to
fix.

Run with::

    PYTHONPATH=. python scripts/smoke_broker.py

The script must be runnable WITHOUT a real Redis instance: the broker's
heartbeat loop survives Redis being unavailable. Set ``REDIS_URL`` to a
running Redis if you want to also exercise the heartbeat path.

Exit code 0 = success, 1 = failure (with traceback on stderr).
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Force disjoint dev ports so the smoke test never collides with the
# real APEX deployment running on 5555/5556 in dev.
os.environ.setdefault("ZMQ_PUB_PORT", "55555")
os.environ.setdefault("ZMQ_SUB_PORT", "55556")
os.environ.setdefault("ZMQ_HOST", "127.0.0.1")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/0")

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Import AFTER env vars are set so they win over .env defaults.
import core.config as _cfg  # noqa: E402

_cfg._settings = None  # reset singleton — pick up our overrides
from core.bus import MessageBus  # noqa: E402
from core.zmq_broker import ZmqBroker  # noqa: E402

EXPECTED_TOPIC = "tick.crypto.BTCUSDT"
EXPECTED_PAYLOAD = {"symbol": "BTCUSDT", "price": "65000.00", "session": "us_open"}


async def _publisher(bus: MessageBus, ready: asyncio.Event) -> None:
    """Publish the test tick three times so the SUB definitely gets one."""
    bus.init_publisher()
    # Give the SUB socket time to register its subscription with the
    # broker. PUB/SUB has a slow-joiner problem — messages sent before
    # the broker has heard the SUBSCRIBE frame are dropped.
    await ready.wait()
    for _ in range(3):
        await bus.publish(EXPECTED_TOPIC, EXPECTED_PAYLOAD)
        await asyncio.sleep(0.05)


async def _subscriber(bus: MessageBus, ready: asyncio.Event) -> tuple[str, dict[str, object]]:
    """Subscribe and return the first matching message."""
    bus.init_subscriber(["tick."])
    # Give the broker time to register the subscription.
    await asyncio.sleep(0.2)
    ready.set()
    return await asyncio.wait_for(bus.receive(), timeout=5.0)


async def _amain() -> int:
    broker = ZmqBroker()

    print(f"[smoke] starting broker on xsub={broker.xsub_endpoint} xpub={broker.xpub_endpoint}")
    try:
        await broker.start()
    except Exception as exc:
        print(f"[smoke] broker.start() failed: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 1

    pub_bus = MessageBus("smoke-publisher")
    sub_bus = MessageBus("smoke-subscriber")
    ready = asyncio.Event()

    try:
        sub_task = asyncio.create_task(_subscriber(sub_bus, ready))
        pub_task = asyncio.create_task(_publisher(pub_bus, ready))

        topic, payload = await sub_task
        # Give the publisher one tick to finish so its socket closes cleanly.
        await pub_task

        ok = topic == EXPECTED_TOPIC and payload == EXPECTED_PAYLOAD
        if ok:
            print(f"[smoke] OK — received topic={topic!r} payload={payload!r}")
            return 0
        print(
            f"[smoke] FAIL — expected ({EXPECTED_TOPIC!r}, {EXPECTED_PAYLOAD!r}) "
            f"got ({topic!r}, {payload!r})",
            file=sys.stderr,
        )
        return 1
    except TimeoutError:
        print("[smoke] FAIL — subscriber timed out (broker not forwarding!)", file=sys.stderr)
        return 1
    except Exception:
        print("[smoke] FAIL — unexpected exception:", file=sys.stderr)
        traceback.print_exc()
        return 1
    finally:
        for bus_name, bus_obj in (("pub", pub_bus), ("sub", sub_bus)):
            try:
                bus_obj.close()
            except Exception as exc:
                print(f"[smoke] {bus_name} close error: {exc}", file=sys.stderr)
        await broker.stop()


def main() -> None:
    try:
        rc = asyncio.run(_amain())
    except KeyboardInterrupt:
        rc = 130
    sys.exit(rc)


if __name__ == "__main__":
    started = time.time()
    main()
    print(f"[smoke] elapsed {time.time() - started:.2f}s")
