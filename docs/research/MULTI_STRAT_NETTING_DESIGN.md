# Multi-Strategy Netting + Sub-Book Design — Research Companion

> Companion document to [ADR-0012 — Multi-Strategy Netting and Sub-Book Architecture](../adr/ADR-0012-multi-strategy-netting-and-sub-books.md).
>
> ADR-0012 is the binding architectural contract. This document expands the worked examples, Redis key layout tables, Python interface sketches, edge cases, and alternative-analysis detail that would bloat the ADR itself. When in doubt, ADR-0012 governs.

| Field | Value |
|---|---|
| Status | Draft, 2026-04-21 |
| Author | APEX CIO (Clement Barbier) + Claude Code |
| Related ADRs | [ADR-0012](../adr/ADR-0012-multi-strategy-netting-and-sub-books.md), [ADR-0007](../adr/ADR-0007-strategy-as-microservice.md), [ADR-0008](../adr/ADR-0008-capital-allocator-topology.md), [ADR-0014](../adr/ADR-0014-timescaledb-schema-v2.md), [ADR-0006](../adr/ADR-0006-fail-closed-risk-controls.md) |
| Related Charter sections | §5.5, §5.4, §8.2, §8.1.1, §9.2 |
| Related Roadmap sections | §3 Phase B deliverables |

---

## 1. Executive summary

