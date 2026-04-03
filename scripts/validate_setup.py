#!/usr/bin/env python3
"""Pre-flight validation script for APEX Trading System.

Tests all external connections and prints colored pass/fail per check.
Exits 0 if all pass, 1 if any fail.
"""

from __future__ import annotations

import asyncio
import os
import sys

# ── ANSI colours ──────────────────────────────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"


def ok(msg: str) -> None:
    print(f"  {GREEN}✓ PASS{RESET}  {msg}")


def fail(msg: str, detail: str = "") -> None:
    suffix = f" - {detail}" if detail else ""
    print(f"  {RED}✗ FAIL{RESET}  {msg}{suffix}")


def warn(msg: str) -> None:
    print(f"  {YELLOW}⚠ WARN{RESET}  {msg}")


# ── Individual checks ─────────────────────────────────────────────────────────


def check_env() -> bool:
    """Verify all required environment variables are set."""
    required = [
        "ALPACA_API_KEY",
        "ALPACA_SECRET_KEY",
        "BINANCE_API_KEY",
        "BINANCE_SECRET_KEY",
        "REDIS_URL",
    ]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        fail("Environment variables", f"missing: {', '.join(missing)}")
        return False
    ok("Environment variables")
    return True


def check_redis() -> bool:
    """Ping Redis."""
    import redis

    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    try:
        r = redis.Redis.from_url(url, socket_timeout=5)
        r.ping()
        ok(f"Redis ({url})")
        return True
    except Exception as exc:
        fail(f"Redis ({url})", str(exc))
        return False


def check_zmq_ports() -> bool:
    """Check ZMQ ports are available."""
    import socket

    pub_port = int(os.environ.get("ZMQ_PUB_PORT", "5555"))
    sub_port = int(os.environ.get("ZMQ_SUB_PORT", "5555"))
    all_ok = True
    for port in {pub_port, sub_port}:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        try:
            result = s.connect_ex(("localhost", port))
            if result == 0:
                warn(f"ZMQ port {port} is already in use")
            else:
                ok(f"ZMQ port {port} is available")
        except Exception as exc:
            fail(f"ZMQ port {port}", str(exc))
            all_ok = False
        finally:
            s.close()
    return all_ok


def check_alpaca() -> bool:
    """Test Alpaca API connectivity using alpaca-py."""
    api_key = os.environ.get("ALPACA_API_KEY", "")
    secret_key = os.environ.get("ALPACA_SECRET_KEY", "")
    if not api_key or not secret_key:
        warn("Alpaca keys not set - skipping")
        return True
    try:
        from alpaca.trading.client import TradingClient

        client = TradingClient(api_key=api_key, secret_key=secret_key, paper=True)
        account = client.get_account()
        ok(f"Alpaca API (account: {account.id})")
        return True
    except Exception as exc:
        fail("Alpaca API", str(exc))
        return False


async def check_binance() -> bool:
    """Test Binance API connectivity."""
    api_key = os.environ.get("BINANCE_API_KEY", "")
    secret_key = os.environ.get("BINANCE_SECRET_KEY", "")
    if not api_key or not secret_key:
        warn("Binance keys not set - skipping")
        return True
    try:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.binance.com/api/v3/ping", timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    ok("Binance API (public ping)")
                    return True
                fail("Binance API", f"HTTP {resp.status}")
                return False
    except Exception as exc:
        fail("Binance API", str(exc))
        return False


def check_fred() -> bool:
    """Test FRED API connectivity."""
    api_key = os.environ.get("FRED_API_KEY", "")
    if not api_key:
        warn("FRED_API_KEY not set - skipping")
        return True
    try:
        from fredapi import Fred

        fred = Fred(api_key=api_key)
        series = fred.get_series("VIXCLS", limit=1)
        if series is not None:
            ok("FRED API")
            return True
        fail("FRED API", "empty response")
        return False
    except Exception as exc:
        fail("FRED API", str(exc))
        return False


# ── Main ──────────────────────────────────────────────────────────────────────


async def main() -> int:
    """Run all checks and return exit code."""
    print("\n════════════════════════════════════════════")
    print("      APEX Trading System - Preflight")
    print("════════════════════════════════════════════\n")

    results = [
        check_env(),
        check_redis(),
        check_zmq_ports(),
        check_alpaca(),
        await check_binance(),
        check_fred(),
    ]

    total = len(results)
    passed = sum(results)
    failed = total - passed

    print(f"\n{'═' * 44}")
    print(f"  Result: {passed}/{total} checks passed, {failed} failed")
    print(f"{'═' * 44}\n")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
