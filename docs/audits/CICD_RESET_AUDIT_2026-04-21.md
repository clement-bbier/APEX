# CI/CD Reset Audit — 2026-04-21

**Author**: Claude Code (infra/cicd-reset)
**Scope**: `.github/workflows/**`, `.github/dependabot.yml`, `pyproject.toml` (coverage only)
**Companion PR**: `infra: modernize CI + disabled CD + Dependabot + coverage audit` on `infra/cicd-reset`

---

## 1. Current workflow inventory

Source: `gh api repos/clement-bbier/APEX/actions/workflows` + `.github/workflows/` listing.

| File | Workflow name | State | Triggers | Jobs |
|---|---|---|---|---|
| `ci.yml` | CI | active | `push {main,develop}`, `pull_request {main,develop}` | `quality`, `rust`, `unit-tests`, `integration-tests`, `backtest-gate` |
| `backtest.yml` | Nightly Backtest Regression | active | `schedule '0 6 * * 1-5'`, `workflow_dispatch` | `backtest` |
| `_disabled_cd.yml` | CD | `disabled_manually` (GitHub API state) + leading-underscore filename convention | `push main`, `workflow_dispatch` | `build-push` |
| `dynamic/copilot-pull-request-reviewer/copilot-pull-request-reviewer` | Copilot code review | active (GitHub-managed dynamic) | `pull_request` events | — |
| `dynamic/copilot-swe-agent/copilot` | Copilot cloud agent | active (GitHub-managed dynamic) | GitHub dispatch | — |

There are no `.github/actions/` composite actions.

### 1.1 Per-job wall-time (last green run: `24717829193`, PR #214)

| Job | Duration | Parallel with |
|---|---|---|
| `quality` | 1m 25s | `rust` |
| `rust` | 31s | `quality` |
| `unit-tests` | 9m 30s | — (needs `quality`, `rust`) |
| `integration-tests` | 2m 25s | — (needs `unit-tests`) |
| `backtest-gate` (MUZZLED) | 1m 12s | — (needs `unit-tests`, runs in parallel with `integration-tests`) |
| **Wall-clock total** | **~13m 30s** | — |

`unit-tests` dominates. It pays a ~4 minute `pip install` tax per run because caching is `cache: pip` on `setup-python` (implicit, keyed on `requirements.txt` hash only — no cross-workflow share).

---

## 2. Branch protection / required checks

`gh api repos/clement-bbier/APEX/branches/main/protection` → **HTTP 404 "Branch not protected"**.

Main is **unprotected**. There are no required status checks enforced at the GitHub level today. CI's job names (`quality`, `rust`, `unit-tests`, `integration-tests`, `backtest-gate`) are the de facto contract but nothing prevents a red-CI merge.

**Implication for this PR**: splitting `ci.yml` into five workflow files is safe — there is no protection rule whose required-check names we would break. The new workflow files still expose jobs named `quality`, `rust`, `unit-tests`, `integration-tests`, `backtest-gate` so that when protection is added later the rule wording is identical to what we'd have set today.

**Recommended follow-up**: after this PR lands, add a branch protection rule on `main` requiring `quality`, `rust`, `unit-tests`, `integration-tests` (NOT `backtest-gate` while muzzled).

---

## 3. Coverage gate status

### 3.1 Current configuration

- CI gate: `.github/workflows/ci.yml` line 94 — `--cov-fail-under=75` passed to `pytest`
- `pyproject.toml [tool.pytest.ini_options]` — no `--cov-fail-under` in `addopts`; the gate is CI-only
- `[tool.coverage.run]` has a long `omit = [...]` list that excludes service entrypoints, ZMQ infra, brokers, MC, geopolitical, and the command_center UI modules

### 3.2 Baseline coverage on main (from CI run `24717829193`)

```
TOTAL  8336 stmts  1349 miss  2018 branch  261 partial  81%
Required test coverage of 75% reached. Total coverage: 81.40%
```

**Gap to 85%**: 3.60 percentage points. About 300 missed statements would need to be covered across ~35 modules.

### 3.3 Modules below 85% (from CI run `24717829193`)