APEX runs on a pod model by design choice (Charter §3, ratified 2026-04-18). Each strategy is a microservice (ADR-0007); each strategy carries a first-class `strategy_id` on every order-path Pydantic model (Charter §5.5, PR #213); the persistence layer (ADR-0014) already assumes per-strategy attribution exists. The piece missing at the start of Phase B is a documented contract for how per-strategy positions are held in Redis, how they are aggregated to a single broker-facing net position, how broker fills are attributed back to individual strategies, and how aggregate risk limits are enforced without overriding per-strategy intent.

ADR-0012 is that contract. This research document expands it.

The design is the **hybrid Option (d)** from ADR-0012 §8.4:

1. Each strategy has a virtual sub-book in Redis keyed by `strategy_id`.
2. The broker sees only the algebraic sum of sub-books per symbol.
3. Fills are attributed pro-rata to each contributor's signed size at the broker's realized price.
4. Risk Manager STEP 7 `PortfolioExposureMonitor` enforces aggregate limits (gross, net, concentration, correlation-adjusted) on top of sub-book state.
5. Reconciliation between sub-book sum and broker state runs every five minutes.

This is the Millennium / Citadel / Balyasny architectural pattern, specialized to a solo operator running a single broker per asset class.

---

## 2. Full worked example — 3 strategies over 5 time steps

Scenario. Three strategies are live: `har_rv` (HAR-RV realized-volatility strategy), `kelly` (Kelly-sized momentum), and `mean_rev` (mean reversion). All trading `BTCUSDT`. The aggregate book is flat at `t=0`. Portfolio capital is $1,000,000 with allocator-assigned weights `har_rv=0.40`, `kelly=0.35`, `mean_rev=0.25`.

### 2.1 t = 0 — starting state

All sub-books flat. No broker position. No pending orders.

Redis state:

```
subbook:har_rv:*        (empty)
subbook:kelly:*         (empty)
subbook:mean_rev:*      (empty)
portfolio:allocation:har_rv    "0.40"
portfolio:allocation:kelly     "0.35"
portfolio:allocation:mean_rev  "0.25"
portfolio:capital              "1000000"
```

Broker state:

```
position(BTCUSDT) = 0
```

### 2.2 t = 1 — first candidate batch

`har_rv` publishes `OrderCandidate(symbol=BTCUSDT, direction=LONG, size=0.5, entry=50_000)`.
`kelly` flat. `mean_rev` flat.

STEP 0-6 of the VETO chain pass. STEP 7 reads the proposed sub-book deltas: `{har_rv: +0.5, kelly: 0, mean_rev: 0}` → aggregate change `+0.5 BTC`. With price $50,000 and gross-limit 4.0× capital, net-limit 1.5× capital, this is well inside limits. Approved.

Netting engine receives a single `ApprovedOrder` for `har_rv`:

```
net_delta(BTCUSDT) = +0.5
direction = LONG
size = 0.5
contributors = [{strategy_id: "har_rv", signed_size: "+0.5"}]
```

Broker fills `LONG 0.5 BTCUSDT` at $50,000. Attribution:

```
subbook:har_rv:position:BTCUSDT           "+0.5"
subbook:har_rv:cost_basis:BTCUSDT         "+25000"   (0.5 * 50000)
subbook:har_rv:cash                       (deployed: 25000 at risk)
```

Broker state:

```
position(BTCUSDT) = +0.5
```

Sum-of-subbooks invariant holds: `Σ subbook[sid].position(BTCUSDT) = +0.5 = broker`.

### 2.3 t = 2 — contradictory candidate enters

BTCUSDT trades at $50,500 (mid). `har_rv` flat (no new candidate). `kelly` publishes `OrderCandidate(symbol=BTCUSDT, direction=SHORT, size=0.3)`. `mean_rev` publishes `OrderCandidate(symbol=BTCUSDT, direction=SHORT, size=0.2)`.

Sub-book proposed deltas:

```
har_rv:   no change         → position stays +0.5
kelly:    -0.3 incremental  → position becomes -0.3
mean_rev: -0.2 incremental  → position becomes -0.2
```

Aggregate proposed position: `0.5 - 0.3 - 0.2 = 0.0`. STEP 7 approves (aggregate flat, all per-strategy checks pass).

Netting engine:

```
net_delta(BTCUSDT) = 0 - 0.5 = -0.5   # broker currently +0.5, target 0.0
direction = SHORT
size = 0.5
contributors = [{kelly, -0.3}, {mean_rev, -0.2}]
```

Broker fills `SHORT 0.5 BTCUSDT` at $50,500. Attribution per §D4.1:

```
subbook:kelly:position:BTCUSDT            "-0.3"
subbook:kelly:cost_basis:BTCUSDT          "-15150"   (-0.3 * 50500)

subbook:mean_rev:position:BTCUSDT         "-0.2"
subbook:mean_rev:cost_basis:BTCUSDT       "-10100"   (-0.2 * 50500)
```

`har_rv`'s sub-book is unchanged (no candidate). It is still LONG 0.5 with cost basis $25,000. But its mark-to-market at $50,500 is `0.5 * (50_500 - 50_000) = +$250` — a profit.

Broker state:

```
position(BTCUSDT) = +0.5 - 0.5 = 0.0    # broker is flat
```

Sum-of-subbooks invariant: `+0.5 - 0.3 - 0.2 = 0.0 = broker`. ✓

**Critical observation.** The broker's book is flat. No broker-facing trade was generated by `har_rv` at `t=2`. But `har_rv`'s sub-book continues to show an open long LONG 0.5 position with a $250 unrealized P&L. This is the attribution mechanic at work — `har_rv`'s thesis ("BTC is going up") remains expressed on its virtual sub-book, and its P&L reflects that thesis cleanly, even while the broker's book shows no exposure because the other two strategies shorted out the position.

If we did not maintain sub-books, `har_rv`'s +$250 of attributable P&L would be invisible; it would be rolled into a single aggregate number that also absorbs `kelly` and `mean_rev`'s losses or gains. Per-strategy Sharpe becomes meaningless. Charter §8.1.1 per-strategy soft breakers cannot act on `har_rv`'s individual drawdown because it is no longer observable.

### 2.4 t = 3 — partial fill of a netted order

BTCUSDT trades at $50,800. All three strategies publish new candidates:

- `har_rv` `OrderCandidate(direction=LONG, size=0.4)` — scaling into its thesis
- `kelly` `OrderCandidate(direction=SHORT, size=0.6)` — doubling down on short
- `mean_rev` `OrderCandidate(direction=LONG, size=0.1)` — mean-reverting signal flipped

Sub-book proposed deltas and resulting positions:

```
har_rv:   +0.4 incremental  → position +0.5 + 0.4 = +0.9
kelly:    -0.6 incremental  → position -0.3 - 0.6 = -0.9
mean_rev: +0.1 incremental  → position -0.2 + 0.1 = -0.1
```

Aggregate proposed position: `+0.9 - 0.9 - 0.1 = -0.1`.

Netting engine:

```
net_delta(BTCUSDT) = -0.1 - 0.0 = -0.1     # broker 0, target -0.1
direction = SHORT
size = 0.1
contributors = [{har_rv, +0.4}, {kelly, -0.6}, {mean_rev, +0.1}]
```

But: the broker fills **only 50% of the 0.1 BTC** at $50,800, pending further liquidity. This is a partial fill with `f = 0.5`.

Attribution per §D4.2 — uniform pro-rata on the filled fraction:

```
attributed_size(har_rv)    = f * +0.4  = +0.20   at $50,800
attributed_size(kelly)     = f * -0.6  = -0.30   at $50,800
attributed_size(mean_rev)  = f * +0.1  = +0.05   at $50,800

sum of attributed_sizes    = +0.20 - 0.30 + 0.05 = -0.05
broker filled             = -0.05                                   ✓
```

Post-attribution sub-book positions:

```
subbook:har_rv:position:BTCUSDT    = +0.5 + 0.20 = +0.70
subbook:kelly:position:BTCUSDT     = -0.3 - 0.30 = -0.60
subbook:mean_rev:position:BTCUSDT  = -0.2 + 0.05 = -0.15
```

Sum: `+0.70 - 0.60 - 0.15 = -0.05 = broker`. ✓

Pending state (the unfilled 50%):

```
subbook:har_rv:pending:order_XYZ    = {remaining_size: "+0.20", submitted_ms: ...}
subbook:kelly:pending:order_XYZ     = {remaining_size: "-0.30", submitted_ms: ...}
subbook:mean_rev:pending:order_XYZ  = {remaining_size: "+0.05", submitted_ms: ...}
```

These are the shares of the unfilled portion that would attribute back to each strategy if the remaining 0.05 BTC fills.

### 2.5 t = 4 — cancel race

BTCUSDT trades at $51,000. The pending order from `t=3` is still alive in the market. Meanwhile, `kelly`'s strategy microservice decides (based on its own thesis update) to **cancel its participation** in that pending order. It publishes a `CancelOrder` for its `order_XYZ` leg.

This is the cancel race of ADR-0012 §5.3. Per the design:

1. `kelly`'s sub-book pending key is deleted: `subbook:kelly:pending:order_XYZ → (deleted)`.
2. The netting engine recomputes the broker target: `har_rv` still wants the remaining `+0.20` portion, `mean_rev` still wants `+0.05`; `kelly` wants none.
3. New proposed net delta = `+0.20 + 0.05 = +0.25` additional beyond current broker position of `-0.05`.
4. But the broker still has an open SHORT order for the unfilled 0.05 BTC at $50,800 from `t=3`. Two paths:
   - **(A) Cancel the pending broker order; submit a new net order** for `+0.25 - 0.0 = +0.25` from current broker state `-0.05` back to target `har_rv(+0.20) + mean_rev(+0.05) = +0.25`, meaning a LONG 0.30 order to flip from `-0.05` to `+0.25`.
   - **(B) Let the pending SHORT finish; then place a correcting LONG**.

Path (A) is chosen for latency: one broker round-trip, clean state. The original `order_XYZ` is cancelled; a new netted order `order_ABC` is submitted with `contributors = [{har_rv, +0.20}, {mean_rev, +0.05}, {(close pending), -0.05}]` combining the cancel-rollback with the new intents. Size = `+0.30`, direction = `LONG`.

Broker fills `LONG 0.30 BTCUSDT` at $51,000. Attribution (ignoring the close-pending leg, which is just reversing `kelly`'s unfilled portion):

```
attributed_size(har_rv)    = +0.20 at $51,000
attributed_size(mean_rev)  = +0.05 at $51,000
```

(The close-pending cancel-rollback has no attributed position; it simply restores the broker net to what it would have been had `kelly`'s pending not existed.)

Post-t=4 sub-book state:

```
subbook:har_rv:position:BTCUSDT    = +0.70 + 0.20 = +0.90
subbook:kelly:position:BTCUSDT     = -0.60          (unchanged)
subbook:mean_rev:position:BTCUSDT  = -0.15 + 0.05 = -0.10
```

Sum: `+0.90 - 0.60 - 0.10 = +0.20`. Broker state after the flip: `-0.05 + 0.30 = +0.25 - 0.05 = +0.20`... actually let's recompute: broker was `-0.05` from `t=3` partial fill, plus the `+0.30` fill at `t=4` = `+0.25`. But sum-of-sub-books = `+0.20`. That is a `0.05` discrepancy caused by the book-keeping of the cancelled pending.

**This is the exact failure mode §5.3 warns about** and the reason the ADR specifies that the broker-facing net is **recomputed on the next cycle** rather than patched in-flight. On the next cycle, the netting engine sees `sum_subbook = +0.20` vs `broker = +0.25` and emits a corrective `SHORT 0.05` that takes the broker back to `+0.20`. Reconciliation invariant restored.

This is why §D9 runs a five-minute drift check: occasional small drifts from in-flight cancels are normal; persistent drifts indicate a bug.

### 2.6 t = 5 — `har_rv` takes profit; position closes

BTCUSDT rallies to $52,000. `har_rv` publishes `OrderCandidate(direction=SHORT, size=0.9, exit_reason=take_profit)` to close its entire long position. `kelly` and `mean_rev` flat (no new candidates).

Netting engine:

```
sub-book positions before:      har_rv +0.90, kelly -0.60, mean_rev -0.10, sum +0.20
har_rv proposed delta:          -0.90
sub-book positions after:       har_rv  0.00, kelly -0.60, mean_rev -0.10, sum -0.70
current broker:                 +0.20 (after t=4 reconciliation)
net_delta to broker:            -0.70 - (+0.20) = -0.90
direction:                      SHORT
size:                           0.90
contributors:                   [{har_rv, -0.90}]
```

Broker fills `SHORT 0.9 BTCUSDT` at $52,000. Attribution:

```
subbook:har_rv:position:BTCUSDT   = +0.90 - 0.90 = 0.00    # flat!
subbook:har_rv:cost_basis:BTCUSDT = compute realized PnL:
    entries: 0.5 @ 50,000 + 0.20 @ 50,800 + 0.20 @ 51,000
    weighted avg entry = (0.5*50000 + 0.20*50800 + 0.20*51000) / 0.90
                       = (25000 + 10160 + 10200) / 0.90 = 45360 / 0.90 = 50,400
    realized_pnl = 0.90 * (52,000 - 50,400) = 0.90 * 1,600 = +1,440
```

Sub-book update:

```
subbook:har_rv:realized_pnl:daily  += +1,440
subbook:har_rv:position:BTCUSDT     = 0         (flat → can be deleted)
subbook:har_rv:cost_basis:BTCUSDT   = 0         (flat → can be deleted)
```

A `TradeRecord` is written to `apex_trade_records` with `strategy_id="har_rv"`, `realized_pnl=1440`, full entry/exit timestamps and prices. The feedback loop picks this up and updates `kelly:har_rv:BTCUSDT` win-rate / avg-RR statistics.

Broker state after `t=5`:

```
position(BTCUSDT) = +0.20 - 0.90 = -0.70
```

Sum of sub-books: `0 - 0.60 - 0.10 = -0.70 = broker`. ✓

### 2.7 Cumulative attribution summary across t=0 through t=5

| Strategy | Realized PnL | Open position | Open unrealized PnL (at $52,000) |
|---|---|---|---|
| `har_rv` | +$1,440 | flat | 0 |
| `kelly` | 0 | -0.60 | `-0.60 * (52,000 - 50,367)` *(avg short entry computed from t=2 and t=3)* ≈ `-$980` |
| `mean_rev` | 0 | -0.10 | `-0.10 * (52,000 - 50,750)` ≈ `-$125` |

Each strategy has a clean attribution trail. `har_rv` earned its +$1,440 from its long thesis; `kelly` and `mean_rev` are sitting on unrealized losses from their short bets in a rallying market. None of these numbers would be separable under Option (a) naïve netting.

**The feedback loop now has three independent return series.** It can compute per-strategy Sharpe, win rate, drawdown. The allocator (ADR-0008) uses those per-strategy numbers to rebalance capital next week. The per-strategy soft circuit breakers (Charter §8.1.1) can fire on `kelly`'s short-side drawdown without affecting `har_rv` or `mean_rev`. The platform is functioning as a multi-strat pod shop, not as a single blended book.

---

## 3. Redis key layout — populated for the 3-strategy scenario at t = 5

Below is the Redis state at the end of the worked example. Strings are shown with their `Decimal` value; HASHes are shown as field → value.

### 3.1 Per-strategy sub-book keys

#### `har_rv` (flat)

| Key | Type | Value |
|---|---|---|
| `subbook:har_rv:position:BTCUSDT` | STRING | `"0"` (or deleted when flat) |
| `subbook:har_rv:cost_basis:BTCUSDT` | STRING | `"0"` (or deleted when flat) |
| `subbook:har_rv:cash` | STRING | `"400000"` (40% allocation, fully available since flat) |
| `subbook:har_rv:realized_pnl:daily` | STRING | `"1440.00"` |
| `subbook:har_rv:unrealized_pnl` | STRING | `"0"` |
| `subbook:har_rv:last_reconcile_ms` | STRING | `"1745256300000"` (example UTC ms) |

No pending orders (order closed at `t=5`).

#### `kelly` (short 0.60 BTC)

| Key | Type | Value |
|---|---|---|
| `subbook:kelly:position:BTCUSDT` | STRING | `"-0.60"` |
| `subbook:kelly:cost_basis:BTCUSDT` | STRING | `"-30200"` *(weighted average short entry)* |
| `subbook:kelly:cash` | STRING | `"318800"` (350k alloc minus 30.2k cost basis at risk) |
| `subbook:kelly:realized_pnl:daily` | STRING | `"0"` |
| `subbook:kelly:unrealized_pnl` | STRING | `"-980.00"` |
| `subbook:kelly:last_reconcile_ms` | STRING | `"1745256300000"` |

No pending orders (all fills completed by t=4).

#### `mean_rev` (short 0.10 BTC)

| Key | Type | Value |
|---|---|---|
| `subbook:mean_rev:position:BTCUSDT` | STRING | `"-0.10"` |
| `subbook:mean_rev:cost_basis:BTCUSDT` | STRING | `"-5075"` |
| `subbook:mean_rev:cash` | STRING | `"244925"` (250k alloc minus 5.075k cost basis at risk) |
| `subbook:mean_rev:realized_pnl:daily` | STRING | `"0"` |
| `subbook:mean_rev:unrealized_pnl` | STRING | `"-125.00"` |
| `subbook:mean_rev:last_reconcile_ms` | STRING | `"1745256300000"` |

### 3.2 Global keys (unchanged by this ADR)

| Key | Type | Value | Owner |
|---|---|---|---|
| `portfolio:capital` | STRING | `"1000000"` | allocator (writer), risk manager (reader) |
| `portfolio:allocation:har_rv` | STRING | `"0.40"` | allocator |
| `portfolio:allocation:kelly` | STRING | `"0.35"` | allocator |
| `portfolio:allocation:mean_rev` | STRING | `"0.25"` | allocator |
| `risk:heartbeat` | STRING | `<ISO timestamp>` | risk manager (ADR-0006) |
| `risk:circuit_breaker:state` | STRING | `"closed"` | risk manager |
| `correlation:matrix` | HASH | `{BTCUSDT-ETHUSDT: "0.82", ...}` | quant analytics |

### 3.3 Key ownership matrix

| Key prefix | Writer | Readers |
|---|---|---|
| `subbook:*:position:*` | `SubBookAttributor` (from `order.filled`) | `PortfolioExposureMonitor`, `ReconciliationMonitor`, dashboards |
| `subbook:*:cost_basis:*` | `SubBookAttributor` | feedback loop, dashboards |
| `subbook:*:cash` | `SubBookAttributor` + allocator on rebalance | `PerStrategyExposureGuard` (STEP 6) |
| `subbook:*:pending:*` | `NettingEngine` on submit, `SubBookAttributor` on fill/cancel | `ReconciliationMonitor`, dashboards |
| `subbook:*:realized_pnl:daily` | `SubBookAttributor` on closing fills | `StrategyHealthCheck` (STEP 3), dashboards |
| `subbook:*:unrealized_pnl` | mark-to-market loop (every 5s) | dashboards |
| `subbook:*:last_reconcile_ms` | `ReconciliationMonitor` | dashboards |
| `portfolio:allocation:*` | allocator (weekly rebalance) | `PerStrategyExposureGuard`, risk manager, dashboards |

Discipline: a key has exactly one writer service. Cross-service writes go through the message bus (`order.filled`, `portfolio.allocation.updated`), never through shared Redis writes.

### 3.4 TTL and retention

| Key class | TTL | Rationale |
|---|---|---|
| `subbook:*:position:*`, `cost_basis:*`, `cash`, `unrealized_pnl`, `last_reconcile_ms` | none | permanent; must survive service restarts |
| `subbook:*:pending:*` | 24h | pending orders that age out are reconciliation candidates, not deadletters |
| `subbook:*:realized_pnl:daily` | reset at UTC midnight, not TTL | explicit reset keeps observable daily P&L; historical values flow to `apex_strategy_metrics` |
| `apex_pnl_snapshots` persistence | hourly snapshot | ADR-0014 §2.1 |

---

## 4. Python interface sketches (for Phase B Gate 1 implementation)

These are **shape-only** — no implementation is delivered in this document per mission brief. The sketches are `Protocol`-flavored so concrete Gate 1 PRs can implement them with the freedom to compose with existing services.

### 4.1 SubBookManager

```python
from decimal import Decimal
from typing import Protocol

from core.models.order import ApprovedOrder, ExecutedOrder


class SubBookSnapshot:
    """Immutable snapshot of a single strategy's book state.

    Produced by SubBookManager.snapshot(). Consumed by aggregate checks
    and by reconciliation. Snapshots are point-in-time; they do not
    observe live Redis mutations after construction.
    """

    strategy_id: str
    positions: dict[str, Decimal]        # symbol -> signed position
    cost_basis: dict[str, Decimal]       # symbol -> cumulative signed cost
    cash_available: Decimal
    realized_pnl_daily: Decimal
    unrealized_pnl: Decimal
    taken_at_ms: int


class AttributedFill:
    """One strategy's share of a netted fill. Emitted by SubBookManager.apply_fill."""

    strategy_id: str
    symbol: str
    attributed_size: Decimal       # signed (positive = long credit, negative = short debit)
    fill_price: Decimal
    realized_pnl_delta: Decimal    # nonzero only when the fill closes a position
    broker_order_id: str


class ReconcileResult:
    symbol: str
    broker_position: Decimal
    sum_subbook_positions: Decimal
    drift_bps: Decimal
    within_tolerance: bool
    per_strategy_breakdown: dict[str, Decimal]


class SubBookManager(Protocol):
    """Owner of the subbook:* Redis keys.

    All writes go through this interface. Reads are allowed directly from
    the Redis key space via StateStore (the keys are documented and stable),
    but writes go only here to ensure transactional consistency via
    Redis MULTI/EXEC.
    """

    async def get_position(self, strategy_id: str, symbol: str) -> Decimal:
        """Read a single (strategy_id, symbol) position. Zero if absent."""

    async def snapshot(self, strategy_id: str) -> SubBookSnapshot:
        """Point-in-time read of one strategy's full sub-book state."""

    async def snapshot_all(self, strategy_ids: list[str]) -> dict[str, SubBookSnapshot]:
        """Point-in-time read for all strategies. Used by STEP 7 aggregate checks."""

    async def apply_candidate(self, approved: ApprovedOrder) -> None:
        """Record a pending contribution from approved: subbook:{sid}:pending:{order_id}.

        Does NOT mutate position or cost_basis. Those are mutated only by
        apply_fill when the broker confirms.
        """

    async def apply_fill(
        self,
        executed: ExecutedOrder,
        contributors: list[tuple[str, Decimal]],
    ) -> list[AttributedFill]:
        """Apply D4 attribution formula to a netted fill across N contributors.

        Atomic via Redis MULTI/EXEC. On success, returns one AttributedFill
        per contributor, summing to executed.fill_size with correct direction.
        On failure, no partial state is written.
        """

    async def cancel_pending(self, strategy_id: str, order_id: str) -> bool:
        """Remove subbook:{strategy_id}:pending:{order_id}. Returns True if the key existed."""

    async def mark_to_market(self, mark_prices: dict[str, Decimal]) -> None:
        """Refresh subbook:*:unrealized_pnl for all open positions at current prices."""
```

### 4.2 NettingEngine

```python
from collections.abc import Iterable


class BrokerOrder:
    """Intent submitted to the broker API. Not a frozen Pydantic model —
    an internal execution-service type.
    """

    symbol: str
    direction: Direction
    size: Decimal
    order_type: OrderType
    contributors: list[dict]   # [{strategy_id: str, signed_size: str}, ...]
    correlation_id: str         # for matching ExecutedOrder back to this batch


class NettingEngine(Protocol):
    """Groups approved candidates by symbol and emits delta-to-broker orders.

    Stateless. The only dependency is on the current broker position,
    read via BrokerPositionReader.
    """

    async def net(
        self,
        approved: list[ApprovedOrder],
        current_broker_positions: dict[str, Decimal],
        current_subbook_snapshot: dict[str, SubBookSnapshot],
    ) -> Iterable[BrokerOrder]:
        """Per symbol:
            1. Compute the new desired aggregate position = sum_subbook + sum(approved_deltas).
            2. delta = desired - current_broker_position.
            3. If delta == 0, yield nothing.
            4. Otherwise yield a BrokerOrder with contributors preserved.
        """
```

### 4.3 RiskAggregator

```python
class AggregateCheckResult:
    passed: bool
    failure_reason: str | None    # None if passed
    failed_check: str | None      # "gross" / "net" / "symbol_concentration" /
                                  # "strategy_concentration" / "correlation_bucket"
    metric_value: Decimal | None
    metric_limit: Decimal | None


class RiskAggregator(Protocol):
    """STEP 7 PortfolioExposureMonitor extension.

    Evaluates gross, net, concentration, and correlation-adjusted exposure
    against sub-book snapshots + proposed candidate deltas.
    """

    async def check_aggregate(
        self,
        candidates: list[ApprovedOrder],
        subbooks: dict[str, SubBookSnapshot],
        prices: dict[str, Decimal],
        correlation_matrix: dict[tuple[str, str], Decimal],
        limits: "RiskLimits",
    ) -> AggregateCheckResult:
        """Evaluate all five aggregate checks of ADR-0012 §D5.
        Returns the first failure; all checks must pass for approval.
        """
```

### 4.4 SubBookAttributor

```python
class SubBookAttributor(Protocol):
    """Consumer of order.filled; writer of sub-book position/cost_basis/pnl keys."""

    async def on_fill(self, executed: ExecutedOrder) -> list[AttributedFill]:
        """Extract contributor list from executed.metadata (or ZMQ envelope),
        apply D4 pro-rata, write sub-book mutations via SubBookManager.apply_fill.
        Emits one AttributedFill per contributor for downstream observability.
        """

    async def on_rejection(self, blocked: NullOrder) -> None:
        """Clear any subbook:{sid}:pending:{order_id} entries for rejected orders."""
```

### 4.5 ReconciliationMonitor

```python
class ReconciliationMonitor(Protocol):
    """Every 5 minutes: compare sum(subbook positions) vs broker positions per symbol.

    READ-ONLY. No code path mutates sub-book keys from this monitor —
    correcting drifts is an operator decision.
    """

    async def reconcile_symbol(self, symbol: str) -> ReconcileResult: ...

    async def reconcile_all(self) -> list[ReconcileResult]: ...

    async def on_drift(self, result: ReconcileResult) -> None:
        """Publish risk.drift.subbook_vs_broker with severity tiers per §6.3."""
```

All five interfaces are `Protocol`-shaped so Phase B Gate 1 implementations can be composed with existing services (`StateStore`, `BaseService`, the ZMQ publisher). Concrete classes land in a Gate 1 PR tracked under Roadmap §3.

---

## 5. Edge cases worked through

### 5.1 One strategy halts mid-order chain (halt between signal and execution)

`har_rv` publishes a signal at `t = T`. Risk Manager STEP 3 approves it (strategy is `HEALTHY`). The order is sitting in the netting engine's cycle queue at `t = T + 1 ms` when `har_rv`'s per-strategy daily-loss breaker trips (its `realized_pnl:daily < -limit` from a prior trade just closed). Strategy health transitions to `PAUSED_24H`.

Question: does the order still go through?

**Answer**: yes, for in-flight orders already approved. Rationale: the VETO chain is *pre-trade*; once STEP 7 approves, the candidate is committed to the netting cycle. Halting after approval is safe because `StrategyHealthState` is evaluated once per candidate, not continuously. The in-flight order completes; subsequent new candidates from `har_rv` are rejected at STEP 3 on the next cycle.

This matches Charter §8.4's explicit treatment of drawdown-triggered Kelly-adjustment — the adjustment applies to *future* orders, not to in-flight ones. `PAUSED_24H` is the stronger form of the same rule.

### 5.2 Partial fills — the pro-rata is the only invariant choice

Assume contributors `{har_rv: +0.4, kelly: -0.6, mean_rev: +0.1}`, aggregate `-0.1`. Broker fills 50%.

**Uniform pro-rata** (§D4.2): each contributor is attributed `0.5 * their_signed_size`. Sum of attributed = `0.5 * (+0.4) + 0.5 * (-0.6) + 0.5 * (+0.1) = -0.05`. ✓

Alternative attribution rules and why they fail:

- **Time-priority**: first-arriving strategy gets full fill until exhausted. If `har_rv` arrived first (`+0.4`), `kelly` second (`-0.6`), `mean_rev` third (`+0.1`): `har_rv` fully filled, `kelly` partially, `mean_rev` none. But this is not a well-defined "time" in practice — all three candidates arrive within the same cycle and the ordering is a race. A race-winning strategy systematically gets better fills, which breaks the per-strategy Sharpe estimate.
- **Size-priority**: biggest absolute size gets filled first. Same failure — biggest strategy is subsidized at fill time.
- **Fusion-score priority**: strategy with highest `fusion_score` gets filled first. This couples attribution to a score whose magnitude comparison across strategies is not well-defined (each strategy's score is on its own scale).
- **Round-robin**: fill smallest equal shares across contributors in cycles. Works but produces non-deterministic tie-breaks at exhausted-cycle boundaries.

Uniform pro-rata is the only rule that is invariant under arrival order, invariant under strategy-scale differences, and deterministic without tie-breaks. All other options introduce some form of systematic bias that distorts feedback-loop signals.

### 5.3 Cancel race — broker-side perspective

`kelly` cancels a leg while the aggregate broker order is in flight. Two sub-cases:

**Sub-case A**: the broker order has not been filled at the moment of cancel.

- `kelly`'s `subbook:kelly:pending:order_XYZ` is deleted.
- The execution service cancels the broker order (`cancel order_XYZ`).
- On the next cycle, the netting engine recomputes net_delta from the remaining subbook states; a new order `order_ABC` is submitted.
- `har_rv` and `mean_rev` see their intents flow into the new order.

**Sub-case B**: the broker order has partially filled at the moment of cancel.

- The partially-filled portion was already attributed to all three contributors pro-rata at the broker's fill price.
- `kelly`'s cancel applies only to its `pending:order_XYZ` share — i.e., the remaining unfilled 50% of its `-0.30` contribution.
- On cancel acknowledgment, the execution service removes `subbook:kelly:pending:order_XYZ` and issues a broker cancel.
- The remaining pending portions for `har_rv` and `mean_rev` become "orphan" pending — they still exist in `subbook:har_rv:pending:*` and `subbook:mean_rev:pending:*`, but the broker order they referenced is now cancelled.
- On the next netting cycle, the engine sees the orphan pendings and re-submits a new aggregate order for `har_rv + mean_rev`'s unfilled portion only (without `kelly`'s cancelled share).

Either sub-case preserves attribution. In neither case is `kelly` retroactively credited for a fill that occurred before its cancel.

### 5.4 Strategy joins mid-session

`trend_following` passes Gate 3 and is added to the live portfolio at week N. Its Docker container starts; it begins subscribing to panels and publishing `OrderCandidate` with `strategy_id="trend_following"`.

- `subbook:trend_following:*` keys do not exist at container-start time.
- First approved candidate: the netting engine sees a new `strategy_id` in the contributor list; `SubBookAttributor` creates the keys on the first fill.
- `ReconciliationMonitor` picks up the new sub-book automatically (it iterates over `subbook:*` key matches, not a fixed list).
- Allocator: the new strategy is included in the next weekly rebalance per Charter §6.1.3's 60-day linear ramp.

No warm-up is required. No code path needs special-casing for a new strategy.

### 5.5 Strategy leaves (blacklisted by CPCV gate mid-run)

Scenario: during a running week, the feedback-loop / CPCV gate fires on `mean_rev` — its out-of-sample Sharpe has degraded past the decommissioning threshold (Charter §9.2 rule #4 or #5). The CIO issues a decommission order.

Steps:

1. `mean_rev`'s strategy health transitions to `DECOMMISSIONED` in `strategy_health:mean_rev:state`.
2. STEP 3 rejects all new candidates from `mean_rev`.
3. The decommissioning protocol (Charter §9.2, Playbook §10) requires open positions to be closed. A controlled close order flows: `OrderCandidate(symbol=BTCUSDT, direction=LONG, size=0.10, strategy_id="mean_rev", exit_reason="decommission_close")` — wait, this is actually a STEP 3 rejection target. The Charter has a specific exemption for close-only orders from decommissioning strategies: they bypass STEP 3 and go only through STEPS 0-2, 5, 7. Implementation is a per-candidate `exit_reason="decommission_close"` flag recognized by `StrategyHealthCheck`.
4. The close order flows through netting (even if `mean_rev` is the sole contributor), fills, and attributes to `mean_rev`'s sub-book.
5. Once `mean_rev`'s positions are all flat, the sub-book's `realized_pnl:daily` is flushed to `apex_trade_records` and `apex_strategy_metrics`, and the Redis keys are archived (exported to file and deleted).
6. `mean_rev`'s Docker container is stopped.
7. The allocator redistributes `mean_rev`'s 25% capital to `har_rv` and `kelly` proportionally at the next weekly rebalance.

The exemption for close-only orders is essential: without it, a decommissioned strategy's positions would be stranded, causing a reconciliation drift that never clears.

### 5.6 Broker split fill across venues (deferred to Phase C)

Currently APEX uses a single venue per asset class (Alpaca for equities, Binance for crypto). A single broker order produces a single stream of fills. The D4 formula extends trivially per §5.8 of ADR-0012 when venues multiply.

Open design questions for Phase C:

- Does each venue fill produce its own `ExecutedOrder` message, or are they aggregated?
- If separate, each contributes its own pro-rata attribution at its own price.
- If aggregated, the execution service computes a weighted average fill price across venues and applies D4 once.
- Preferred choice: separate per-venue `ExecutedOrder` messages — preserves the auditable fill-level detail required for best-execution analysis.

Not in scope for this ADR.

### 5.7 Mark-to-market during volatile moves

Between fills, the sub-book's `unrealized_pnl` reflects the strategy's accounting P&L. If BTCUSDT gaps from $50,000 to $47,000 in one tick:

- The mark-to-market loop refreshes `subbook:har_rv:unrealized_pnl` at the new mark.
- Per-strategy soft breakers (Charter §8.1.1 drawdown triggers) are evaluated against `realized_pnl:daily + unrealized_pnl`.
- A strategy may enter `DD_KELLY_ADJUSTED` or `PAUSED_24H` on unrealized drawdown alone, even without any new fills.

This matches Charter §8.4 worked example where an 8.5% unrealized + realized drawdown triggers Kelly halving.

### 5.8 Multiple fills of the same broker order (chunked fills)

A single broker order may produce multiple `ExecutedOrder` messages as it fills in chunks at potentially different prices (common for limit orders or for market-on-close orders). Each chunk fill triggers an independent D4.2 pro-rata attribution at that chunk's fill price.

The contributor list is the same across all chunks (it was fixed at submission time). Each chunk's `f` is the chunk's size divided by the original aggregate order size; the sum of `f` across all chunks sums to `1.0` at full completion.

---

## 6. Comparison to rejected alternatives

ADR-0012 §8 summarized the rejection rationale. This section expands with concrete failure examples for each alternative.

### 6.1 Option (a) — pure netting pre-broker, no sub-books

**Concrete failure**: at `t=2` in the worked example, the broker's book is flat. A single-line "positions" table in Redis would show `BTCUSDT = 0`. A question at `t=5` like "what was `har_rv`'s P&L contribution?" can only be reconstructed from the `OrderCandidate` / `ExecutedOrder` history — not from a position-state read. If any `OrderCandidate` is lost in transit (ZMQ hiccup, service restart before the feedback-loop persists it), the reconstruction is incomplete.

**Why sub-books fix it**: the sub-book is the *position state* at a per-strategy grain. Reconstruction is not required; the state is the answer.

### 6.2 Option (b) — sub-books without aggregate veto

**Concrete failure**: three strategies each hold LONG 5 BTC in BTCUSDT (within each strategy's per-strategy exposure guard of LONG ≤ 5 BTC per symbol). Aggregate: LONG 15 BTC. If portfolio gross limit is 10 BTC (equivalent to 100% of capital), this is in violation; but no per-strategy check catches it. The Risk Manager does not see the aggregate.

**Why aggregate veto fixes it**: STEP 7 reads the sub-book snapshot, computes `Σ = 15 BTC`, compares to `portfolio_gross_limit = 10 BTC`, rejects.

### 6.3 Option (c) — aggregate veto with priority queue but no sub-books

**Concrete failure**: two candidates arrive within the same cycle: `A = {sid: har_rv, LONG 5 BTC}` and `B = {sid: kelly, LONG 5 BTC}`. The aggregate limit is 5 BTC. The priority queue admits `A` and rejects `B`.

But: if the order of arrival were reversed, the queue would admit `B` and reject `A`. Over many cycles, each strategy's admission rate depends on its arrival-order advantage, which is a function of Python scheduler latency — not edge.

When the feedback loop computes `har_rv`'s Sharpe, it is measuring `har_rv`'s edge *combined with* `har_rv`'s arrival-order luck. This invalidates the allocator's input signal. The allocator, acting on corrupted Sharpe, makes systematically wrong capital allocations.

Sub-books + aggregate veto + uniform pro-rata partial fills (Option d) does not have this failure mode: each strategy's fill share is the same regardless of arrival order within the cycle.

### 6.4 Option (d) — the chosen hybrid

**Why it wins**: it is the only option that satisfies all four design requirements simultaneously:

1. Per-strategy P&L attribution (failure of (a), (c)).
2. Aggregate risk enforcement (failure of (b)).
3. Invariance under arrival order within a cycle (failure of (c)).
4. Matches the proven industry pod model (failure of (a), (b), (c) against public evidence from Millennium, Citadel, Balyasny).

The cost — Redis key management for N strategies — is linear in N and absorbable by the existing per-strategy Redis partitioning scheme of ADR-0007 §D8.

### 6.5 A fifth option considered and rejected — per-strategy brokers

**Description**: each strategy has its own broker sub-account; positions are independent at the broker level; no netting at all.

**Why rejected**:

- APEX uses Alpaca (equities) and Binance (crypto); neither natively supports per-sub-account brokerage at the operator's tier without significant operational overhead (margin isolation across sub-accounts is manual at retail-pro level).
- The primary benefit — physically separated books — is achieved architecturally by sub-books at a fraction of the operational cost.
- Double spread cost becomes the default instead of an edge case: two strategies that perfectly cancel at the intent level still incur two broker round-trips.
- Aggregate risk enforcement becomes harder: each sub-account reports separately; the platform would need to merge the reports, essentially reinventing the sub-book abstraction on the broker side.

Pod shops at scale (Millennium, Citadel) do run physically separate brokerage accounts per PM — but they also deploy capital at scales where the operational cost of sub-account management is negligible relative to AUM, and where netting across PMs is prohibited for regulatory (Chinese Wall) reasons. Neither applies at APEX's scale.

---

## 7. Open design questions (explicitly out of scope for ADR-0012)

Listed for Phase C consideration; not binding on Phase B.

### 7.1 Attribution price choice for perfectly-cancelling cycles

When two strategies' candidates perfectly cancel (e.g., `har_rv: LONG 0.5`, `kelly: SHORT 0.5`) within a single cycle, no broker round-trip occurs. But each strategy's sub-book must still record its intent at *some* price so the per-strategy Sharpe reflects its intent.

**Options**:

- (i) Use the current mid-price at the cycle tick.
- (ii) Use the previous broker fill price on the symbol.
- (iii) Record the intent but mark it as "virtual" and exclude from Sharpe until a real round-trip fills.

**Recommendation**: (i) mid-price — simple, deterministic, aligned with standard mark-to-market conventions. To be ratified in a Gate 2 follow-up if the issue becomes material. For Phase B's single live strategy plus LegacyConfluenceStrategy, this case cannot occur (N=1 effective).

### 7.2 Retroactive attribution on delayed fill events

A broker fill that arrives `> 1 second` after submission indicates a venue latency issue. If the sub-book state has moved on in the interim (other strategies have traded the same symbol), should the delayed fill attribute at the broker's reported price (which may no longer match the current market) or at the current mark?

**Recommendation**: attribute at the broker's reported fill price (always — this is the D4 contract). Drift between that price and current mark manifests as unrealized P&L, not as an attribution correction.

### 7.3 Negative-cash sub-books

A strategy's sub-book `cash` could go negative if its deployed capital exceeds its allocator assignment (possible transiently between weekly rebalances as positions move against it). Should the allocator enforce a hard floor, or tolerate temporary overrun?

**Recommendation**: STEP 6 `PerStrategyExposureGuard` rejects new candidates when `cash + new_at_risk < 0`. Existing positions are not unwound. Temporary overrun is tolerated until the next rebalance.

### 7.4 Sub-book vs broker reconciliation during a broker outage

If the broker API is unresponsive, `ReconciliationMonitor` cannot read broker positions. Does it assume no drift, or does it escalate?

**Recommendation**: after 2 consecutive failed reads, publish `risk.reconcile.broker_unreachable` and (per ADR-0006) trigger DEGRADED state. Once broker reachability resumes, run a full reconcile before clearing DEGRADED.

### 7.5 Cross-asset sub-book aggregation

For a strategy trading BTCUSDT and ETHUSDT, is its "sub-book" a single logical book (one `strategy_id`, N symbols) or N sub-books (one per `(strategy_id, symbol)`)?

**Current design**: a single logical sub-book per `strategy_id`, spanning all symbols. Redis keys are partitioned by `(strategy_id, symbol)` only for `position` and `cost_basis`; the scalar cash/PnL keys are per-strategy not per-symbol. This matches the Charter §5.5 wording. No change needed.

### 7.6 Interaction with future options strategies

If a future strategy trades options, the D4 pro-rata attribution formula generalizes to contract-level attribution. But aggregate risk checks (gross, net, concentration) must be computed in delta-adjusted or notional-adjusted space, not contract counts. ADR-0012 does not address this; a future ADR will.

---

## 8. Performance considerations

### 8.1 Latency budget for the netting + aggregate-check cycle

Target: ≤ 5 ms p99 for the full cycle, measured from `order.approved` publish to `BrokerOrder` emit.

Decomposition:

- **Sub-book snapshot read** (N strategies × M symbols): `O(N*M)` Redis reads. At `N=6`, `M=50`, that is 300 Redis reads. Using `MGET` batching, this is ≤ 1 ms on a warm LAN connection.
- **Aggregate checks** (§D5.1–D5.5): pure Python arithmetic over the snapshot. ≤ 0.5 ms.
- **Netting computation** (§D7): one `defaultdict` group-by over approved list, one sum per symbol, one `yield BrokerOrder`. ≤ 0.2 ms per symbol.
- **ZMQ emit**: ≤ 0.1 ms per message.

Total budget: 2 ms at N=6. Headroom for N up to ~30 strategies before breaching 5 ms.

### 8.2 Throughput

In steady state, each approved candidate triggers one netting cycle. At the legacy single-strategy pipeline's cadence (one candidate per ~5 seconds), throughput is trivially bounded. Phase C stress testing will revisit.

### 8.3 Memory

Each sub-book is ≤ 1 KB per symbol in Redis (7 keys × 100 bytes avg). At `N=6` strategies × `M=50` symbols, total Redis memory for sub-books ≤ 300 KB. Negligible.

### 8.4 TimescaleDB write volume

Per ADR-0014 §2.1, `apex_pnl_snapshots` writes hourly per strategy × symbol. At `N=6`, `M=50`, that is 300 rows/hour = ~2.6M rows/year. Well within TimescaleDB's comfortable throughput band.

---

## 9. Testing plan summary

Per ADR-0012 §9.1, the Phase B Gate 2 PR delivers:

1. **Attribution-closure property test** using `hypothesis`: for random contributor lists with random signed sizes, uniform `f ∈ [0, 1]`, and random fill prices, `Σ_k attributed_size_k` matches `f * broker_fill_size` within `Decimal` precision (no float rounding).
2. **Sub-book consistency test** against a simulated broker: replay a 30-day fixture tick stream through a 3-strategy simulated pipeline; assert that at every sampled timestamp, `Σ_sid subbook[sid].position(sym) == simulated_broker_position(sym)`.
3. **Netting-zero-cost test**: candidates `[{A: +X}, {B: -X}]` produce `net_to_broker(...) == []`. Sub-books record the intents at the attribution-reference mid price.
4. **Partial-fill test**: for `f in [0.1, 0.3, 0.5, 0.7, 0.99]`, the sum of per-strategy credits equals `f * broker_fill_size` with correct direction sign per contributor.
5. **Cancel race test**: cancel a contribution while a partial fill is in flight; verify that (a) the canceled contributor's pending key is removed, (b) the remaining contributors' pending keys remain, (c) the next netting cycle emits a corrective delta.
6. **Decommission close test**: set a strategy to `DECOMMISSIONED`; a close-only order with `exit_reason="decommission_close"` flows through the VETO chain (bypassing STEP 3) and unwinds the sub-book to flat.
7. **Reconciliation drift test**: inject a broker-side position that differs from sub-book sum; verify that `ReconciliationMonitor` detects the drift and publishes `risk.drift.subbook_vs_broker`; verify that `ReconciliationMonitor` does *not* write to sub-book keys (the read-only invariant).

Integration tests run against `fakeredis` for unit-level sub-book behavior, and against a real Redis instance for end-to-end behavior including ZMQ round-trips.

---

## 10. Migration and rollout

### 10.1 Phase B Gate 1 — sub-book primitives, single strategy

Scope:

- Introduce `SubBookManager` and `subbook:{default}:*` keys in Redis.
- `LegacyConfluenceStrategy` (ADR-0007 §D4) writes to its own sub-book on every approved order.
- `ReconciliationMonitor` in read-only observer mode (alerts only).
- No netting engine yet (single strategy → no netting needed).
- Dual-read pattern extending the existing PR-#210 / PR-#214 fallbacks: aggregate-check reads use `subbook:default:*` if present, fall back to `portfolio:capital` / `pnl:daily`.

Exit: `LegacyConfluenceStrategy` trades for 1 week in paper; its sub-book state exactly matches the broker state (within reconciliation tolerance) for 100% of 5-minute windows.

### 10.2 Phase B Gate 2 — netting engine online, 2 strategies

Scope:

- `NettingEngine` implemented in `services/execution/`.
- `SubBookAttributor` wired to `order.filled`.
- STEP 7 `PortfolioExposureMonitor` extended with all five aggregate checks.
- STEP 3 `StrategyHealthCheck` extended with per-strategy daily-loss circuit breaker.
- `crypto_momentum` joins `default` in live paper.
- All CI tests pass per §9.

Exit: 1 week of 2-strategy paper trading with daily reconciliation drift < 0.01% on 100% of 5-minute windows.

### 10.3 Phase B Gate 3 — live small size

Scope:

- Correlation-adjusted exposure check becomes enforcing (previously observer).
- `strategy_daily_loss_limit` tuned per-strategy from paper-trade data.
- 2-3 strategies live with small capital (≤ 10% of full allocation).

Exit: 2 weeks of live trading with no unexplained reconciliation drifts, no attribution anomalies, no per-strategy breaker false positives.

### 10.4 Phase C — full multi-strat

Scope:

- 5+ strategies live simultaneously.
- ADR-0013 HRP allocator integrated.
- Correlation matrix feeds both the allocator (ADR-0013) and the aggregate correlation-bucket check (§D5.5).
- Latency profiling; snapshot caching if required.

Exit: full Charter §10 legitimacy — multi-strat portfolio Sharpe > 1.5 over 6 months with at least 3 live strategies.

---

## 11. Interaction with ADR-0013 (capital allocation trajectory)

ADR-0013 (parallel PR, drafted by Terminal 7) specifies the capital allocation trajectory from Phase B (inverse-volatility risk parity) through Phase C (HRP) per Charter §6 and ADR-0008.

Interaction with this ADR (ADR-0012):

- ADR-0013 **writes** `portfolio:allocation:{strategy_id}`. This ADR **reads** it for STEP 6 `PerStrategyExposureGuard` and §D5.4 single-strategy concentration.
- ADR-0013's correlation-matrix estimate feeds §D5.5 correlation-bucket exposure. Consistency: the same correlation matrix is used for allocation and for aggregate veto, ensuring the allocator does not over-allocate a correlation cluster while the risk manager under-limits it.
- ADR-0013's Phase 2 Sharpe overlay depends on per-strategy Sharpe computed by the feedback loop over `apex_trade_records`. This ADR guarantees per-strategy Sharpe is measurable (without sub-books, Sharpe collapses to an aggregate number).

No conflicts. The two ADRs are complementary — ADR-0012 makes per-strategy attribution possible; ADR-0013 uses per-strategy attribution to allocate capital.

---

## 12. Interaction with ADR-0011 (decoded replication validation harness)

ADR-0011 (parallel PR, drafted by Terminal 8) specifies the validation harness for decoded replication of a strategy's backtest against its live paper run.

Interaction with this ADR:

- ADR-0011's harness reads `apex_trade_records` filtered by `strategy_id` to compare live fills against backtest projections. This ADR guarantees those records exist with correct per-strategy attribution.
- If ADR-0012's attribution were ever wrong (e.g., a bug in D4 applied incorrectly), ADR-0011's harness would detect the divergence between live and backtest within one reconciliation cycle.

The two ADRs are mutually reinforcing: ADR-0012 produces per-strategy attribution; ADR-0011 verifies its correctness against independent evidence.

---

## 13. References and further reading

### 13.1 Internal docs

- [ADR-0012 — Multi-Strategy Netting and Sub-Book Architecture](../adr/ADR-0012-multi-strategy-netting-and-sub-books.md) — the binding contract this document expands.
- [ADR-0007 — Strategy as Microservice](../adr/ADR-0007-strategy-as-microservice.md) §D6 (strategy_id first-class), §D8 (per-strategy Redis partitioning), §D9 (independent deployment).
- [ADR-0008 — Capital Allocator Topology](../adr/ADR-0008-capital-allocator-topology.md).
- [ADR-0014 — TimescaleDB Schema v2](../adr/ADR-0014-timescaledb-schema-v2.md).
- [ADR-0006 — Fail-Closed Risk Controls](../adr/ADR-0006-fail-closed-risk-controls.md).
- [APEX Multi-Strat Charter v1.0](../strategy/ALPHA_THESIS_AND_MULTI_STRAT_CHARTER.md) §5.4, §5.5, §8.1, §8.2, §9.2.
- [Lifecycle Playbook v1.0](../strategy/STRATEGY_DEVELOPMENT_LIFECYCLE.md) §8.0 (strategy health states), §10 (decommissioning).
- [Phase 5 v3 Roadmap](../phases/PHASE_5_v3_MULTI_STRAT_ALIGNED_ROADMAP.md) §3 (Phase B deliverables).

### 13.2 Public sources on pod-based architecture (non-proprietary)

The following are public articles cited for pod-model context. No proprietary materials from any named firm were consulted.

- **Millennium / pod structure**:
  - Navnoor Bawa, "Millennium Management's Multi-Strategy Trading Architecture" — [https://navnoorbawa.substack.com/p/millennium-managements-multi-strategy](https://navnoorbawa.substack.com/p/millennium-managements-multi-strategy). Describes pod count (330+), capital per pod ($100M-$200M typical), and drawdown triggers (5% → capital reduction, 7.5% → termination). Maps directly to Charter §8.1.1's per-strategy soft breaker thresholds.
  - Confluence GP, "Millennium's Pod System: How Platform Design Beats Star Portfolio Managers" — [https://www.confluencegp.com/articles-and-news/millennium-s-pod-system-how-platform-design-beats-star-portfolio-managers](https://www.confluencegp.com/articles-and-news/millennium-s-pod-system-how-platform-design-beats-star-portfolio-managers). Platform-first organizational primitive.
  - The Motley Fool, "Millennium Management: Overview, History, and Investments" — [https://www.fool.com/investing/how-to-invest/famous-investors/millennium-management/](https://www.fool.com/investing/how-to-invest/famous-investors/millennium-management/). Background for non-specialist readers.

- **Citadel / Portfolio Construction & Risk Group**:
  - Rupak Ghose, "Citadel is from Mars and Millennium is from Venus" — [https://rupakghose.substack.com/p/citadel-is-from-mars-and-millennium](https://rupakghose.substack.com/p/citadel-is-from-mars-and-millennium). Key passage: Citadel's risk group hedges aggregate exposure (e.g., Nasdaq puts) rather than overriding PM decisions. This is the public-information analogue of APEX's STEP 7 aggregate veto that preserves sub-book intents.
  - Citadel official, "What We Do" — [https://www.citadel.com/what-we-do/](https://www.citadel.com/what-we-do/). Corporate overview; used only for non-technical framing.

- **Balyasny**:
  - Navnoor Bawa, "How Multi-Strategy Funds Generated 10% Returns in 2025: Inside Balyasny's Pod Allocation Model" — [https://navnoorbawa.substack.com/p/how-multi-strategy-funds-generated](https://navnoorbawa.substack.com/p/how-multi-strategy-funds-generated). Pod allocation drivers (Sharpe, factor overlap, regime) match ADR-0008's allocator inputs.

- **Cross-firm comparative**:
  - Navnoor Bawa, "How Millennium, Citadel & Point72 Structure Pods" — [https://navnoorbawa.substack.com/p/how-millennium-citadel-and-point72](https://navnoorbawa.substack.com/p/how-millennium-citadel-and-point72).
  - eFinancialCareers, "Citadel, Millennium, or...? Life at the big multistrategy hedge funds" — [https://www.efinancialcareers.com/news/2023/10/citadel-millennium-hedge-funds](https://www.efinancialcareers.com/news/2023/10/citadel-millennium-hedge-funds).

### 13.3 Academic references

- Maillard, Roncalli & Teiletche (2010). "The Properties of Equally Weighted Risk Contribution Portfolios." *Journal of Portfolio Management* 36, 60–70. Foundational for Charter §6.1 Phase 1 Risk Parity.
- Lo, A. (2002). "The Statistics of Sharpe Ratios." *Financial Analysts Journal* 58, 36–52. Cited by Charter §6.2.5 for why ±20% Sharpe-overlay cap in Phase 2.
- Nygard, M. (2007). *Release It! Design and Deploy Production-Ready Software*. Pragmatic Bookshelf. Isolation and bulkhead patterns — conceptual precedent for pod isolation, cited by ADR-0007 §7.3.

### 13.4 Internal code pointers (reference-only; no changes required by this ADR)

- [`core/models/order.py`](../../core/models/order.py) — five order-path Pydantic models, `strategy_id` propagation via `model_validator(mode="before")` (PR #213).
- [`core/models/signal.py`](../../core/models/signal.py) — `Signal` with `strategy_id`.
- [`core/state.py`](../../core/state.py) — `StateStore` Redis abstraction used by all sub-book readers/writers.
- [`services/risk_manager/portfolio_tracker.py`](../../services/risk_manager/portfolio_tracker.py) — dual-read pattern for `portfolio:capital` (PR #210).
- [`services/risk_manager/pnl_tracker.py`](../../services/risk_manager/pnl_tracker.py) — pre-trade PnL reader citing the Millennium/Citadel pod pattern (PR #214).
- [`services/risk_manager/chain_orchestrator.py`](../../services/risk_manager/chain_orchestrator.py) — seven-step VETO chain; STEP 7 extension point for §D5.
- [`services/risk_manager/exposure_monitor.py`](../../services/risk_manager/exposure_monitor.py) — where the aggregate checks land in Gate 2.
- [`services/execution/service.py`](../../services/execution/service.py) — where the `NettingEngine` lands in Gate 2.
- [`services/fusion_engine/kelly_sizer.py`](../../services/fusion_engine/kelly_sizer.py) — per-strategy Kelly stats reader; reference pattern for dual-read.
- [`db/migrations/001_apex_initial_schema.sql`](../../db/migrations/001_apex_initial_schema.sql) — TimescaleDB schema v2 (ADR-0014); `apex_pnl_snapshots`, `apex_trade_records`, `apex_strategy_metrics` are the persistence layer for sub-book state.

---

**END OF MULTI_STRAT_NETTING_DESIGN.md** — companion to ADR-0012.