| Module | Coverage | Stmts | Missed | Gap → 85% |
|---|---:|---:|---:|---:|
| `services/data_ingestion/orchestrator/main.py` | 0% | 36 | 36 | +31 stmts |
| `core/service_runner.py` | 0% | 52 | 52 | +44 stmts |
| `services/data_ingestion/alpaca_feed.py` | 0% | 53 | 53 | +45 stmts |
| `services/data_ingestion/binance_feed.py` | 0% | 78 | 78 | +66 stmts |
| `services/data_ingestion/macro_feed.py` | 0% | 85 | 85 | +72 stmts |
| `core/zmq_broker.py` | 0% | 136 | 136 | +116 stmts |
| `services/command_center/pnl_tracker.py` | 14% | 57 | 45 | +41 stmts |
| `services/command_center/health_checker.py` | 33% | 33 | 20 | +17 stmts |
| `services/data_ingestion/orchestrator/connector_factory.py` | 53% | 91 | 42 | +29 stmts |
| `services/macro_intelligence/cb_watcher.py` | 57% | 102 | 42 | +29 stmts |
| `services/data_ingestion/orchestrator/cli.py` | 58% | 131 | 53 | +35 stmts |
| `services/signal_engine/technical.py` | 59% | 190 | 68 | +49 stmts |
| `services/execution/broker_factory.py` | 63% | 49 | 12 | +11 stmts |
| `services/data_ingestion/quality/outlier_check.py` | 65% | 58 | 17 | +12 stmts |
| `core/data/timescale_repository.py` | 65% | 205 | 62 | +41 stmts |
| `services/data_ingestion/serving/deps.py` | 67% | 9 | 3 | +2 stmts |
| `core/logger.py` | 68% | 17 | 5 | +3 stmts |
| `services/data_ingestion/connectors/boj_calendar_scraper.py` | 72% | 85 | 19 | +8 stmts |
| `services/data_ingestion/connectors/ecb_scraper.py` | 72% | 88 | 19 | +9 stmts |
| `services/data_ingestion/connectors/fred_releases.py` | 75% | 84 | 19 | +8 stmts |
| `backtesting/walk_forward.py` | 76% | 200 | 47 | +20 stmts |
| `services/signal_engine/microstructure.py` | 77% | 88 | 16 | +7 stmts |
| `services/data_ingestion/connectors/boj_connector.py` | 77% | 112 | 23 | +7 stmts |
| `services/execution/paper_trader.py` | 78% | 72 | 14 | +6 stmts |
| `services/data_ingestion/quality/checker.py` | 78% | 126 | 19 | +9 stmts |
| `services/data_ingestion/connectors/fomc_scraper.py` | 79% | 121 | 18 | +7 stmts |
| `services/data_ingestion/connectors/ecb_connector.py` | 79% | 134 | 21 | +8 stmts |
| `services/data_ingestion/connectors/simfin_connector.py` | 79% | 142 | 26 | +9 stmts |
| `services/risk_manager/context_loader.py` | 80% | 55 | 10 | +3 stmts |
| `services/data_ingestion/orchestrator/scheduler.py` | 80% | 71 | 12 | +4 stmts |
| `core/models/regime.py` | 82% | 75 | 10 | +2 stmts |
| `services/data_ingestion/connectors/binance_historical.py` | 82% | 210 | 32 | +7 stmts |
| `services/data_ingestion/connectors/edgar_connector.py` | 83% | 158 | 23 | +4 stmts |
| `services/signal_engine/pipeline.py` | 83% | 182 | 22 | +4 stmts |
| `services/data_ingestion/quality/stale_check.py` | 84% | 30 | 4 | +1 stmt |

**121 Python modules** were measured; **35 fall under 85%**. Six of them are at 0% — those are the ZMQ broker, service runners, and feed entrypoints, which deliberately require live brokers/ZMQ and are un-unit-testable today. Either they need integration-level counting, or they should join the `omit` list. They're the dominant drag on total coverage.

**Methodology note**: this audit reads the coverage numbers from the most recent green CI log (run `24717829193`, commit on `phase-A.8/pnl-tracker-risk-manager-pretrade`). A local re-run was attempted but the dev environment (Windows, no venv) is missing `numpy`/`polars`; CI numbers are more authoritative anyway because they reflect the real `[tool.coverage.run] omit` set.

### 3.4 Gate raise — deferred to issue #203

**Verdict: coverage is 81.40% on main, NOT ≥ 85%. The raise does not ship in this PR.**

Recommendation: **(C) push CI modernization now, defer coverage raise to issue #203**. Rationale:

1. Current main is 81.40% — raising to 85% today would make CI red on the next commit.
2. Roadmap §2.2.6 gates the raise on "7 consecutive days of pytest --cov ≥ 85% on main". Neither the 85% figure nor the 7-day stability window is achievable today.
3. The six 0%-coverage modules (zmq_broker, service_runner, three feeds, orchestrator/main) contribute ~440 missed statements. Closing that accounts for the whole 3.6pp gap but needs either (a) integration-level coverage stitched in via `coverage combine`, or (b) those modules moved into the existing `omit` list with justification. Both are their own design decisions, not a ci.yml change.
4. The `[phase-A.13]` issue (#203) already owns the eventual gate raise per Roadmap §2.2.6 — that issue is the right vehicle, not this infrastructure-reset PR.
5. Four other PRs are in flight during this sprint. Shipping `--cov-fail-under=85` now would block every one of them until each lands enough per-module coverage to clear 85%. That's operational risk this PR is not authorized to introduce.

**This PR does NOT modify the `--cov-fail-under` value.** All preparation stays in this document — §3.2 (baseline), §3.3 (per-module gaps), and §10 (the exact one-line diff and activation checklist for issue #203).

---

## 4. Deprecated GitHub Action versions

From the old `ci.yml` (being replaced) and the API logs:

| Usage | Old | Latest stable | Status in new workflows |
|---|---|---|---|
| `actions/checkout` | `@v5` | `@v4` (v5 exists but v4 remains current-stable LTS per docs) | **downgraded to `@v4`** per brief |
| `actions/setup-python` | `@v6` | `@v5` stable, `@v6` preview | **downgraded to `@v5`** per brief |
| `actions/cache` | not explicit (relied on setup-python cache) | `@v4` | **now explicit `@v4`** |
| `actions/upload-artifact` | `@v4` | `@v4` | unchanged |
| `actions/download-artifact` | `@v4` | `@v4` | unchanged |
| `dtolnay/rust-toolchain` | `@stable` | `@stable` | unchanged (pinned name, moving target by design) |
| `Swatinem/rust-cache` | `@v2` | `@v2` | unchanged |
| `codecov/codecov-action` | `@v5` | `@v5` | unchanged |

GitHub runner deprecation notice on recent runs:
> "Node.js 20 actions are deprecated … actions/upload-artifact@v4, actions/download-artifact@v4 …"

Both artifact actions still publish on Node 20; GitHub will force Node 24 on 2026-06-02. No version fixes the warning today — bumps will come through Dependabot after the 2026-06 release wave. Tracked only; no workflow change.

---

## 5. Old CD workflow — what was it doing?

`.github/workflows/_disabled_cd.yml` (leading-underscore is the convention this repo used to mark "parsed-but-never-runs" — GitHub shows it as `disabled_manually`):

- Trigger: `push { branches: [main] }` + `workflow_dispatch`
- Single job `build-push`:
  1. Checkout with LFS.
  2. Compute lowercase owner for OCI reference.
  3. `docker/setup-qemu-action@v3` + `docker/setup-buildx-action@v3`.
  4. `docker/login-action@v3` against `ghcr.io` with `GITHUB_TOKEN`.
  5. `docker/build-push-action@v6` → `push: true`, tags `sha` and `latest`, cache `type=gha`.

Why disabled: no staging/production target exists; the `build-push` would publish images that nothing consumes. No smoke test suite gates the publish. Credentials for any downstream deploy target aren't provisioned.

**Replacement**: `.github/workflows/cd.yml.disabled` (see §6). The new file has a richer scaffold: build → smoke → staging (manual dispatch) → production (with environment approval). It stays disabled.

---

## 6. New workflow set — what changed

| File | Purpose | Required check |
|---|---|---|
| `ci-quality.yml` | ruff + mypy strict + bandit + pip-audit (non-blocking) | `quality` |
| `ci-rust.yml` | `cargo check`/`test`/`clippy` + maturin wheel build + artifact upload | `rust` |
| `ci-unit-tests.yml` | pytest tests/unit + coverage (artifact + codecov) | `unit-tests` |
| `ci-integration-tests.yml` | docker-compose test stack + pytest tests/integration | `integration-tests` |
| `ci-backtest-gate.yml` | Backtest regression gate, **MUZZLED** (`continue-on-error: true`) | not required |
| `cd.yml.disabled` | Production CD pipeline scaffold — intentionally disabled | N/A |
| `backtest.yml` | Nightly backtest (cron) — existing, minimally modernized (added explicit cache step) | N/A |

Changes vs. old `ci.yml`:

1. **One-concern-per-file.** Five separate workflows. Easier to see red/green per concern in the GitHub UI, and future auth changes (e.g. `integration-tests` needs broker sandbox creds) don't ripple into the other four.
2. **Explicit cache step** (`actions/cache@v4`) everywhere instead of `setup-python`'s implicit cache. Cache key is `pip-{os}-py{version}-{hash(pyproject.toml, requirements.txt)}` which shares hits across all CI workflows on the same commit.
3. **`cargo clippy`** added (warnings-as-errors, `continue-on-error: true` until clippy baseline is clean).
4. **`pip-audit`** on requirements.txt, non-blocking, writes CVE list to the GitHub Step Summary. Graduate to blocking once baseline is clean.
5. **Python version matrix** — `strategy.matrix.python-version: ["3.12"]` in the relevant workflows. Adding 3.13 later is a one-line change.
6. **Action version downgrade** from `@v5/@v6` back to `@v4/@v5` per brief. v4/v5 is the current-stable LTS series; v5/v6 pins are ahead-of-stable and unnecessary.
7. **Concurrency per workflow** — each workflow has its own `concurrency.group` so a new push cancels only its own family of jobs, not all five.

---

## 7. Pre-existing mypy debt on main — **RESOLVED 2026-04-22 (issue #240)**

From Sprint 3B close-out and confirmed by reading `backtesting/data_loader.py` at the `pq.write_table` call site:

```python
pq.write_table(pa.Table.from_pandas(df), str(path))
```

`mypy . --strict` flagged this as **`[no-untyped-call]`** because pyarrow 24.0 ships `py.typed` but leaves `pyarrow.parquet.write_table` without annotations in its inline stubs.

**Resolution** (PR resolving #240):

Targeted `# type: ignore[no-untyped-call]` on the call site with a documented rationale. `pyarrow-stubs` was evaluated and rejected — the package is pinned at 20.x (checked 2026-04-22 via `pip index versions`) against our pyarrow 24.0 requirement, and an inline `py.typed` marker takes precedence over external stubs in mypy's resolution, so the external package cannot supply the missing annotations here.

A round-trip Parquet write/read smoke test was added at `tests/unit/backtesting/test_data_loader_writes.py` to catch any future pyarrow API drift that the silenced call would otherwise hide.

**Effect**: `mypy --strict backtesting/` is clean. Future PRs touching `data_loader.py` no longer require `--admin` bypass to land. Quality CI returns to fully gating.

---

## 8. Dependabot

None configured today (`ls .github/dependabot.yml → not found`). This PR adds `.github/dependabot.yml` with:

- **pip** at `/` — weekly on Sunday, cap 5 open PRs, labels `dependencies`, `python`.
- **cargo** at `/rust` — weekly on Sunday, cap 3 open PRs. _Deviation from brief_: the brief listed three cargo entries (`/`, `/rust/apex_mc`, `/rust/apex_risk`). In this repo `Cargo.toml` exists at `/rust/Cargo.toml` (workspace) and `/rust/apex_mc/Cargo.toml` + `/rust/apex_risk/Cargo.toml` (members). The per-crate `Cargo.lock`s do not exist — the workspace has a single `rust/Cargo.lock`. Dependabot monitors the workspace at `/rust` and covers all three manifests via that single entry. Adding the per-crate entries would be redundant and slow the Sunday digest. Entry at `/` was dropped because `/Cargo.toml` does not exist (would fail Dependabot's manifest check). See the comment at the top of `.github/dependabot.yml`.
- **github-actions** at `/` — weekly on Sunday, cap 5 open PRs.

---

## 9. Supply chain (pip-audit / safety / SBOM)

Today: none. Bandit covers Python source static analysis but does not look at dependency CVEs.

This PR adds `pip-audit` as a `continue-on-error: true` step in `ci-quality.yml`. Findings are written to the GitHub Step Summary so they are one click away from any PR reviewer. The goal is to surface CVE drift without blocking dev. Graduation to blocking is the same mechanical flip as the coverage gate — one line change, no architectural work.

`safety` is intentionally not used — it requires an account and rate-limits on the free tier.

No SBOM generation in this PR; Dependabot's alert surface and the pip-audit baseline cover the typical "CVE on a pinned dep" case without the SBOM tooling overhead.

---

## 10. Coverage gate raise — handoff to issue #203

**Status on this PR**: no commit, no file modification. The gate stays at `--cov-fail-under=75` in `ci-unit-tests.yml` after this PR merges. Baseline behavior is preserved.

### 10.1 Exact diff to apply when #203 activates

File: `.github/workflows/ci-unit-tests.yml` — the `pytest tests/unit/` step inside the `unit-tests` job. On the post-merge state of this PR, the relevant line is approximately `ci-unit-tests.yml:93` (line number may shift by one if the file is reformatted; anchor on the `--cov-fail-under=` token).

```diff
           pytest tests/unit/ -v \
             --cov=services --cov=core --cov=backtesting \
             --cov-report=xml --cov-report=term-missing \
-            --cov-fail-under=75 --timeout=30
+            --cov-fail-under=85 --timeout=30
```

One character change. No other file touches needed. `pyproject.toml` does not have a repo-wide `--cov-fail-under` today; the CI workflow is the single source of truth for the gate.

### 10.2 Activation condition (from Roadmap §2.2.6)

> Once all Phase A §2.2.1 through §2.2.5 deliverables are merged and main has stably shown total coverage ≥ 85% for at least 7 days, raise the CI coverage gate in `.github/workflows/ci.yml` [now `ci-unit-tests.yml` — see §6] from `--cov-fail-under=75` to `--cov-fail-under=85`.

Mechanically: before opening the PR that applies §10.1, verify on main:

```bash
# For each of the last 7 green CI runs on main, the "coverage" line
# under the unit-tests job should read ≥ 85.0%. Spot-check via:
gh run list --workflow=unit-tests --branch=main --limit=20 --json conclusion,createdAt,databaseId \
  --jq '[.[] | select(.conclusion == "success")][:7]'
# For each run ID, `gh run view <id> --log | grep "Total coverage"` should show ≥ 85%.
```

### 10.3 Per-module residual gap (snapshot 2026-04-21)

The table of 35 modules below 85% is captured in §3.3 above. When activating #203, re-run the coverage audit and verify that every entry either cleared 85% or was moved into `[tool.coverage.run] omit` with a documented rationale (per §3.4 point 3).

Focus targets (ordered by marginal yield for the 3.6pp gap):

1. `core/zmq_broker.py` (0%, 136 stmts) — candidate for `omit` (ZMQ infra, live-only) or dedicated integration coverage.
2. `services/data_ingestion/{alpaca_feed,binance_feed,macro_feed}.py` (0%, 216 stmts total) — same disposition.
3. `core/service_runner.py` (0%, 52 stmts) — candidate for `omit` (requires ZMQ/Redis runtime per existing `[tool.coverage.run] omit` policy on `services/*/service.py`).
4. `services/command_center/pnl_tracker.py` (14%) and `services/command_center/health_checker.py` (33%) — testable, need unit coverage.
5. `services/signal_engine/technical.py` (59%, 190 stmts) — highest absolute yield among non-zero-coverage modules.

### 10.4 Handoff statement

**This work is captured for issue #203 (Phase A.13). When activated: apply the one-line diff in §10.1, and verify that every module listed in §3.3 has either cleared 85% in the preceding 7 days, or been moved into `[tool.coverage.run] omit` with a documented rationale.** The baseline snapshot (81.40%, 35 modules under 85%, 1349 missed statements) in §3 is the "before" picture that §2.2.6's "stably ≥ 85% for 7 days" must visibly move past before the gate raise is safe.

---

## 11. Summary: what to land now vs. later

**Land now** (part of this PR):
- New workflow files + split
- Disabled CD scaffold
- Dependabot config
- This audit doc

**Defer to follow-up**:
- Coverage gate raise — handed off to **issue #203 (phase-A.13)**, activation condition in §10.2, exact diff in §10.1. **Not committed on this branch.**
- ~~mypy debt fix on `backtesting/data_loader.py` at the `pq.write_table` call site (see §7)~~ — **RESOLVED via issue #240 (2026-04-22)**
- Branch protection on `main` requiring `quality`, `rust`, `unit-tests`, `integration-tests`

**Tracked upstream, do not touch in this PR**:
- Backtest-gate un-muzzling — owned by issue #196 / phase-A.6, depends on phase-A.5 landing. Prerequisite: 2026-04-27 or Strategy #1 Gate 2.
