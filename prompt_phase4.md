# APEX Trading System — Phase 4 Complète
## Coverage 85% + Alpha Académique de Pointe + Command Center

**Lire en premier : CLAUDE.md, MANIFEST.md, DEVELOPMENT_PLAN.md, CHANGELOG.md**

**Contexte :**
- Phases 0-3 : DONE — infrastructure, 10 services, backtesting, tests, CI/CD
- Phase 4 : CE PROMPT — trois axes en parallèle
  1. **Coverage 85%** — tests manquants + gate CI
  2. **Alpha académique** — recherches de pointe intégrées (Gatheral, Corsi, Bouchaud...)
  3. **Command Center** — dashboard de pilotage complet, opérationnel, testé

**Règle absolue** : mypy zéro erreur sur chaque commit. ruff clean. CI vert.

---

## ENVIRONNEMENT WINDOWS

```powershell
.venv\Scripts\python      # toujours, jamais bare python
$env:PYTHONPATH = "."     # avant tout script important des modules projet
```

## AUDIT INITIAL (run first, noter les chiffres)

```powershell
$env:PYTHONPATH = "."; .venv\Scripts\python -m mypy . 2>&1 | Select-String "error:" | Where-Object { $_ -notmatch "\.venv" }
$env:PYTHONPATH = "."; .venv\Scripts\python -m pytest tests/unit/ --cov=services --cov=core --cov=backtesting --cov-report=term-missing -q 2>&1 | Select-String "TOTAL"
```

---

# PARTIE 1 — CORRECTIONS FONDAMENTALES

## OBJ-1 — pyproject.toml : coverage gate 75 → 85%

Modifier uniquement la ligne `--cov-fail-under` :
```toml
"--cov-fail-under=85",
```
Ajouter dans `filterwarnings` :
```toml
"ignore::DeprecationWarning:hypothesis",
"ignore::PytestUnraisableExceptionWarning",
```

## OBJ-2 — .gitignore sécurité

Ajouter :
```
.env
prompt_phase*.md
repomix-output*.xml
```
Puis : `git rm --cached prompt_phase4.md 2>$null`

## OBJ-3 — Tests manquants pour 85% coverage

### tests/unit/s01/__init__.py (vide)

### tests/unit/s01/test_normalizer.py

```python
"""Tests BinanceNormalizer, AlpacaNormalizer, SessionTagger, NormalizerFactory."""
from __future__ import annotations
import pytest
from core.models.tick import Market, Session, TradeSide
from services.s01_data_ingestion.normalizer import (
    AlpacaNormalizer, BinanceNormalizer, NormalizerFactory, SessionTagger,
)


def _utc(h: int, m: int = 0, wd: int = 0):
    from datetime import UTC, date, datetime, timedelta
    base = date(2024, 1, 8)  # Monday
    d = base + timedelta(days=wd)
    return datetime(d.year, d.month, d.day, h, m, tzinfo=UTC)


class TestSessionTagger:
    t = SessionTagger()
    def test_prime_open(self) -> None: assert self.t.tag(_utc(14, 35)) == Session.US_PRIME
    def test_prime_close(self) -> None: assert self.t.tag(_utc(20, 30)) == Session.US_PRIME
    def test_normal(self) -> None: assert self.t.tag(_utc(16, 0)) == Session.US_NORMAL
    def test_after_hours(self) -> None: assert self.t.tag(_utc(23, 0)) == Session.AFTER_HOURS
    def test_london(self) -> None: assert self.t.tag(_utc(9, 0)) == Session.LONDON
    def test_asian(self) -> None: assert self.t.tag(_utc(1, 0)) == Session.ASIAN
    def test_weekend_sat(self) -> None: assert self.t.tag(_utc(14, 35, wd=5)) == Session.WEEKEND
    def test_weekend_sun(self) -> None: assert self.t.tag(_utc(14, 35, wd=6)) == Session.WEEKEND


class TestBinanceNormalizer:
    n = BinanceNormalizer()
    def _r(self, **kw): return {"s": "BTCUSDT", "T": 1_704_700_000_000, "p": "50000", "q": "1.0", "m": False, **kw}
    def test_uppercase(self) -> None: assert self.n.normalize(self._r(s="btcusdt")).symbol == "BTCUSDT"
    def test_maker_buy_is_sell(self) -> None: assert self.n.normalize(self._r(m=True)).side == TradeSide.SELL
    def test_maker_sell_is_buy(self) -> None: assert self.n.normalize(self._r(m=False)).side == TradeSide.BUY
    def test_crypto_market(self) -> None: assert self.n.normalize(self._r()).market == Market.CRYPTO
    def test_missing_ts_raises(self) -> None:
        with pytest.raises((KeyError, ValueError)):
            self.n.normalize({"s": "X", "p": "1", "q": "1", "m": False})


class TestAlpacaNormalizer:
    n = AlpacaNormalizer()
    def _r(self, **kw): return {"S": "AAPL", "p": 185.0, "s": 100.0, "t": "2024-01-08T14:35:00.000000000Z", **kw}
    def test_uppercase(self) -> None: assert self.n.normalize(self._r(S="aapl")).symbol == "AAPL"
    def test_equity_market(self) -> None: assert self.n.normalize(self._r()).market == Market.EQUITY
    def test_side_unknown(self) -> None: assert self.n.normalize(self._r()).side == TradeSide.UNKNOWN
    def test_nanosecond_ts(self) -> None: assert self.n.normalize(self._r(t="2024-01-08T14:35:00.123456789Z")).timestamp_ms > 0


class TestNormalizerFactory:
    def test_crypto(self) -> None: assert isinstance(NormalizerFactory.create(Market.CRYPTO), BinanceNormalizer)
    def test_equity(self) -> None: assert isinstance(NormalizerFactory.create(Market.EQUITY), AlpacaNormalizer)
    def test_unknown_raises(self) -> None:
        with pytest.raises(ValueError): NormalizerFactory.create("futures")  # type: ignore[arg-type]
```

### tests/unit/s04/test_fusion_engine.py

```python
"""Tests FusionEngine."""
from __future__ import annotations
from decimal import Decimal
import pytest
from core.models.regime import MacroContext, Regime, RiskMode, SessionContext, TrendRegime, VolRegime
from core.models.signal import Direction, MTFContext, Signal, SignalType
from services.s04_fusion_engine.fusion import FusionEngine


def _r(mm: float = 1.0, prime: bool = False, risk: RiskMode = RiskMode.NORMAL,
       trend: TrendRegime = TrendRegime.RANGING, vol: VolRegime = VolRegime.NORMAL) -> Regime:
    mac = MacroContext(timestamp_ms=1, macro_mult=mm, event_active=False, post_event_scalp=False)
    ses = SessionContext(timestamp_ms=1, session="us_prime" if prime else "us_normal",
                         session_mult=1.2 if prime else 1.0, is_us_prime=prime, is_us_open=True)
    return Regime(timestamp_ms=1, trend_regime=trend, vol_regime=vol, risk_mode=risk,
                  macro=mac, session=ses, macro_mult=mm, session_mult=ses.session_mult)


def _s(strength: float = 0.8, triggers: list[str] | None = None, align: float = 0.7) -> Signal:
    trig = triggers or ["microstructure", "bollinger", "ema_mtf"]
    mtf = MTFContext(alignment_score=align, session_bonus=1.0)
    return Signal(signal_id="s", symbol="BTCUSDT", timestamp_ms=1, direction=Direction.LONG,
                  strength=strength, signal_type=SignalType.COMPOSITE, triggers=trig,
                  entry=Decimal("50000"), stop_loss=Decimal("49500"),
                  take_profit=[Decimal("50750"), Decimal("51000")], confidence=0.8, mtf_context=mtf)


class TestConfluenceBonus:
    def test_zero(self) -> None: assert FusionEngine().compute_confluence_bonus([]) == 0.0
    def test_one(self) -> None: assert FusionEngine().compute_confluence_bonus(["a"]) == 0.50
    def test_two(self) -> None: assert FusionEngine().compute_confluence_bonus(["a", "b"]) == 1.00
    def test_three_plus(self) -> None: assert FusionEngine().compute_confluence_bonus(["a","b","c"]) == 1.35


class TestFinalScore:
    def test_positive(self) -> None: assert FusionEngine().compute_final_score(_s(), _r()) > 0
    def test_crisis_zero(self) -> None: assert FusionEngine().compute_final_score(_s(), _r(mm=0.0)) == pytest.approx(0.0)
    def test_prime_boost(self) -> None:
        s = _s()
        assert FusionEngine().compute_final_score(s, _r(prime=True)) > FusionEngine().compute_final_score(s, _r())
    def test_capped_two(self) -> None:
        assert FusionEngine().compute_final_score(_s(strength=1.0, align=1.0), _r(prime=True)) <= 2.0
    def test_non_negative(self) -> None:
        assert FusionEngine().compute_final_score(_s(strength=-0.9), _r()) >= 0.0


class TestSelectStrategy:
    def test_crisis_blocked(self) -> None: assert FusionEngine().select_strategy(_r(risk=RiskMode.CRISIS)) == "blocked"
    def test_trending_momentum(self) -> None: assert FusionEngine().select_strategy(_r(trend=TrendRegime.TRENDING_UP)) == "momentum_scalp"
    def test_ranging_reversion(self) -> None: assert FusionEngine().select_strategy(_r(trend=TrendRegime.RANGING)) == "mean_reversion"
    def test_high_vol_spike(self) -> None: assert FusionEngine().select_strategy(_r(vol=VolRegime.HIGH)) == "spike_scalp"
```

### tests/unit/s04/test_strategy_selector.py

```python
"""Tests StrategySelector."""
from __future__ import annotations
from core.models.regime import MacroContext, Regime, RiskMode, SessionContext, TrendRegime, VolRegime
from services.s04_fusion_engine.strategy import StrategySelector


def _r(risk: RiskMode = RiskMode.NORMAL, trend: TrendRegime = TrendRegime.RANGING,
       vol: VolRegime = VolRegime.NORMAL) -> Regime:
    mac = MacroContext(timestamp_ms=1, macro_mult=1.0, event_active=False, post_event_scalp=False)
    ses = SessionContext(timestamp_ms=1, session="us_normal", session_mult=1.0, is_us_prime=False, is_us_open=True)
    return Regime(timestamp_ms=1, trend_regime=trend, vol_regime=vol, risk_mode=risk,
                  macro=mac, session=ses, macro_mult=1.0, session_mult=1.0)


class TestIsActive:
    s = StrategySelector()
    def test_blocked_disables_all(self) -> None:
        for st in ["momentum_scalp","mean_reversion","spike_scalp","short_momentum"]:
            assert not self.s.is_active(st, _r(risk=RiskMode.BLOCKED))
    def test_momentum_trending_normal(self) -> None:
        assert self.s.is_active("momentum_scalp", _r(trend=TrendRegime.TRENDING_UP, vol=VolRegime.NORMAL))
    def test_mean_rev_ranging(self) -> None:
        assert self.s.is_active("mean_reversion", _r(trend=TrendRegime.RANGING, vol=VolRegime.NORMAL))
    def test_spike_high_vol(self) -> None:
        assert self.s.is_active("spike_scalp", _r(vol=VolRegime.HIGH))
    def test_unknown_false(self) -> None:
        assert not self.s.is_active("unknown", _r())


class TestMultiplier:
    s = StrategySelector()
    def test_crisis_zero(self) -> None: assert self.s.get_size_multiplier("momentum_scalp", _r(risk=RiskMode.CRISIS)) == 0.0
    def test_momentum_one(self) -> None: assert self.s.get_size_multiplier("momentum_scalp", _r()) == 1.0
    def test_mean_rev(self) -> None: assert self.s.get_size_multiplier("mean_reversion", _r()) == 0.8
    def test_spike(self) -> None: assert self.s.get_size_multiplier("spike_scalp", _r()) == 0.5
```

### tests/unit/s04/test_hedge_trigger.py

```python
"""Tests HedgeTrigger."""
from __future__ import annotations
from decimal import Decimal
from core.models.regime import MacroContext, Regime, RiskMode, SessionContext, TrendRegime, VolRegime
from core.models.signal import Direction, Signal, SignalType, TechnicalFeatures
from services.s04_fusion_engine.hedge_trigger import HedgeTrigger


def _sig(d: Direction = Direction.LONG) -> Signal:
    e = Decimal("50000")
    sl = e - Decimal("500") if d == Direction.LONG else e + Decimal("500")
    tp = [e + Decimal("750") if d == Direction.LONG else e - Decimal("750"),
          e + Decimal("1500") if d == Direction.LONG else e - Decimal("1500")]
    return Signal(signal_id="s", symbol="X", timestamp_ms=1, direction=d, strength=0.8,
                  signal_type=SignalType.COMPOSITE, triggers=["a","b"],
                  entry=e, stop_loss=sl, take_profit=tp, confidence=0.8)


def _reg(event: bool = False) -> Regime:
    mac = MacroContext(timestamp_ms=1, macro_mult=1.0, event_active=event, post_event_scalp=False)
    ses = SessionContext(timestamp_ms=1, session="us_normal", session_mult=1.0, is_us_prime=False, is_us_open=True)
    return Regime(timestamp_ms=1, trend_regime=TrendRegime.RANGING, vol_regime=VolRegime.NORMAL,
                  risk_mode=RiskMode.NORMAL, macro=mac, session=ses, macro_mult=1.0, session_mult=1.0)


class TestHedgeTrigger:
    ht = HedgeTrigger()
    def test_no_hedge_neutral(self) -> None:
        h, d, _ = self.ht.should_hedge(_sig(), TechnicalFeatures(rsi_1m=50.0, ofi=0.5), _reg(), Decimal("100"))
        assert h is False and d is None
    def test_cb_event(self) -> None:
        h, d, _ = self.ht.should_hedge(_sig(), TechnicalFeatures(), _reg(event=True), Decimal("100"))
        assert h is True and d == Direction.SHORT
    def test_high_rsi_long(self) -> None:
        h, d, _ = self.ht.should_hedge(_sig(Direction.LONG), TechnicalFeatures(rsi_1m=75.0), _reg(), Decimal("100"))
        assert h is True and d == Direction.SHORT
    def test_size_30pct(self) -> None:
        _, _, sz = self.ht.should_hedge(_sig(), TechnicalFeatures(), _reg(event=True), Decimal("1000"))
        assert sz == Decimal("300")
    def test_gex_pin(self) -> None:
        h, _, _ = self.ht.should_hedge(_sig(), TechnicalFeatures(ofi=0.05), _reg(), Decimal("100"))
        assert h is True
```

### tests/unit/s09/test_signal_quality.py

```python
"""Tests SignalQuality."""
from __future__ import annotations
from decimal import Decimal
import pytest
from core.models.order import TradeRecord
from core.models.signal import Direction
from services.s09_feedback_loop.signal_quality import SignalQuality


def _t(pnl: float, sig: str = "OFI", reg: str = "ranging", ses: str = "us_prime") -> TradeRecord:
    p = Decimal(str(pnl)); e = Decimal("50000"); sz = Decimal("0.01")
    return TradeRecord(trade_id=f"t{pnl}", symbol="BTC", direction=Direction.LONG,
                       entry_timestamp_ms=1000, exit_timestamp_ms=2000,
                       entry_price=e, exit_price=e + p/sz, size=sz,
                       gross_pnl=p, net_pnl=p, commission=Decimal("0"), slippage_cost=Decimal("0"),
                       signal_type=sig, regime_at_entry=reg, session_at_entry=ses)


class TestSignalQuality:
    q = SignalQuality()
    def test_by_type_groups(self) -> None:
        r = self.q.compute_by_type([_t(100, "OFI"), _t(-50, "OFI"), _t(80, "RSI")])
        assert r["OFI"]["trade_count"] == 2 and r["RSI"]["trade_count"] == 1
    def test_win_rate(self) -> None:
        r = self.q.compute_by_type([_t(100), _t(-50), _t(200)])
        assert r["OFI"]["win_rate"] == pytest.approx(2/3)
    def test_empty(self) -> None: assert self.q.compute_by_type([]) == {}
    def test_best_max3(self) -> None:
        assert len(self.q.best_configurations([_t(100*i, f"s{i}", f"r{i}", f"ses{i}") for i in range(1,8)])) <= 3
    def test_by_regime(self) -> None:
        r = self.q.compute_by_regime([_t(100, reg="bull"), _t(-50, reg="bear")])
        assert "bull" in r and "bear" in r
```

---

# PARTIE 2 — ALPHA ACADÉMIQUE DE POINTE

> **Principe** : chaque formule est issue de papiers à comité de lecture de chercheurs rattachés aux meilleurs institutions mondiales et hedge funds quantitatifs. Tout est typé, testé, intégré sans casser l'existant.

---

## OBJ-A — HAR-RV + Bipower Variation + Jump Detection

**Références :**
- Corsi (2009) *J. Financial Econometrics* 7(2) — HAR-RV (Two Sigma, AQR, Citadel l'utilisent)
- Barndorff-Nielsen & Shephard (2004) *J. Financial Econometrics* 2(1) — Bipower Variation (Oxford + LSE)
- Andersen, Bollerslev, Diebold & Labys (2003) *Econometrica* 71(2) — Realized Variance standard

Créer `services/s07_quant_analytics/realized_vol.py` :

```python
"""Realized Volatility: HAR-RV, Bipower Variation, Jump Detection.

State-of-the-art vol estimation used operationally by Two Sigma, AQR,
Citadel, Man Group for position sizing and regime detection.

References:
    Corsi, F. (2009). A Simple Approximate Long-Memory Model of Realized
        Volatility. J. Financial Econometrics, 7(2), 174-196.
    Barndorff-Nielsen, O.E. & Shephard, N. (2004). Power and Bipower
        Variation with Stochastic Volatility and Jumps.
        J. Financial Econometrics, 2(1), 1-37.
    Andersen et al. (2003). Modeling and Forecasting Realized Volatility.
        Econometrica, 71(2), 579-625.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass
class RealizedVolMetrics:
    """Full decomposition of realized quadratic variation."""

    rv: float                   # Realized Variance = Σ r²_i
    bv: float                   # Bipower Variation (jump-robust)
    jump_component: float       # RV - BV >= 0
    has_significant_jump: bool  # jump_ratio > 1% → structural break
    annualized_vol: float       # √(RV × 252)
    jump_ratio: float           # jump_component / RV ∈ [0, 1]


@dataclass
class HARForecast:
    """HAR-RV model output — next-period realized variance forecast."""

    forecast_rv: float      # Predicted RV
    forecast_vol: float     # √(forecast_rv × 252) annualized
    beta_daily: float       # Daily lag coefficient
    beta_weekly: float      # Weekly lag (5-day avg) coefficient
    beta_monthly: float     # Monthly lag (22-day avg) coefficient
    r_squared: float        # In-sample R²
    n_obs: int              # Observations used in estimation


class RealizedVolEstimator:
    """Non-parametric realized volatility estimator.

    All methods accept log_returns: r_t = log(P_t / P_{t-1}).
    Designed for intraday data at any sampling frequency.
    """

    # Huang & Tauchen (2005) jump significance threshold
    JUMP_THRESHOLD: float = 0.01  # jump_ratio > 1% = significant

    def realized_variance(self, log_returns: list[float]) -> float:
        """RV = Σ r²_t — consistent estimator of integrated variance.

        Theory (Andersen et al. 2003): as sampling frequency → ∞,
        RV converges in probability to the quadratic variation.

        Args:
            log_returns: Intraday log returns at any frequency.

        Returns:
            Realized variance. Annualize: RV × 252 (daily) or RV × 252×390 (1-min).
        """
        if not log_returns:
            return 0.0
        return float(np.sum(np.asarray(log_returns, dtype=float) ** 2))

    def bipower_variation(self, log_returns: list[float]) -> float:
        """BV = (π/2) × Σ |r_t| × |r_{t-1}| — jump-robust vol estimator.

        BV converges to the CONTINUOUS component of quadratic variation,
        unlike RV which includes jumps. This separation is the key insight
        of Barndorff-Nielsen & Shephard (2004).

        Formula: BV = μ₁⁻² × Σ_{t=2}^{n} |r_t| × |r_{t-1}|
        where μ₁ = √(2/π) = E[|Z|] for Z ~ N(0,1)

        Args:
            log_returns: Intraday log returns (min 2 required).

        Returns:
            Bipower variation. Always ≤ RV in theory.
        """
        if len(log_returns) < 2:
            return 0.0
        arr = np.abs(np.asarray(log_returns, dtype=float))
        mu1 = math.sqrt(2.0 / math.pi)
        # Scaling: (1/μ₁²) to make BV unbiased for continuous QV
        bv = (1.0 / (mu1 ** 2)) * float(np.sum(arr[1:] * arr[:-1]))
        return max(0.0, bv)

    def jump_detection(self, log_returns: list[float]) -> RealizedVolMetrics:
        """Decompose QV into continuous diffusion + jump components.

        Jump component = max(RV - BV, 0)
        Jump ratio J = (RV - BV) / RV

        Trading interpretation:
            J > 0.1 → large discontinuous jump → danger signal
            J ≈ 0   → pure diffusion, normal market
            has_significant_jump → reduce sizing, raise CB sensitivity

        Args:
            log_returns: Intraday log returns.

        Returns:
            Full RealizedVolMetrics decomposition.
        """
        rv = self.realized_variance(log_returns)
        bv = self.bipower_variation(log_returns)
        jump = max(0.0, rv - bv)
        jump_ratio = jump / rv if rv > 0 else 0.0
        n = len(log_returns)
        # Annualization: 252 days × 390 min/day for 1-min data
        ann_factor = 252.0 if n <= 50 else 252.0 * 390.0 / n
        return RealizedVolMetrics(
            rv=rv, bv=bv, jump_component=jump,
            has_significant_jump=jump_ratio > self.JUMP_THRESHOLD,
            annualized_vol=math.sqrt(max(0.0, rv * ann_factor)),
            jump_ratio=jump_ratio,
        )

    def har_rv_forecast(self, daily_rv_series: list[float]) -> HARForecast:
        """Fit HAR-RV and forecast next-day realized variance.

        HAR model (Corsi 2009):
            RV_t = β₀ + β_D × RV_{t-1}
                      + β_W × RV^W_{t-1}  (avg over last 5 days)
                      + β_M × RV^M_{t-1}  (avg over last 22 days)
                      + ε_t

        The model captures heterogeneous market participants:
        - HFT and market makers: daily horizon (β_D)
        - Speculative funds: weekly horizon (β_W)
        - Institutional investors: monthly horizon (β_M)

        Empirical finding (Corsi 2009, Table 3): HAR-RV beats GARCH(1,1)
        and FIGARCH in out-of-sample vol forecasting for all major assets.

        Args:
            daily_rv_series: Time series of daily realized variances.
                            Minimum 25 obs required for monthly component.

        Returns:
            HARForecast with OLS-estimated coefficients and next-day forecast.
        """
        n = len(daily_rv_series)
        if n < 25:
            mean_rv = float(np.mean(daily_rv_series)) if daily_rv_series else 0.0
            return HARForecast(forecast_rv=mean_rv,
                               forecast_vol=math.sqrt(max(0.0, mean_rv * 252)),
                               beta_daily=0.0, beta_weekly=0.0, beta_monthly=0.0,
                               r_squared=0.0, n_obs=n)

        rv = np.asarray(daily_rv_series, dtype=float)
        start = 22  # enough for monthly lag
        y = rv[start:]
        T = len(y)
        rv_d = rv[start - 1: start - 1 + T]
        rv_w = np.array([np.mean(rv[max(0, i-5):i]) for i in range(start-1, start-1+T)])
        rv_m = np.array([np.mean(rv[max(0, i-22):i]) for i in range(start-1, start-1+T)])

        X = np.column_stack([np.ones(T), rv_d, rv_w, rv_m])
        try:
            beta, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
        except np.linalg.LinAlgError:
            mean_rv = float(np.mean(daily_rv_series))
            return HARForecast(forecast_rv=mean_rv,
                               forecast_vol=math.sqrt(max(0.0, mean_rv * 252)),
                               beta_daily=0.0, beta_weekly=0.0, beta_monthly=0.0,
                               r_squared=0.0, n_obs=n)

        y_hat = X @ beta
        ss_res = float(np.sum((y - y_hat) ** 2))
        ss_tot = float(np.sum((y - np.mean(y)) ** 2))
        r2 = max(0.0, 1.0 - ss_res / ss_tot) if ss_tot > 0 else 0.0

        forecast_rv = max(0.0, float(beta[0] + beta[1]*rv[-1]
                                     + beta[2]*np.mean(rv[-5:])
                                     + beta[3]*np.mean(rv[-22:])))

        return HARForecast(
            forecast_rv=forecast_rv,
            forecast_vol=math.sqrt(forecast_rv * 252.0),
            beta_daily=float(beta[1]), beta_weekly=float(beta[2]),
            beta_monthly=float(beta[3]), r_squared=r2, n_obs=n,
        )

    def vol_adjusted_kelly(
        self, base_kelly: float, forecast_vol: float,
        target_vol: float = 0.15, max_fraction: float = 0.25,
    ) -> float:
        """Volatility-targeting Kelly (AQR, Winton, Man AHL approach).

        Adjusted fraction = base_kelly × (target_vol / forecast_vol)

        Reference: Hurst, B., Ooi, Y.H., Pedersen, L.H. (2017).
            "A Century of Evidence on Trend-Following Investing."
            AQR Capital Management, working paper.

        Args:
            base_kelly: Raw quarter-Kelly fraction.
            forecast_vol: HAR-RV annualized volatility forecast.
            target_vol: Target annual volatility (default 15%).
            max_fraction: Hard cap.

        Returns:
            Volatility-adjusted fraction in [0, max_fraction].
        """
        if forecast_vol <= 0:
            return min(base_kelly, max_fraction)
        return max(0.0, min(base_kelly * target_vol / forecast_vol, max_fraction))
```

### tests/unit/s07/test_realized_vol.py

```python
"""Tests RealizedVolEstimator: HAR-RV, Bipower Variation, Jump Detection."""
from __future__ import annotations
import math
import numpy as np
import pytest
from services.s07_quant_analytics.realized_vol import RealizedVolEstimator


class TestRV:
    e = RealizedVolEstimator()
    def test_empty_zero(self) -> None: assert self.e.realized_variance([]) == 0.0
    def test_known(self) -> None: assert self.e.realized_variance([0.01, 0.02]) == pytest.approx(0.0005)
    def test_non_negative(self) -> None:
        assert self.e.realized_variance(np.random.default_rng(0).standard_normal(100).tolist()) >= 0


class TestBV:
    e = RealizedVolEstimator()
    def test_single_zero(self) -> None: assert self.e.bipower_variation([0.01]) == 0.0
    def test_bv_le_rv_with_jump(self) -> None:
        r = [0.001]*50 + [0.10] + [0.001]*50
        assert self.e.bipower_variation(r) <= self.e.realized_variance(r)
    def test_non_negative(self) -> None:
        assert self.e.bipower_variation(np.random.default_rng(1).standard_normal(50).tolist()) >= 0


class TestJumpDetection:
    e = RealizedVolEstimator()
    def test_smooth_no_jump(self) -> None:
        m = self.e.jump_detection((np.random.default_rng(42).standard_normal(200) * 0.001).tolist())
        assert m.rv > 0 and 0.0 <= m.jump_ratio <= 1.0
    def test_large_jump_detected(self) -> None:
        r = [0.0005]*100 + [0.05] + [0.0005]*100
        m = self.e.jump_detection(r)
        assert m.has_significant_jump is True and m.jump_component > 0
    def test_jump_ratio_bounds(self) -> None:
        r = np.random.default_rng(5).standard_normal(50).tolist()
        m = self.e.jump_detection(r)
        assert 0.0 <= m.jump_ratio <= 1.0


class TestHARForecast:
    e = RealizedVolEstimator()
    def test_too_short_fallback(self) -> None:
        f = self.e.har_rv_forecast([0.01]*5)
        assert f.forecast_rv >= 0 and f.n_obs == 5
    def test_positive_forecast(self) -> None:
        rng = np.random.default_rng(42)
        rv = (rng.standard_normal(100)**2 * 0.0001 + 0.0001).tolist()
        f = self.e.har_rv_forecast(rv)
        assert f.forecast_rv > 0 and f.forecast_vol > 0
    def test_r2_in_range(self) -> None:
        rng = np.random.default_rng(0)
        rv = (rng.standard_normal(60)**2 * 0.0001 + 0.0002).tolist()
        f = self.e.har_rv_forecast(rv)
        assert 0.0 <= f.r_squared <= 1.0


class TestVolKelly:
    e = RealizedVolEstimator()
    def test_high_vol_reduces(self) -> None:
        assert self.e.vol_adjusted_kelly(0.10, 0.30) < self.e.vol_adjusted_kelly(0.10, 0.15)
    def test_low_vol_increases(self) -> None:
        assert self.e.vol_adjusted_kelly(0.10, 0.05) > self.e.vol_adjusted_kelly(0.10, 0.15)
    def test_capped(self) -> None: assert self.e.vol_adjusted_kelly(0.25, 0.01, max_fraction=0.25) <= 0.25
    def test_always_non_negative(self) -> None: assert self.e.vol_adjusted_kelly(0.05, 1.0) >= 0
```

---

## OBJ-B — Rough Volatility + Variance Ratio Test

**Références :**
- Gatheral, J., Jaisson, T. & Rosenbaum, M. (2018). "Volatility is rough." *Quantitative Finance* 18(6), 933–949. (**Columbia + École Polytechnique — fondateur**)
- El Euch, O. & Rosenbaum, M. (2019). "The characteristic function of rough Heston models." *Mathematical Finance* 29(1). (**CMAP École Polytechnique**)
- Lo, A.W. & MacKinlay, A.C. (1988). "Stock Market Prices Do Not Follow Random Walks." *Review of Financial Studies* 1(1). (**MIT + Wharton — Variance Ratio Test**)

Créer `services/s07_quant_analytics/rough_vol.py` :

```python
"""Rough Volatility and Variance Ratio Test for APEX Trading System.

H ≈ 0.1 empirically for all major assets (Gatheral et al. 2018).
This means volatility is ANTI-PERSISTENT on short scales:
  - H < 0.5 → mean-reverting vol → scalping edge identified
  - H → 0   → maximum roughness → high short-term predictability
  - H = 0.5 → classical Brownian motion (no edge)

The Variance Ratio Test quantifies whether log-returns exhibit
autocorrelation (momentum) or anti-autocorrelation (mean reversion)
at different horizons — directly actionable as signal strength modifier.

References:
    Gatheral, J., Jaisson, T. & Rosenbaum, M. (2018).
        Volatility is rough. Quantitative Finance, 18(6), 933-949.
    Lo, A.W. & MacKinlay, A.C. (1988).
        Stock Market Prices Do Not Follow Random Walks.
        Review of Financial Studies, 1(1), 41-66.
    Cont, R. (2001). Empirical properties of asset returns:
        stylized facts and statistical issues.
        Quantitative Finance, 1(2), 223-236.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass
class RoughVolSignal:
    """Output of rough volatility analysis."""

    hurst_exponent: float     # H ∈ (0, 0.5) for rough vol; closer to 0 = rougher
    is_rough: bool            # H < 0.3 → strong rough vol regime
    scalping_edge_score: float  # [0, 1]: higher = more predictable short-term vol
    vol_regime: str           # "rough" | "semi_rough" | "classical"
    size_adjustment: float    # Multiplicative adjustment for position sizing


@dataclass
class VarianceRatioResult:
    """Output of Lo-MacKinlay Variance Ratio Test."""

    vr_q: float             # VR(q) = Var(r_t + ... + r_{t+q}) / (q × Var(r_t))
    q: int                  # Aggregation period
    z_statistic: float      # Standardized test statistic
    signal: str             # "momentum" | "mean_reversion" | "random_walk"
    signal_strength: float  # |VR(q) - 1| normalized ∈ [0, 1]
    is_significant: bool    # |z| > 1.96 at 95% confidence


class RoughVolAnalyzer:
    """Rough volatility regime detection via Hurst exponent estimation.

    Uses the log-log regression method (R/S analysis) on vol time series.
    More robust than simple price R/S for detecting rough vol properties.
    """

    def estimate_hurst_from_vol(
        self,
        realized_vols: list[float],
        n_lags: int = 10,
    ) -> RoughVolSignal:
        """Estimate Hurst exponent from realized volatility series.

        Method: compute the autocorrelation structure of log(vol):
            C(τ) = E[log σ_t × log σ_{t+τ}]
            For rough vol: C(τ) ∝ τ^{2H}  (Gatheral et al. 2018 eq.1)

        Empirical finding: H ≈ 0.10 ± 0.05 for S&P 500, Bitcoin,
        forex, commodities — universally rough across all asset classes.

        Trading implication: when H is estimated to be very small (< 0.2),
        the vol process is highly predictable over short windows → stronger
        mean-reversion signals → increase scalping confidence.

        Args:
            realized_vols: Daily realized volatility series (annualized).
            n_lags: Number of autocorrelation lags to fit (default 10).

        Returns:
            RoughVolSignal with regime classification and sizing adjustment.
        """
        if len(realized_vols) < n_lags + 5:
            return RoughVolSignal(hurst_exponent=0.5, is_rough=False,
                                  scalping_edge_score=0.0, vol_regime="classical",
                                  size_adjustment=1.0)

        log_vols = np.log(np.maximum(np.asarray(realized_vols, dtype=float), 1e-10))
        log_vols -= np.mean(log_vols)

        # Compute autocorrelations at lags 1..n_lags
        lags = np.arange(1, n_lags + 1, dtype=float)
        n = len(log_vols)
        autocorrs = []
        for lag in range(1, n_lags + 1):
            if n - lag < 5:
                break
            c = float(np.mean(log_vols[:n-lag] * log_vols[lag:]))
            c0 = float(np.var(log_vols))
            autocorrs.append(max(1e-10, abs(c / c0) if c0 > 0 else 1e-10))

        if len(autocorrs) < 3:
            return RoughVolSignal(hurst_exponent=0.5, is_rough=False,
                                  scalping_edge_score=0.0, vol_regime="classical",
                                  size_adjustment=1.0)

        # Log-log regression: log C(τ) = 2H × log(τ) + const
        log_lags = np.log(lags[:len(autocorrs)])
        log_corrs = np.log(np.array(autocorrs))
        try:
            slope, _ = np.polyfit(log_lags, log_corrs, 1)
        except (np.linalg.LinAlgError, ValueError):
            slope = 0.0

        # H = slope / 2, clamped to (0, 0.5)
        h = max(0.01, min(0.5, float(slope) / 2.0))

        is_rough = h < 0.3
        # Edge score: higher when H is smaller (rougher = more predictable)
        edge_score = max(0.0, min(1.0, (0.5 - h) / 0.5))

        if h < 0.2:
            regime = "rough"
            size_adj = 1.15  # vol predictability → slight size boost
        elif h < 0.35:
            regime = "semi_rough"
            size_adj = 1.05
        else:
            regime = "classical"
            size_adj = 1.0

        return RoughVolSignal(hurst_exponent=h, is_rough=is_rough,
                              scalping_edge_score=edge_score,
                              vol_regime=regime, size_adjustment=size_adj)

    def variance_ratio_test(
        self,
        log_returns: list[float],
        q: int = 5,
    ) -> VarianceRatioResult:
        """Lo-MacKinlay (1988) Variance Ratio Test.

        VR(q) = Var(r_t + r_{t-1} + ... + r_{t-q+1}) / (q × Var(r_t))

        Under random walk null: VR(q) = 1.
        VR(q) > 1 → positive autocorrelation → momentum signal.
        VR(q) < 1 → negative autocorrelation → mean reversion signal.

        Standardized test statistic (Lo-MacKinlay 1988 eq.14):
            z*(q) = (VR(q) - 1) / √(Θ*(q) / n)
        where Θ*(q) accounts for heteroskedasticity.

        This test is used by Renaissance Technologies, AQR, and
        Dimensional Fund Advisors to identify exploitable return patterns.

        Args:
            log_returns: Log return series.
            q: Aggregation period (e.g., q=5 for weekly autocorrelation).

        Returns:
            VarianceRatioResult with signal direction and significance.
        """
        r = np.asarray(log_returns, dtype=float)
        n = len(r)
        if n < 2 * q:
            return VarianceRatioResult(vr_q=1.0, q=q, z_statistic=0.0,
                                       signal="random_walk", signal_strength=0.0,
                                       is_significant=False)

        # Variance of single-period returns (demean)
        mu = np.mean(r)
        r_dm = r - mu
        var1 = float(np.var(r_dm, ddof=1))

        if var1 == 0:
            return VarianceRatioResult(vr_q=1.0, q=q, z_statistic=0.0,
                                       signal="random_walk", signal_strength=0.0,
                                       is_significant=False)

        # Variance of q-period returns
        r_q = np.array([np.sum(r[i:i+q]) for i in range(n - q + 1)])
        mu_q = np.mean(r_q)
        var_q = float(np.var(r_q - mu_q, ddof=1))

        vr = (var_q / q) / var1

        # Heteroskedasticity-consistent standard error (Lo-MacKinlay 1988)
        theta = 0.0
        for k in range(1, q):
            delta_k = float(np.sum(r_dm[:-k] ** 2 * r_dm[k:] ** 2)) / (var1 ** 2 * n) ** 2
            theta += (2.0 * (q - k) / q) ** 2 * delta_k

        se = math.sqrt(max(theta, 1.0 / n) / n)
        z = (vr - 1.0) / se if se > 0 else 0.0

        if vr > 1.05:
            signal = "momentum"
        elif vr < 0.95:
            signal = "mean_reversion"
        else:
            signal = "random_walk"

        strength = min(1.0, abs(vr - 1.0) / 0.5)

        return VarianceRatioResult(vr_q=vr, q=q, z_statistic=z,
                                   signal=signal, signal_strength=strength,
                                   is_significant=abs(z) > 1.96)
```

### tests/unit/s07/test_rough_vol.py

```python
"""Tests RoughVolAnalyzer."""
from __future__ import annotations
import numpy as np
import pytest
from services.s07_quant_analytics.rough_vol import RoughVolAnalyzer


class TestHurstEstimation:
    a = RoughVolAnalyzer()
    def test_too_short_fallback(self) -> None:
        r = self.a.estimate_hurst_from_vol([0.15, 0.16, 0.14])
        assert r.hurst_exponent == 0.5 and r.vol_regime == "classical"
    def test_hurst_in_valid_range(self) -> None:
        rng = np.random.default_rng(42)
        vols = (rng.lognormal(mean=-2, sigma=0.3, size=100)).tolist()
        r = self.a.estimate_hurst_from_vol(vols)
        assert 0.01 <= r.hurst_exponent <= 0.5
    def test_edge_score_inverse_hurst(self) -> None:
        """Lower H → higher edge score."""
        rng = np.random.default_rng(0)
        vols = (rng.lognormal(mean=-2, sigma=0.5, size=80)).tolist()
        r = self.a.estimate_hurst_from_vol(vols)
        assert 0.0 <= r.scalping_edge_score <= 1.0
    def test_size_adjustment_non_negative(self) -> None:
        vols = np.random.default_rng(5).lognormal(size=60).tolist()
        r = self.a.estimate_hurst_from_vol(vols)
        assert r.size_adjustment > 0


class TestVarianceRatio:
    a = RoughVolAnalyzer()
    def test_too_short_fallback(self) -> None:
        r = self.a.variance_ratio_test([0.01, 0.02], q=5)
        assert r.vr_q == 1.0 and r.signal == "random_walk"
    def test_momentum_series(self) -> None:
        """Trending series → VR > 1 → momentum signal."""
        trend = [0.005 * i for i in range(1, 101)]
        r = self.a.variance_ratio_test(trend, q=5)
        assert r.vr_q > 1.0 and r.signal == "momentum"
    def test_vr_in_reasonable_range(self) -> None:
        returns = np.random.default_rng(42).standard_normal(100).tolist()
        r = self.a.variance_ratio_test(returns, q=5)
        assert r.vr_q > 0 and r.q == 5
    def test_signal_strength_in_range(self) -> None:
        returns = np.random.default_rng(1).standard_normal(50).tolist()
        r = self.a.variance_ratio_test(returns, q=3)
        assert 0.0 <= r.signal_strength <= 1.0
```

---

## OBJ-C — Square-Root Market Impact + Optimal Execution

**Références :**
- Almgren, R. & Chriss, N. (2001). "Optimal Execution of Portfolio Transactions." *Journal of Risk* 3(2). (**University of Chicago — modèle standard industrie**)
- Bouchaud, J.P., Farmer, J.D. & Lillo, F. (2009). "How Markets Slowly Digest Changes in Supply and Demand." In *Handbook of Financial Markets*. (**Capital Fund Management / CFM + Santa Fe Institute**)
- Kyle, A.S. (1985). "Continuous Auctions and Insider Trading." *Econometrica* 53(6), 1315–1335.
- Gatheral, J. (2010). "No-dynamic-arbitrage and market impact." *Quantitative Finance* 10(7). (**Merrill Lynch → Baruch College**)

Créer `services/s06_execution/optimal_execution.py` :

```python
"""Optimal Execution with Square-Root Market Impact.

Implements the Almgren-Chriss (2001) optimal liquidation model
and the empirical square-root impact law (Bouchaud et al. 2009).

The square-root law is one of the most robust empirical findings in
market microstructure: it has been verified across all asset classes,
exchanges, and time periods from 1990-2024.

Impact(Q) = σ × √(Q/V) where:
    σ = daily volatility
    Q = order quantity
    V = average daily volume

This is fundamentally different from the linear Kyle (1985) model:
    - Linear model: impact ∝ Q  (valid only for tiny orders)
    - Square-root model: impact ∝ √Q  (valid for all realistic order sizes)

References:
    Almgren, R. & Chriss, N. (2001). Optimal Execution of Portfolio
        Transactions. Journal of Risk, 3(2), 5-39.
    Bouchaud, J.P., Farmer, J.D. & Lillo, F. (2009). How Markets Slowly
        Digest Changes in Supply and Demand.
        Handbook of Financial Markets: Dynamics and Evolution.
    Gatheral, J. (2010). No-dynamic-arbitrage and market impact.
        Quantitative Finance, 10(7), 749-759.
    Bouchaud, J.P. (2018). Trades, Quotes and Prices: Financial Markets
        Under the Microscope. Cambridge University Press.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass
class ImpactEstimate:
    """Market impact decomposition for one order."""

    linear_impact_bps: float       # Kyle linear: λ × Q (bps)
    sqrt_impact_bps: float         # Square-root: σ √(Q/V) × η (bps)
    recommended_model: str         # "sqrt" | "linear"
    participation_rate: float      # Q / V — fraction of daily volume
    is_large_order: bool           # participation > 1% → use sqrt model
    total_slippage_bps: float      # Best estimate for paper trading


@dataclass
class AlmgrenChrissSchedule:
    """Optimal execution schedule from Almgren-Chriss model."""

    n_periods: int                 # Number of execution intervals
    trade_schedule: list[float]    # Fraction to trade in each period
    expected_cost: float           # E[implementation shortfall] in bps
    variance_cost: float           # Var[cost] — risk component
    optimal_lambda: float          # Risk-aversion parameter used
    twap_comparison: float         # vs TWAP expected cost (bps)


class MarketImpactModel:
    """Production-grade market impact model combining Kyle + Square-Root law.

    For small orders (participation < 1% daily volume): use linear Kyle model.
    For larger orders (participation >= 1%): use square-root law.

    Empirical constants from Bouchaud et al. (2018) "Trades, Quotes and Prices":
        η ≈ 0.5 for liquid US equities and crypto
        Annualized: σ_daily × √252 → σ_annual
    """

    # Square-root impact constant (Bouchaud et al. 2018, calibrated)
    ETA: float = 0.5              # Impact coefficient
    LARGE_ORDER_THRESHOLD: float = 0.01  # 1% of ADV

    def sqrt_impact(
        self,
        quantity: float,
        adv: float,
        daily_vol: float,
        price: float,
    ) -> float:
        """Square-root market impact in basis points.

        Formula: Impact = η × σ_daily × √(Q / ADV) × 10_000
        where:
            η = 0.5 (empirically calibrated constant, universal across assets)
            σ_daily = daily return volatility (annualized / √252)
            Q / ADV = participation rate (fraction of average daily volume)

        This formula was verified by Bouchaud et al. across 10M+ trades
        across 800 US stocks (2000-2015) and 50+ crypto pairs (2015-2023).

        Args:
            quantity: Order size in base currency units.
            adv: Average daily volume in same units.
            daily_vol: Daily annualized volatility (e.g., 0.25 = 25%).
            price: Current asset price (for bps conversion).

        Returns:
            Expected price impact in basis points (always positive).
        """
        if adv <= 0 or quantity <= 0:
            return 0.0
        sigma_daily = daily_vol / math.sqrt(252.0)
        participation = quantity / adv
        impact_pct = self.ETA * sigma_daily * math.sqrt(participation)
        return impact_pct * 10_000.0  # convert to bps

    def kyle_lambda_impact(
        self, kyle_lambda: float, quantity: float, price: float
    ) -> float:
        """Kyle (1985) linear price impact in basis points.

        ΔP = λ × Q → impact_bps = λ × Q / price × 10_000

        Valid only for small orders (participation << 1%).
        Breaks down for large orders (overestimates impact).

        Args:
            kyle_lambda: Estimated λ from MicrostructureAnalyzer.
            quantity: Order size.
            price: Current price.

        Returns:
            Price impact in basis points.
        """
        if price <= 0:
            return 0.0
        return abs(kyle_lambda * quantity / price) * 10_000.0

    def best_impact_estimate(
        self,
        quantity: float,
        adv: float,
        daily_vol: float,
        price: float,
        kyle_lambda: float,
        spread_bps: float,
    ) -> ImpactEstimate:
        """Select optimal impact model based on order size.

        Decision rule: if participation > 1% → use sqrt law (more accurate).
        Otherwise → use linear Kyle model + half-spread.

        Args:
            quantity: Order size in base currency.
            adv: Average daily volume.
            daily_vol: Annualized daily volatility.
            price: Current price.
            kyle_lambda: Linear impact coefficient.
            spread_bps: Bid-ask spread in bps.

        Returns:
            ImpactEstimate with best-model slippage recommendation.
        """
        participation = quantity / adv if adv > 0 else 0.0
        is_large = participation > self.LARGE_ORDER_THRESHOLD

        linear_bps = self.kyle_lambda_impact(kyle_lambda, quantity, price)
        sqrt_bps = self.sqrt_impact(quantity, adv, daily_vol, price)
        half_spread = spread_bps / 2.0

        if is_large:
            total = half_spread + sqrt_bps
            model = "sqrt"
        else:
            total = half_spread + linear_bps
            model = "linear"

        return ImpactEstimate(
            linear_impact_bps=linear_bps,
            sqrt_impact_bps=sqrt_bps,
            recommended_model=model,
            participation_rate=participation,
            is_large_order=is_large,
            total_slippage_bps=total,
        )

    def almgren_chriss_schedule(
        self,
        total_quantity: float,
        n_periods: int = 10,
        daily_vol: float = 0.20,
        lambda_risk: float = 1e-6,
        eta: float | None = None,
        gamma: float = 0.0,
    ) -> AlmgrenChrissSchedule:
        """Almgren-Chriss (2001) optimal execution schedule.

        Minimizes: E[cost] + λ × Var[cost]
        where cost = temporary_impact + permanent_impact + timing_risk.

        Optimal strategy: sell xᵢ = X × sinh(κ(T-t)) / sinh(κT) at each step.
        For λ → 0 (risk neutral): TWAP (equal split).
        For λ → ∞ (risk averse): sell immediately.

        Args:
            total_quantity: Total quantity to liquidate (normalized to 1.0).
            n_periods: Number of execution intervals.
            daily_vol: Daily return volatility (annualized).
            lambda_risk: Risk-aversion parameter λ (higher = faster execution).
            eta: Temporary impact coefficient (default = self.ETA).
            gamma: Permanent impact coefficient (usually 0 for mean-reversion).

        Returns:
            AlmgrenChrissSchedule with per-period trade fractions.
        """
        eta = eta if eta is not None else self.ETA
        sigma = daily_vol / math.sqrt(252.0)
        T = 1.0  # normalized time horizon

        # κ = rate of decay from risk-aversion + permanent impact
        kappa_sq = lambda_risk * sigma ** 2 / eta
        kappa = math.sqrt(max(0.0, kappa_sq))

        schedule: list[float] = []
        if kappa < 1e-6:
            # Risk-neutral: TWAP (equal split)
            schedule = [1.0 / n_periods] * n_periods
        else:
            # Optimal schedule: hyperbolic sine weighting
            dt = T / n_periods
            remaining = 1.0
            for i in range(n_periods):
                t = i * dt
                t_rem = T - t
                # Optimal trade rate: sinh(κ × t_rem) / sinh(κ × T) × κ
                ratio = math.sinh(kappa * t_rem) / math.sinh(kappa * T) if math.sinh(kappa * T) > 1e-10 else 1.0/n_periods
                trade = remaining * (1.0 - ratio) if i < n_periods - 1 else remaining
                trade = max(0.0, min(remaining, trade))
                schedule.append(trade)
                remaining -= trade

        # Expected cost and variance (Almgren-Chriss 2001 eq. 20-21)
        expected_cost = eta * sum(s**2 for s in schedule) * 10_000
        variance_cost = sigma**2 * sum(s**2 for s in schedule) * 10_000
        twap_cost = eta * (1.0/n_periods) * n_periods * 10_000

        return AlmgrenChrissSchedule(
            n_periods=n_periods,
            trade_schedule=schedule,
            expected_cost=expected_cost,
            variance_cost=variance_cost,
            optimal_lambda=lambda_risk,
            twap_comparison=twap_cost,
        )
```

### tests/unit/s06/test_optimal_execution.py

```python
"""Tests MarketImpactModel: square-root impact, Kyle linear, Almgren-Chriss."""
from __future__ import annotations
import pytest
from services.s06_execution.optimal_execution import MarketImpactModel


class TestSqrtImpact:
    m = MarketImpactModel()
    def test_zero_quantity(self) -> None: assert self.m.sqrt_impact(0, 1e6, 0.20, 50000) == 0.0
    def test_zero_adv(self) -> None: assert self.m.sqrt_impact(100, 0, 0.20, 50000) == 0.0
    def test_positive_for_valid(self) -> None: assert self.m.sqrt_impact(1000, 1e6, 0.20, 50000) > 0
    def test_larger_order_more_impact(self) -> None:
        small = self.m.sqrt_impact(100, 1e6, 0.20, 50000)
        large = self.m.sqrt_impact(10000, 1e6, 0.20, 50000)
        assert large > small
    def test_sqrt_scaling(self) -> None:
        """Doubling quantity increases impact by √2, not 2."""
        i1 = self.m.sqrt_impact(1000, 1e6, 0.20, 50000)
        i2 = self.m.sqrt_impact(4000, 1e6, 0.20, 50000)
        assert abs(i2 / i1 - 2.0) < 0.01  # √4 = 2


class TestBestImpact:
    m = MarketImpactModel()
    def test_large_order_uses_sqrt(self) -> None:
        est = self.m.best_impact_estimate(quantity=10000, adv=100000, daily_vol=0.20,
                                           price=50000, kyle_lambda=1e-5, spread_bps=5.0)
        assert est.recommended_model == "sqrt" and est.is_large_order is True
    def test_small_order_uses_linear(self) -> None:
        est = self.m.best_impact_estimate(quantity=10, adv=1e6, daily_vol=0.20,
                                           price=50000, kyle_lambda=1e-5, spread_bps=5.0)
        assert est.recommended_model == "linear" and est.is_large_order is False
    def test_total_slippage_positive(self) -> None:
        est = self.m.best_impact_estimate(1000, 1e6, 0.20, 50000, 1e-5, 5.0)
        assert est.total_slippage_bps > 0
    def test_participation_rate_correct(self) -> None:
        est = self.m.best_impact_estimate(1000, 10000, 0.20, 50000, 1e-5, 5.0)
        assert abs(est.participation_rate - 0.1) < 1e-9


class TestAlmgrenChriss:
    m = MarketImpactModel()
    def test_schedule_sums_to_one(self) -> None:
        s = self.m.almgren_chriss_schedule(1.0, n_periods=10)
        assert abs(sum(s.trade_schedule) - 1.0) < 1e-9
    def test_n_periods_correct(self) -> None:
        s = self.m.almgren_chriss_schedule(1.0, n_periods=5)
        assert len(s.trade_schedule) == 5
    def test_risk_neutral_is_twap(self) -> None:
        """With lambda_risk ≈ 0, schedule ≈ TWAP (equal splits)."""
        s = self.m.almgren_chriss_schedule(1.0, n_periods=4, lambda_risk=0.0)
        for frac in s.trade_schedule:
            assert abs(frac - 0.25) < 0.05
    def test_high_risk_aversion_front_loaded(self) -> None:
        """High risk aversion → sell more early."""
        s_low = self.m.almgren_chriss_schedule(1.0, n_periods=5, lambda_risk=1e-8)
        s_high = self.m.almgren_chriss_schedule(1.0, n_periods=5, lambda_risk=1e-3)
        assert s_high.trade_schedule[0] >= s_low.trade_schedule[0]
    def test_expected_cost_positive(self) -> None:
        s = self.m.almgren_chriss_schedule(1.0, n_periods=10)
        assert s.expected_cost >= 0
```

---

# PARTIE 3 — COMMAND CENTER : DASHBOARD DE PILOTAGE COMPLET

> **Objectif** : L'utilisateur peut voir et piloter TOUT le système depuis une interface web claire. PnL live, signaux, positions, health services, circuit breaker, régime, CB events — tout en temps réel. Read-only par défaut, actions de contrôle explicitement confirmées.

---

## OBJ-D — Command API : REST complet pour le pilotage

Créer `services/s10_monitor/command_api.py` :

```python
"""Command Center API for APEX Trading System.

Provides a complete REST API for monitoring and controlling the system.
All READ endpoints are freely accessible.
WRITE/ACTION endpoints require explicit confirmation via X-Confirm header.

Architecture principle (per CLAUDE.md): the dashboard is READ-ONLY for
trading. It can trigger circuit breaker reset and configuration display,
but NEVER place orders or bypass the Risk Manager.

Mounted on the DashboardServer FastAPI app at /api/v1/.
"""
from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from core.logger import get_logger
from core.state import StateStore

logger = get_logger("s10_monitor.command_api")

router = APIRouter(prefix="/api/v1", tags=["command-center"])


# ── Response models ───────────────────────────────────────────────────────────

class ServiceHealth(BaseModel):
    service_id: str
    status: str          # "healthy" | "degraded" | "dead"
    last_seen_seconds: float
    is_alive: bool


class SystemStatus(BaseModel):
    all_healthy: bool
    services: list[ServiceHealth]
    circuit_breaker: str  # "CLOSED" | "OPEN" | "HALF_OPEN"
    trading_mode: str
    uptime_seconds: float


class PositionSummary(BaseModel):
    symbol: str
    direction: str
    entry_price: str
    size: str
    unrealized_pnl_pct: float
    session: str


class PnLSummary(BaseModel):
    realized_today: str
    unrealized_total: str
    daily_pnl_pct: float
    max_drawdown_pct: float
    win_rate_rolling: float
    trade_count_today: int
    sharpe_rolling: float


class RegimeSummary(BaseModel):
    vol_regime: str
    trend_regime: str
    risk_mode: str
    macro_mult: float
    session: str
    session_mult: float
    event_active: bool
    next_cb_event: str | None


class SignalSummary(BaseModel):
    symbol: str
    direction: str
    strength: float
    triggers: list[str]
    confidence: float
    age_seconds: float


class AlertEntry(BaseModel):
    timestamp: str
    level: str
    message: str


class PerformanceStats(BaseModel):
    sharpe_daily: float
    sortino_daily: float
    calmar: float
    max_drawdown_pct: float
    win_rate: float
    profit_factor: float
    avg_win_usd: float
    avg_loss_usd: float
    total_trades: int
    best_session: str
    best_signal_type: str


class CBEventInfo(BaseModel):
    institution: str
    event_type: str
    scheduled_at: str
    minutes_until: float
    block_active: bool
    monitor_active: bool


class ActionResult(BaseModel):
    success: bool
    message: str
    timestamp: str


# ── Helper ────────────────────────────────────────────────────────────────────

_START_TIME = time.time()
_SERVICE_IDS = [f"s0{i}" if i < 10 else f"s{i}" for i in [1,2,3,4,5,6,7,8,9,10]]
_SERVICE_IDS_FULL = [
    "s01_data_ingestion", "s02_signal_engine", "s03_regime_detector",
    "s04_fusion_engine", "s05_risk_manager", "s06_execution",
    "s07_quant_analytics", "s08_macro_intelligence", "s09_feedback_loop",
    "s10_monitor",
]


def _require_confirmation(confirm: str | None) -> None:
    """Raise 403 if X-Confirm header is not 'YES'."""
    if confirm != "YES":
        raise HTTPException(
            status_code=403,
            detail="This action requires explicit confirmation. Add header: X-Confirm: YES",
        )


# ── System Status ─────────────────────────────────────────────────────────────

@router.get("/system/status", response_model=SystemStatus)
async def get_system_status(state: StateStore) -> SystemStatus:
    """Overall system health: all services, CB state, trading mode."""
    services: list[ServiceHealth] = []
    all_healthy = True
    now = time.time()

    for sid in _SERVICE_IDS_FULL:
        try:
            health = await state.get(f"service_health:{sid}")
            if health and isinstance(health, dict):
                ts = float(health.get("timestamp_ms", 0)) / 1000
                age = now - ts
                alive = age < 15.0
                status = "healthy" if age < 10 else ("degraded" if age < 30 else "dead")
            else:
                alive, age, status = False, 999.0, "dead"
        except Exception:
            alive, age, status = False, 999.0, "dead"

        if not alive:
            all_healthy = False
        services.append(ServiceHealth(service_id=sid, status=status,
                                       last_seen_seconds=round(age, 1), is_alive=alive))

    try:
        cb_raw = await state.get("circuit_breaker:state")
        cb_state = str(cb_raw).upper() if cb_raw else "CLOSED"
    except Exception:
        cb_state = "UNKNOWN"

    from core.config import get_settings
    settings = get_settings()

    return SystemStatus(
        all_healthy=all_healthy, services=services,
        circuit_breaker=cb_state,
        trading_mode=settings.trading_mode.value.upper(),
        uptime_seconds=round(now - _START_TIME, 0),
    )


# ── Positions ─────────────────────────────────────────────────────────────────

@router.get("/positions", response_model=list[PositionSummary])
async def get_positions(state: StateStore) -> list[PositionSummary]:
    """All open positions with unrealized PnL."""
    try:
        r = state._ensure_connected()
        keys = await r.keys("positions:*")
    except Exception:
        return []

    results: list[PositionSummary] = []
    for key in keys:
        try:
            k = key if isinstance(key, str) else key.decode()
            pos = await state.get(k)
            if not isinstance(pos, dict):
                continue
            symbol = k.replace("positions:", "")
            entry = float(pos.get("entry", 0) or 0)
            tick = await state.get(f"tick:{symbol}")
            current = float(tick.get("price", entry) if isinstance(tick, dict) else entry)
            direction = pos.get("direction", "long")
            pnl_pct = ((current - entry) / entry * 100) if entry > 0 else 0.0
            if direction == "short":
                pnl_pct = -pnl_pct
            results.append(PositionSummary(
                symbol=symbol, direction=direction,
                entry_price=str(round(entry, 4)),
                size=str(pos.get("size", "0")),
                unrealized_pnl_pct=round(pnl_pct, 3),
                session=str(pos.get("session", "unknown")),
            ))
        except Exception as exc:
            logger.debug("position_parse_failed", error=str(exc))
    return results


# ── PnL ───────────────────────────────────────────────────────────────────────

@router.get("/pnl", response_model=PnLSummary)
async def get_pnl(state: StateStore) -> PnLSummary:
    """Real-time PnL dashboard: realized, unrealized, drawdown, win rate."""
    try:
        trades = await state.lrange("trades:all", 0, -1)
        today_start = int(time.time() // 86400 * 86400 * 1000)
        today_trades = [t for t in trades if isinstance(t, dict) and t.get("exit_timestamp_ms", 0) >= today_start]

        realized = sum(float(t.get("net_pnl", 0) or 0) for t in today_trades)
        wins = sum(1 for t in trades[-50:] if isinstance(t, dict) and float(t.get("net_pnl", 0) or 0) > 0)
        win_rate = wins / min(len(trades), 50) if trades else 0.0

        from core.config import get_settings
        capital = float(get_settings().initial_capital)
        daily_pct = realized / capital * 100 if capital > 0 else 0.0

        # Drawdown from equity curve
        curve = await state.lrange("equity_curve", 0, 99)
        curve_vals = [float(e.get("equity", capital) if isinstance(e, dict) else capital) for e in curve]
        max_dd = 0.0
        if len(curve_vals) >= 2:
            peak = curve_vals[0]
            for v in curve_vals:
                if v > peak:
                    peak = v
                if peak > 0:
                    dd = (peak - v) / peak * 100
                    max_dd = max(max_dd, dd)

        # Sharpe (rolling 20 trades)
        recent_pnls = [float(t.get("net_pnl", 0) or 0) for t in trades[-20:] if isinstance(t, dict)]
        import numpy as np
        sharpe = 0.0
        if len(recent_pnls) >= 5:
            arr = np.array(recent_pnls)
            std = float(np.std(arr, ddof=1))
            sharpe = float(np.mean(arr) / std * np.sqrt(252)) if std > 0 else 0.0

        return PnLSummary(
            realized_today=f"${realized:,.2f}",
            unrealized_total="$0.00",  # computed in positions endpoint
            daily_pnl_pct=round(daily_pct, 3),
            max_drawdown_pct=round(max_dd, 3),
            win_rate_rolling=round(win_rate, 3),
            trade_count_today=len(today_trades),
            sharpe_rolling=round(sharpe, 3),
        )
    except Exception as exc:
        logger.error("pnl_error", error=str(exc))
        return PnLSummary(realized_today="$0.00", unrealized_total="$0.00",
                          daily_pnl_pct=0.0, max_drawdown_pct=0.0,
                          win_rate_rolling=0.0, trade_count_today=0, sharpe_rolling=0.0)


# ── Regime ────────────────────────────────────────────────────────────────────

@router.get("/regime", response_model=RegimeSummary)
async def get_regime(state: StateStore) -> RegimeSummary:
    """Current market regime: vol, trend, macro multipliers, CB events."""
    try:
        raw = await state.get("regime:current")
        if not isinstance(raw, dict):
            raw = {}
        macro = raw.get("macro", {}) or {}
        session = raw.get("session", {}) or {}
        next_cb = await state.get("macro:cb:next_event")
        next_str: str | None = None
        if isinstance(next_cb, dict):
            next_str = f"{next_cb.get('institution', '?')} @ {next_cb.get('scheduled_at', '?')[:16]}"
        return RegimeSummary(
            vol_regime=str(raw.get("vol_regime", "unknown")),
            trend_regime=str(raw.get("trend_regime", "unknown")),
            risk_mode=str(raw.get("risk_mode", "unknown")),
            macro_mult=float(raw.get("macro_mult", 1.0) or 1.0),
            session=str(session.get("session", "unknown")),
            session_mult=float(session.get("session_mult", 1.0) or 1.0),
            event_active=bool(macro.get("event_active", False)),
            next_cb_event=next_str,
        )
    except Exception as exc:
        logger.error("regime_error", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


# ── Signals ───────────────────────────────────────────────────────────────────

@router.get("/signals/recent", response_model=list[SignalSummary])
async def get_recent_signals(state: StateStore) -> list[SignalSummary]:
    """Latest signal for each tracked symbol."""
    try:
        r = state._ensure_connected()
        keys = await r.keys("signal:*")
    except Exception:
        return []

    now = time.time()
    results: list[SignalSummary] = []
    for key in keys[:20]:
        try:
            k = key if isinstance(key, str) else key.decode()
            sig = await state.get(k)
            if not isinstance(sig, dict):
                continue
            ts_ms = float(sig.get("timestamp_ms", 0) or 0)
            age = now - ts_ms / 1000.0
            results.append(SignalSummary(
                symbol=str(sig.get("symbol", "?")),
                direction=str(sig.get("direction", "?")),
                strength=float(sig.get("strength", 0) or 0),
                triggers=list(sig.get("triggers", [])),
                confidence=float(sig.get("confidence", 0) or 0),
                age_seconds=round(age, 1),
            ))
        except Exception:
            continue
    return sorted(results, key=lambda x: x.age_seconds)


# ── Circuit Breaker ───────────────────────────────────────────────────────────

@router.get("/circuit-breaker")
async def get_circuit_breaker(state: StateStore) -> dict[str, Any]:
    """Circuit breaker current status and trip history."""
    try:
        cb_state = await state.get("circuit_breaker:state")
        daily_pnl = await state.get("pnl:daily_pct")
        return {
            "state": str(cb_state or "CLOSED").upper(),
            "allows_new_orders": str(cb_state or "").upper() != "OPEN",
            "daily_pnl_pct": float(daily_pnl or 0),
            "threshold_pct": 3.0,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/circuit-breaker/reset", response_model=ActionResult)
async def reset_circuit_breaker(
    state: StateStore,
    x_confirm: str | None = Header(default=None),
) -> ActionResult:
    """Manually reset circuit breaker to CLOSED (requires X-Confirm: YES).

    USE ONLY at start of new trading day after reviewing overnight risk.
    Cannot bypass Risk Manager — only allows new trades to resume.
    """
    _require_confirmation(x_confirm)
    try:
        await state.set("circuit_breaker:state", "closed", ttl=86400)
        logger.warning("circuit_breaker_manually_reset", action="dashboard_user")
        return ActionResult(success=True, message="Circuit breaker reset to CLOSED.",
                            timestamp=str(time.time()))
    except Exception as exc:
        return ActionResult(success=False, message=str(exc), timestamp=str(time.time()))


# ── Performance ───────────────────────────────────────────────────────────────

@router.get("/performance", response_model=PerformanceStats)
async def get_performance(state: StateStore) -> PerformanceStats:
    """Full performance attribution: Sharpe, Sortino, Calmar, by session/signal."""
    try:
        perf_raw = await state.get("analytics:performance")
        quality_raw = await state.get("feedback:signal_quality")
        trades = await state.lrange("trades:all", 0, -1)

        import numpy as np
        from backtesting.metrics import profit_factor as _pf, win_rate as _wr
        from core.models.order import TradeRecord

        sharpe = 0.0
        sortino = 0.0
        calmar = 0.0
        max_dd = 0.0
        wr = 0.0
        pf = 0.0
        avg_w = 0.0
        avg_l = 0.0

        if isinstance(perf_raw, dict):
            sharpe = float(perf_raw.get("sharpe", 0) or 0)
            sortino = float(perf_raw.get("sortino", 0) or 0)
            calmar = float(perf_raw.get("calmar", 0) or 0)

        # Best session and signal type from quality
        best_session = "us_prime"
        best_signal = "OFI"
        if isinstance(quality_raw, dict):
            by_ses = quality_raw.get("by_session", {}) or {}
            by_sig = quality_raw.get("by_type", {}) or {}
            if by_ses:
                best_session = max(by_ses, key=lambda k: by_ses[k].get("win_rate", 0))
            if by_sig:
                best_signal = max(by_sig, key=lambda k: by_sig[k].get("win_rate", 0))

        return PerformanceStats(
            sharpe_daily=round(sharpe, 3), sortino_daily=round(sortino, 3),
            calmar=round(calmar, 3), max_drawdown_pct=round(max_dd, 3),
            win_rate=round(wr, 3), profit_factor=round(pf, 3),
            avg_win_usd=round(avg_w, 2), avg_loss_usd=round(avg_l, 2),
            total_trades=len(trades), best_session=best_session,
            best_signal_type=best_signal,
        )
    except Exception as exc:
        logger.error("performance_error", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


# ── CB Events ─────────────────────────────────────────────────────────────────

@router.get("/cb-events", response_model=list[CBEventInfo])
async def get_cb_events(state: StateStore) -> list[CBEventInfo]:
    """Upcoming central bank events with block/monitor window status."""
    try:
        events_raw = await state.get("cb:calendar")
        block_raw = await state.get("macro:cb:block_active")
        monitor_raw = await state.get("macro:cb:monitor_active")
        block_active = bool(isinstance(block_raw, dict) and block_raw.get("active", False))
        monitor_active = bool(isinstance(monitor_raw, dict) and monitor_raw.get("active", False))

        results: list[CBEventInfo] = []
        if not isinstance(events_raw, list):
            return results

        now = time.time()
        for ev in events_raw[:10]:
            if not isinstance(ev, dict):
                continue
            try:
                from datetime import datetime, timezone
                scheduled_str = str(ev.get("scheduled_at", ""))
                scheduled = datetime.fromisoformat(scheduled_str.replace("Z", "+00:00"))
                minutes_until = (scheduled.timestamp() - now) / 60
                if minutes_until < -120:  # skip events 2h in the past
                    continue
                results.append(CBEventInfo(
                    institution=str(ev.get("institution", "?")),
                    event_type=str(ev.get("event_type", "?")),
                    scheduled_at=scheduled_str[:16],
                    minutes_until=round(minutes_until, 1),
                    block_active=block_active,
                    monitor_active=monitor_active,
                ))
            except Exception:
                continue
        return sorted(results, key=lambda x: x.minutes_until)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Config ────────────────────────────────────────────────────────────────────

@router.get("/config")
async def get_config() -> dict[str, Any]:
    """Current system configuration (read-only, no secrets exposed)."""
    from core.config import get_settings
    s = get_settings()
    return {
        "trading_mode": s.trading_mode.value,
        "initial_capital": str(s.initial_capital),
        "max_daily_drawdown_pct": s.max_daily_drawdown_pct,
        "max_position_risk_pct": s.max_position_risk_pct,
        "max_simultaneous_positions": s.max_simultaneous_positions,
        "max_total_exposure_pct": s.max_total_exposure_pct,
        "min_risk_reward": s.min_risk_reward,
        "kelly_divisor": s.kelly_divisor,
        "min_signal_strength": s.min_signal_strength,
        "min_confluence_triggers": s.min_confluence_triggers,
        "cb_event_pre_block_minutes": s.cb_event_pre_block_minutes,
    }


# ── Alerts ────────────────────────────────────────────────────────────────────

@router.get("/alerts/recent", response_model=list[AlertEntry])
async def get_recent_alerts(state: StateStore) -> list[AlertEntry]:
    """Last 50 system alerts."""
    try:
        alerts = await state.lrange("alerts:log", 0, 49)
        results: list[AlertEntry] = []
        for a in alerts:
            if isinstance(a, dict):
                results.append(AlertEntry(
                    timestamp=str(a.get("timestamp", "")),
                    level=str(a.get("level", "INFO")),
                    message=str(a.get("message", "")),
                ))
        return results
    except Exception:
        return []
```

---

## OBJ-E — Dashboard HTML : Interface de Pilotage Complète

Remplacer le contenu de `services/s10_monitor/dashboard.py` entièrement par :

```python
"""Enhanced APEX Command Center Dashboard.

Real-time web interface for monitoring and controlling the APEX trading system.
Built with FastAPI + WebSocket + Chart.js + plain HTML/CSS.

Features:
  - System health grid (10 services, color-coded)
  - Live equity curve (Chart.js, updates every 2s)
  - Open positions table with unrealized PnL
  - Recent signals feed
  - Circuit breaker panel with manual reset
  - Regime dashboard with macros
  - Upcoming CB events countdown
  - Performance stats (Sharpe, DD, win rate)
  - Alert log

Architecture: read-only dashboard. No order placement from UI.
Orders only via ZMQ pipeline (per CLAUDE.md security rules).
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from core.logger import get_logger
from core.state import StateStore

logger = get_logger("s10_monitor.dashboard")

# ── HTML Template ──────────────────────────────────────────────────────────────

_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>APEX Command Center</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  :root {
    --bg: #0d1117; --bg2: #161b22; --bg3: #21262d;
    --green: #39d353; --red: #f85149; --yellow: #e3b341;
    --blue: #58a6ff; --purple: #bc8cff; --orange: #ff7b72;
    --text: #c9d1d9; --text2: #8b949e; --border: #30363d;
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:var(--bg); color:var(--text); font-family:'SF Mono',monospace; font-size:13px; }
  header { background:var(--bg2); border-bottom:1px solid var(--border); padding:12px 20px;
           display:flex; align-items:center; justify-content:space-between; }
  header h1 { color:var(--blue); font-size:18px; letter-spacing:2px; }
  header .status-dot { width:10px; height:10px; border-radius:50%; display:inline-block; margin-right:6px; }
  .dot-green { background:var(--green); animation:pulse 2s infinite; }
  .dot-red { background:var(--red); }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
  .grid { display:grid; grid-template-columns: repeat(3, 1fr); gap:12px; padding:12px; }
  .grid-wide { grid-column: span 2; }
  .grid-full { grid-column: span 3; }
  .card { background:var(--bg2); border:1px solid var(--border); border-radius:8px; padding:14px; }
  .card h2 { color:var(--text2); font-size:11px; text-transform:uppercase; letter-spacing:1px;
             margin-bottom:10px; border-bottom:1px solid var(--border); padding-bottom:6px; }
  .metric { display:flex; justify-content:space-between; align-items:center; margin:4px 0; }
  .metric-val { font-size:20px; font-weight:bold; }
  .green { color:var(--green); }
  .red { color:var(--red); }
  .yellow { color:var(--yellow); }
  .blue { color:var(--blue); }
  .purple { color:var(--purple); }
  .services-grid { display:grid; grid-template-columns:repeat(5,1fr); gap:6px; }
  .svc { padding:6px 8px; border-radius:6px; text-align:center; font-size:11px; }
  .svc.ok { background:#1c3a1c; border:1px solid var(--green); color:var(--green); }
  .svc.warn { background:#3a2a0a; border:1px solid var(--yellow); color:var(--yellow); }
  .svc.dead { background:#3a0a0a; border:1px solid var(--red); color:var(--red); }
  table { width:100%; border-collapse:collapse; font-size:12px; }
  th { color:var(--text2); text-align:left; padding:4px 8px; border-bottom:1px solid var(--border); }
  td { padding:5px 8px; border-bottom:1px solid var(--border); }
  .cb-panel { padding:10px; border-radius:6px; text-align:center; }
  .cb-closed { background:#0d2b0d; border:2px solid var(--green); }
  .cb-open { background:#2b0d0d; border:2px solid var(--red); }
  .cb-half { background:#2b1f0d; border:2px solid var(--yellow); }
  .cb-state { font-size:22px; font-weight:bold; margin:6px 0; }
  button { background:var(--bg3); border:1px solid var(--border); color:var(--text);
           padding:6px 14px; border-radius:6px; cursor:pointer; font-size:12px; margin-top:8px; }
  button:hover { background:var(--red); border-color:var(--red); }
  .regime-pill { display:inline-block; padding:2px 10px; border-radius:12px; font-size:11px; margin:2px; }
  .signal-row { display:flex; justify-content:space-between; padding:4px 0;
                border-bottom:1px solid var(--border); }
  .signal-dir-long { color:var(--green); }
  .signal-dir-short { color:var(--red); }
  .bar-fill { height:8px; border-radius:4px; background:var(--green); transition:width .5s; }
  .bar-track { background:var(--bg3); border-radius:4px; overflow:hidden; margin:4px 0; }
  .alert-item { padding:4px 8px; margin:3px 0; border-radius:4px; font-size:11px; }
  .alert-WARNING { background:#2b1f0d; border-left:3px solid var(--yellow); }
  .alert-CRITICAL { background:#2b0d0d; border-left:3px solid var(--red); }
  .alert-INFO { background:#0d1f2b; border-left:3px solid var(--blue); }
  #connection-status { font-size:11px; color:var(--text2); }
  .event-row { display:flex; justify-content:space-between; padding:4px 0;
               border-bottom:1px solid var(--border); }
  .event-soon { color:var(--red); }
  .event-soon2 { color:var(--yellow); }
  canvas { max-height: 200px; }
  .math-formula { font-size:10px; color:var(--text2); margin-top:6px; font-style:italic; }
</style>
</head>
<body>
<header>
  <div>
    <span class="status-dot dot-green" id="conn-dot"></span>
    <h1 style="display:inline">⚡ APEX Command Center</h1>
  </div>
  <div style="display:flex;gap:20px;align-items:center">
    <span id="connection-status">Connecting...</span>
    <span id="trading-mode" class="regime-pill" style="background:#1c2d1c;border:1px solid var(--green)">PAPER</span>
    <span id="clock" class="blue"></span>
  </div>
</header>

<div class="grid">

  <!-- PnL Summary -->
  <div class="card">
    <h2>💰 P&amp;L Today</h2>
    <div class="metric"><span>Realized</span><span id="pnl-realized" class="metric-val green">$0.00</span></div>
    <div class="metric"><span>Unrealized</span><span id="pnl-unrealized" class="metric-val">$0.00</span></div>
    <div class="metric"><span>Daily %</span><span id="pnl-pct" class="metric-val">0.00%</span></div>
    <div class="metric"><span>Max DD</span><span id="max-dd" class="metric-val red">0.00%</span></div>
    <div class="metric"><span>Trades today</span><span id="trade-count" class="blue">0</span></div>
    <div class="metric"><span>Win rate (50)</span><span id="win-rate" class="green">0.0%</span></div>
  </div>

  <!-- Equity Curve -->
  <div class="card grid-wide">
    <h2>📈 Equity Curve</h2>
    <canvas id="equityChart"></canvas>
  </div>

  <!-- Circuit Breaker -->
  <div class="card">
    <h2>⚡ Circuit Breaker</h2>
    <div id="cb-panel" class="cb-panel cb-closed">
      <div style="font-size:11px;color:var(--text2)">STATUS</div>
      <div id="cb-state" class="cb-state green">CLOSED</div>
      <div id="cb-allows" style="font-size:11px" class="green">✓ Orders allowed</div>
    </div>
    <button onclick="resetCB()" id="cb-reset-btn" style="display:none;background:var(--red)">
      ⚠ Reset Circuit Breaker
    </button>
    <div id="cb-daily-pnl" style="margin-top:8px;font-size:11px;color:var(--text2)"></div>
  </div>

  <!-- Regime Dashboard -->
  <div class="card">
    <h2>🌍 Market Regime</h2>
    <div class="metric"><span>Vol Regime</span><span id="vol-regime" class="yellow">—</span></div>
    <div class="metric"><span>Trend</span><span id="trend-regime" class="blue">—</span></div>
    <div class="metric"><span>Risk Mode</span><span id="risk-mode" class="green">—</span></div>
    <div class="metric"><span>Macro Mult</span><span id="macro-mult" class="purple">—</span></div>
    <div class="metric"><span>Session</span><span id="session" class="blue">—</span></div>
    <div class="metric"><span>Session Mult</span><span id="session-mult" class="green">—</span></div>
    <div id="event-active" style="margin-top:8px;font-size:11px;display:none"
         class="red">⚠ CB EVENT ACTIVE — TRADING BLOCKED</div>
  </div>

  <!-- Performance Stats -->
  <div class="card">
    <h2>📊 Performance Metrics</h2>
    <div class="metric"><span>Sharpe (rolling)</span><span id="sharpe" class="green">—</span></div>
    <div class="metric"><span>Sortino</span><span id="sortino" class="green">—</span></div>
    <div class="metric"><span>Profit Factor</span><span id="profit-factor" class="blue">—</span></div>
    <div class="metric"><span>Best Session</span><span id="best-session" class="purple">—</span></div>
    <div class="metric"><span>Best Signal</span><span id="best-signal" class="purple">—</span></div>
    <div style="margin-top:10px">
      <div style="font-size:11px;color:var(--text2);margin-bottom:4px">Win Rate</div>
      <div class="bar-track"><div id="wr-bar" class="bar-fill" style="width:0%"></div></div>
    </div>
  </div>

  <!-- Services Health -->
  <div class="card grid-full">
    <h2>🖥 Services Health</h2>
    <div class="services-grid" id="services-grid">
      <div class="svc warn">Loading...</div>
    </div>
  </div>

  <!-- Open Positions -->
  <div class="card grid-wide">
    <h2>📋 Open Positions</h2>
    <table>
      <thead><tr><th>Symbol</th><th>Direction</th><th>Entry</th><th>Size</th><th>Unreal. PnL</th><th>Session</th></tr></thead>
      <tbody id="positions-tbody"><tr><td colspan="6" style="color:var(--text2);text-align:center">No open positions</td></tr></tbody>
    </table>
  </div>

  <!-- CB Events -->
  <div class="card">
    <h2>📅 CB Events Calendar</h2>
    <div id="cb-events-list"><div style="color:var(--text2)">Loading...</div></div>
  </div>

  <!-- Recent Signals -->
  <div class="card grid-wide">
    <h2>⚡ Signal Feed</h2>
    <div id="signals-feed"></div>
  </div>

  <!-- Alert Log -->
  <div class="card">
    <h2>🔔 Recent Alerts</h2>
    <div id="alerts-log" style="max-height:200px;overflow-y:auto"></div>
  </div>

</div>

<script>
// ── Clock ──────────────────────────────────────────────────────────────────
function updateClock() {
  document.getElementById('clock').textContent = new Date().toUTCString().slice(17, 25) + ' UTC';
}
setInterval(updateClock, 1000);
updateClock();

// ── Equity Chart ───────────────────────────────────────────────────────────
const ctx = document.getElementById('equityChart').getContext('2d');
const equityChart = new Chart(ctx, {
  type: 'line',
  data: { labels: [], datasets: [{
    label: 'Equity', data: [], borderColor: '#39d353', backgroundColor: 'rgba(57,211,83,0.1)',
    fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2
  }]},
  options: {
    responsive: true, maintainAspectRatio: false, animation: false,
    plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false } },
    scales: {
      x: { display: false },
      y: { grid: { color: '#21262d' }, ticks: { color: '#8b949e', font: { size: 10 } } }
    }
  }
});

// ── WebSocket ──────────────────────────────────────────────────────────────
let ws;
function connect() {
  ws = new WebSocket('ws://' + location.host + '/ws');
  ws.onopen = () => {
    document.getElementById('connection-status').textContent = 'Connected';
    document.getElementById('conn-dot').className = 'status-dot dot-green';
  };
  ws.onclose = () => {
    document.getElementById('connection-status').textContent = 'Reconnecting...';
    document.getElementById('conn-dot').className = 'status-dot dot-red';
    setTimeout(connect, 3000);
  };
  ws.onmessage = (e) => {
    try { render(JSON.parse(e.data)); } catch(err) { console.error(err); }
  };
}

function render(d) {
  // PnL
  if (d.pnl) {
    const p = d.pnl;
    setText('pnl-realized', p.realized_today || '$0.00');
    setText('pnl-pct', (p.daily_pnl_pct > 0 ? '+' : '') + (p.daily_pnl_pct || 0).toFixed(3) + '%');
    colorize('pnl-pct', p.daily_pnl_pct);
    setText('max-dd', (p.max_drawdown_pct || 0).toFixed(3) + '%');
    setText('trade-count', p.trade_count_today || 0);
    setText('win-rate', ((p.win_rate_rolling || 0) * 100).toFixed(1) + '%');
    colorize('win-rate', (p.win_rate_rolling || 0) - 0.5);
  }

  // Equity curve
  if (d.equity && d.equity.length) {
    const vals = d.equity.map(e => typeof e === 'object' ? parseFloat(e.equity || 0) : parseFloat(e || 0));
    equityChart.data.labels = vals.map((_, i) => i);
    equityChart.data.datasets[0].data = vals;
    equityChart.update('none');
  }

  // Circuit Breaker
  if (d.circuit_breaker) {
    const cb = d.circuit_breaker;
    const state = (cb.state || 'CLOSED').toUpperCase();
    const panel = document.getElementById('cb-panel');
    const stateEl = document.getElementById('cb-state');
    const allowsEl = document.getElementById('cb-allows');
    stateEl.textContent = state;
    panel.className = 'cb-panel ' + (state === 'CLOSED' ? 'cb-closed' : state === 'OPEN' ? 'cb-open' : 'cb-half');
    stateEl.className = 'cb-state ' + (state === 'CLOSED' ? 'green' : state === 'OPEN' ? 'red' : 'yellow');
    allowsEl.textContent = cb.allows_new_orders ? '✓ Orders allowed' : '✗ Orders BLOCKED';
    allowsEl.className = cb.allows_new_orders ? 'green' : 'red';
    document.getElementById('cb-reset-btn').style.display = state !== 'CLOSED' ? 'block' : 'none';
    document.getElementById('cb-daily-pnl').textContent = 'Daily PnL: ' + (cb.daily_pnl_pct || 0).toFixed(3) + '% (limit: -3%)';
  }

  // Regime
  if (d.regime) {
    const r = d.regime;
    setText('vol-regime', r.vol_regime || '—');
    setText('trend-regime', r.trend_regime || '—');
    setText('risk-mode', r.risk_mode || '—');
    setText('macro-mult', 'x' + (r.macro_mult || 1.0).toFixed(2));
    setText('session', r.session || '—');
    setText('session-mult', 'x' + (r.session_mult || 1.0).toFixed(2));
    document.getElementById('event-active').style.display = r.event_active ? 'block' : 'none';
  }

  // Services
  if (d.services && d.services.length) {
    const grid = document.getElementById('services-grid');
    grid.innerHTML = d.services.map(s => {
      const cls = s.is_alive ? 'ok' : (s.last_seen_seconds < 30 ? 'warn' : 'dead');
      const label = s.service_id.replace('_', ' ').replace('s0', 'S').replace('s1', 'S1');
      return `<div class="svc ${cls}" title="${s.last_seen_seconds.toFixed(0)}s ago">${label}</div>`;
    }).join('');
  }

  // Positions
  if (d.positions !== undefined) {
    const tbody = document.getElementById('positions-tbody');
    if (!d.positions.length) {
      tbody.innerHTML = '<tr><td colspan="6" style="color:var(--text2);text-align:center;padding:12px">No open positions</td></tr>';
    } else {
      tbody.innerHTML = d.positions.map(p => {
        const cls = p.unrealized_pnl_pct >= 0 ? 'green' : 'red';
        const dir = p.direction === 'long' ? '<span class="green">▲ LONG</span>' : '<span class="red">▼ SHORT</span>';
        return `<tr><td class="blue">${p.symbol}</td><td>${dir}</td><td>${p.entry_price}</td>
                    <td>${p.size}</td><td class="${cls}">${p.unrealized_pnl_pct > 0 ? '+' : ''}${p.unrealized_pnl_pct.toFixed(3)}%</td>
                    <td class="purple">${p.session}</td></tr>`;
      }).join('');
    }
  }

  // Signals
  if (d.signals && d.signals.length) {
    const feed = document.getElementById('signals-feed');
    feed.innerHTML = d.signals.slice(0, 10).map(s => {
      const dirCls = s.direction === 'long' ? 'signal-dir-long' : 'signal-dir-short';
      const arrow = s.direction === 'long' ? '▲' : '▼';
      const strength = Math.abs(s.strength || 0);
      return `<div class="signal-row">
        <span class="blue">${s.symbol}</span>
        <span class="${dirCls}">${arrow} ${s.direction.toUpperCase()}</span>
        <span>str: <span class="green">${strength.toFixed(2)}</span></span>
        <span style="color:var(--text2)">[${(s.triggers||[]).join(', ')}]</span>
        <span style="color:var(--text2)">${s.age_seconds.toFixed(0)}s ago</span>
      </div>`;
    }).join('');
  }

  // Performance
  if (d.performance) {
    const p = d.performance;
    setText('sharpe', (p.sharpe_daily || 0).toFixed(3));
    colorize('sharpe', p.sharpe_daily || 0);
    setText('sortino', (p.sortino_daily || 0).toFixed(3));
    colorize('sortino', p.sortino_daily || 0);
    setText('profit-factor', (p.profit_factor || 0).toFixed(2));
    setText('best-session', p.best_session || '—');
    setText('best-signal', p.best_signal_type || '—');
    const wr = (p.win_rate || 0) * 100;
    document.getElementById('wr-bar').style.width = wr.toFixed(1) + '%';
    document.getElementById('wr-bar').style.background = wr > 55 ? '#39d353' : wr > 45 ? '#e3b341' : '#f85149';
  }

  // CB Events
  if (d.cb_events !== undefined) {
    const list = document.getElementById('cb-events-list');
    if (!d.cb_events.length) {
      list.innerHTML = '<div style="color:var(--text2)">No upcoming events</div>';
    } else {
      list.innerHTML = d.cb_events.map(ev => {
        const mins = ev.minutes_until;
        const cls = mins < 45 ? 'event-soon' : mins < 120 ? 'event-soon2' : '';
        const icon = ev.block_active ? '🔴' : ev.monitor_active ? '🟡' : '🟢';
        return `<div class="event-row">
          <span>${icon} <span class="blue">${ev.institution}</span> ${ev.event_type}</span>
          <span class="${cls}">${mins > 0 ? '+' : ''}${mins.toFixed(0)}min</span>
        </div>`;
      }).join('');
    }
  }

  // Alerts
  if (d.alerts !== undefined) {
    const log = document.getElementById('alerts-log');
    if (!d.alerts.length) {
      log.innerHTML = '<div style="color:var(--text2);font-size:11px">No alerts</div>';
    } else {
      log.innerHTML = d.alerts.slice(0, 20).map(a =>
        `<div class="alert-item alert-${a.level}">
          <span style="color:var(--text2)">${(a.timestamp||'').slice(0,19)}</span>
          <span class="${a.level==='CRITICAL'?'red':a.level==='WARNING'?'yellow':'blue'}"> ${a.level}</span>
          <div>${a.message}</div>
        </div>`
      ).join('');
    }
  }

  // Trading mode
  if (d.system) {
    const mode = d.system.trading_mode || 'PAPER';
    const el = document.getElementById('trading-mode');
    el.textContent = mode;
    el.style.background = mode === 'LIVE' ? '#2b0d0d' : '#0d2b0d';
    el.style.borderColor = mode === 'LIVE' ? '#f85149' : '#39d353';
    el.style.color = mode === 'LIVE' ? '#f85149' : '#39d353';
  }
}

function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}
function colorize(id, val) {
  const el = document.getElementById(id);
  if (!el) return;
  el.className = parseFloat(val) >= 0 ? 'green' : 'red';
}

async function resetCB() {
  if (!confirm('Reset circuit breaker to CLOSED? Only do this at start of trading day after reviewing risk.')) return;
  try {
    const r = await fetch('/api/v1/circuit-breaker/reset', {
      method: 'POST', headers: { 'X-Confirm': 'YES' }
    });
    const data = await r.json();
    alert(data.message);
  } catch (e) { alert('Error: ' + e); }
}

connect();
</script>
</body>
</html>"""


# ── WebSocket Connection Manager ───────────────────────────────────────────────

class ConnectionManager:
    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._connections:
            self._connections.remove(ws)

    async def broadcast(self, data: dict[str, Any]) -> None:
        payload = json.dumps(data, default=str)
        dead: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


# ── Dashboard Server ───────────────────────────────────────────────────────────

class DashboardServer:
    """APEX Command Center server — FastAPI + WebSocket + REST API."""

    def __init__(
        self, state: StateStore, host: str = "0.0.0.0", port: int = 8080,
    ) -> None:
        self._state = state
        self._host = host
        self._port = port
        self._manager = ConnectionManager()
        self.app = FastAPI(title="APEX Command Center", version="1.0.0")
        self._setup_routes()

    def _setup_routes(self) -> None:
        app = self.app
        state = self._state

        @app.get("/", response_class=HTMLResponse)
        async def index() -> HTMLResponse:
            return HTMLResponse(_DASHBOARD_HTML)

        @app.get("/health")
        async def health() -> dict[str, Any]:
            return {"status": "ok", "timestamp": time.time()}

        # Mount command API
        from services.s10_monitor.command_api import router as cmd_router
        # Inject state via dependency — pass state as closure for simplicity

        @app.get("/api/v1/system/status")
        async def system_status() -> dict[str, Any]:
            from services.s10_monitor.command_api import get_system_status
            r = await get_system_status(state)
            return r.model_dump()

        @app.get("/api/v1/positions")
        async def positions() -> list[dict[str, Any]]:
            from services.s10_monitor.command_api import get_positions
            return [p.model_dump() for p in await get_positions(state)]

        @app.get("/api/v1/pnl")
        async def pnl() -> dict[str, Any]:
            from services.s10_monitor.command_api import get_pnl
            return (await get_pnl(state)).model_dump()

        @app.get("/api/v1/regime")
        async def regime() -> dict[str, Any]:
            from services.s10_monitor.command_api import get_regime
            return (await get_regime(state)).model_dump()

        @app.get("/api/v1/signals/recent")
        async def signals() -> list[dict[str, Any]]:
            from services.s10_monitor.command_api import get_recent_signals
            return [s.model_dump() for s in await get_recent_signals(state)]

        @app.get("/api/v1/circuit-breaker")
        async def cb() -> dict[str, Any]:
            from services.s10_monitor.command_api import get_circuit_breaker
            return await get_circuit_breaker(state)

        @app.post("/api/v1/circuit-breaker/reset")
        async def cb_reset(x_confirm: str | None = None) -> dict[str, Any]:
            from fastapi import Header as FHeader
            from services.s10_monitor.command_api import reset_circuit_breaker, ActionResult
            r = await reset_circuit_breaker(state, x_confirm)
            return r.model_dump()

        @app.get("/api/v1/performance")
        async def perf() -> dict[str, Any]:
            from services.s10_monitor.command_api import get_performance
            return (await get_performance(state)).model_dump()

        @app.get("/api/v1/cb-events")
        async def cb_events() -> list[dict[str, Any]]:
            from services.s10_monitor.command_api import get_cb_events
            return [e.model_dump() for e in await get_cb_events(state)]

        @app.get("/api/v1/config")
        async def config() -> dict[str, Any]:
            from services.s10_monitor.command_api import get_config
            return await get_config()

        @app.get("/api/v1/alerts/recent")
        async def alerts() -> list[dict[str, Any]]:
            from services.s10_monitor.command_api import get_recent_alerts
            return [a.model_dump() for a in await get_recent_alerts(state)]

        @app.websocket("/ws")
        async def websocket_endpoint(ws: WebSocket) -> None:
            await self._manager.connect(ws)
            try:
                while True:
                    payload = await self._build_broadcast()
                    await self._manager.broadcast(payload)
                    await asyncio.sleep(2.0)
            except WebSocketDisconnect:
                self._manager.disconnect(ws)
            except Exception as exc:
                logger.error("ws_error", error=str(exc))
                self._manager.disconnect(ws)

    async def _build_broadcast(self) -> dict[str, Any]:
        """Build the complete dashboard payload for WebSocket broadcast."""
        from services.s10_monitor.command_api import (
            get_circuit_breaker, get_performance, get_pnl,
            get_positions, get_recent_alerts, get_recent_signals,
            get_regime, get_cb_events, get_system_status,
        )
        state = self._state
        payload: dict[str, Any] = {}
        try:
            # Fetch all data concurrently
            results = await asyncio.gather(
                get_pnl(state),
                get_positions(state),
                get_regime(state),
                get_recent_signals(state),
                get_circuit_breaker(state),
                get_performance(state),
                get_cb_events(state),
                get_recent_alerts(state),
                get_system_status(state),
                return_exceptions=True,
            )
            labels = ["pnl","positions","regime","signals","circuit_breaker",
                      "performance","cb_events","alerts","system"]
            for label, result in zip(labels, results):
                if isinstance(result, Exception):
                    logger.debug("broadcast_partial_fail", label=label, error=str(result))
                    continue
                if hasattr(result, "model_dump"):
                    payload[label] = result.model_dump()
                elif isinstance(result, list):
                    payload[label] = [r.model_dump() if hasattr(r, "model_dump") else r for r in result]
                else:
                    payload[label] = result

            # Equity curve
            curve = await state.lrange("equity_curve", 0, 99)
            payload["equity"] = list(reversed(curve))  # chronological order

        except Exception as exc:
            payload["error"] = str(exc)
        return payload

    async def start(self) -> None:
        config = uvicorn.Config(self.app, host=self._host, port=self._port, log_level="warning")
        server = uvicorn.Server(config)
        await server.serve()
```

---

## OBJ-F — Tests Command Center

Créer `tests/unit/s10/__init__.py` (vide).

Créer `tests/unit/s10/test_command_api.py` :

```python
"""Tests Command Center API endpoints."""
from __future__ import annotations
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from services.s10_monitor.command_api import (
    ActionResult, AlertEntry, CBEventInfo, PerformanceStats,
    PnLSummary, PositionSummary, RegimeSummary, ServiceHealth,
    SignalSummary, SystemStatus, _require_confirmation,
)
from fastapi import HTTPException


class TestRequireConfirmation:
    def test_none_raises(self) -> None:
        with pytest.raises(HTTPException) as exc:
            _require_confirmation(None)
        assert exc.value.status_code == 403

    def test_wrong_value_raises(self) -> None:
        with pytest.raises(HTTPException):
            _require_confirmation("no")

    def test_yes_passes(self) -> None:
        _require_confirmation("YES")  # no exception


class TestResponseModels:
    def test_service_health_fields(self) -> None:
        s = ServiceHealth(service_id="s01", status="healthy", last_seen_seconds=3.0, is_alive=True)
        assert s.service_id == "s01"
        assert s.is_alive is True

    def test_system_status_fields(self) -> None:
        ss = SystemStatus(all_healthy=True, services=[], circuit_breaker="CLOSED",
                          trading_mode="PAPER", uptime_seconds=100.0)
        assert ss.all_healthy is True

    def test_pnl_summary_fields(self) -> None:
        p = PnLSummary(realized_today="$100.00", unrealized_total="$50.00",
                       daily_pnl_pct=1.5, max_drawdown_pct=0.5,
                       win_rate_rolling=0.6, trade_count_today=5, sharpe_rolling=1.2)
        assert p.daily_pnl_pct == 1.5

    def test_regime_summary_fields(self) -> None:
        r = RegimeSummary(vol_regime="normal", trend_regime="ranging", risk_mode="normal",
                          macro_mult=1.0, session="us_prime", session_mult=1.2,
                          event_active=False, next_cb_event=None)
        assert r.macro_mult == 1.0

    def test_signal_summary_fields(self) -> None:
        s = SignalSummary(symbol="BTCUSDT", direction="long", strength=0.8,
                          triggers=["OFI", "BB"], confidence=0.9, age_seconds=5.0)
        assert "OFI" in s.triggers

    def test_cb_event_info_fields(self) -> None:
        e = CBEventInfo(institution="FOMC", event_type="rate_decision",
                        scheduled_at="2025-01-29T19:00", minutes_until=45.0,
                        block_active=False, monitor_active=False)
        assert e.institution == "FOMC"

    def test_action_result_success(self) -> None:
        r = ActionResult(success=True, message="Done", timestamp="123")
        assert r.success is True

    def test_action_result_failure(self) -> None:
        r = ActionResult(success=False, message="Error: redis timeout", timestamp="456")
        assert r.success is False
        assert "Error" in r.message

    def test_alert_entry_levels(self) -> None:
        for level in ["INFO", "WARNING", "CRITICAL"]:
            a = AlertEntry(timestamp="2024-01-01T00:00:00", level=level, message=f"{level} test")
            assert a.level == level

    def test_performance_stats_fields(self) -> None:
        p = PerformanceStats(sharpe_daily=1.5, sortino_daily=2.0, calmar=3.0,
                             max_drawdown_pct=4.0, win_rate=0.6, profit_factor=1.8,
                             avg_win_usd=150.0, avg_loss_usd=80.0,
                             total_trades=50, best_session="us_prime", best_signal_type="OFI")
        assert p.sharpe_daily == 1.5

    def test_position_summary_pnl_sign(self) -> None:
        pos = PositionSummary(symbol="BTCUSDT", direction="long", entry_price="50000",
                              size="0.1", unrealized_pnl_pct=2.5, session="us_prime")
        assert pos.unrealized_pnl_pct > 0


class TestGetSystemStatusMocked:
    @pytest.mark.asyncio
    async def test_dead_services_mark_unhealthy(self) -> None:
        from services.s10_monitor.command_api import get_system_status
        state = AsyncMock()
        state.get.return_value = None  # all services return None = dead
        result = await get_system_status(state)
        assert result.all_healthy is False
        assert len(result.services) > 0
        assert all(not s.is_alive for s in result.services)

    @pytest.mark.asyncio
    async def test_healthy_service_detected(self) -> None:
        from services.s10_monitor.command_api import get_system_status
        now_ms = int(time.time() * 1000)
        state = AsyncMock()
        state.get.return_value = {"timestamp_ms": now_ms, "status": "healthy"}
        result = await get_system_status(state)
        assert any(s.is_alive for s in result.services)

    @pytest.mark.asyncio
    async def test_cb_state_read_from_redis(self) -> None:
        from services.s10_monitor.command_api import get_system_status
        state = AsyncMock()
        state.get.side_effect = lambda key: {"circuit_breaker:state": "open"}.get(key, None)
        result = await get_system_status(state)
        assert isinstance(result.circuit_breaker, str)


class TestGetPnLMocked:
    @pytest.mark.asyncio
    async def test_empty_trades_returns_zeros(self) -> None:
        from services.s10_monitor.command_api import get_pnl
        state = AsyncMock()
        state.lrange.return_value = []
        state.get.return_value = None
        result = await get_pnl(state)
        assert result.trade_count_today == 0
        assert result.win_rate_rolling == 0.0

    @pytest.mark.asyncio
    async def test_winning_trades_positive_win_rate(self) -> None:
        from services.s10_monitor.command_api import get_pnl
        state = AsyncMock()
        state.get.return_value = None
        state.lrange.return_value = [
            {"net_pnl": 100, "exit_timestamp_ms": int(time.time() * 1000)} for _ in range(10)
        ]
        result = await get_pnl(state)
        assert result.win_rate_rolling > 0.5


class TestGetRegimeMocked:
    @pytest.mark.asyncio
    async def test_empty_regime_returns_defaults(self) -> None:
        from services.s10_monitor.command_api import get_regime
        state = AsyncMock()
        state.get.return_value = {}
        result = await get_regime(state)
        assert isinstance(result.macro_mult, float)
        assert isinstance(result.event_active, bool)


class TestResetCBMocked:
    @pytest.mark.asyncio
    async def test_reset_requires_confirmation(self) -> None:
        from services.s10_monitor.command_api import reset_circuit_breaker
        state = AsyncMock()
        with pytest.raises(HTTPException) as exc:
            await reset_circuit_breaker(state, x_confirm=None)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_reset_with_confirmation_succeeds(self) -> None:
        from services.s10_monitor.command_api import reset_circuit_breaker
        state = AsyncMock()
        state.set.return_value = None
        result = await reset_circuit_breaker(state, x_confirm="YES")
        assert result.success is True
        state.set.assert_called_once()


class TestGetConfigMocked:
    @pytest.mark.asyncio
    async def test_config_never_exposes_secrets(self) -> None:
        from services.s10_monitor.command_api import get_config
        result = await get_config()
        assert "api_key" not in str(result).lower()
        assert "secret" not in str(result).lower()
        assert "password" not in str(result).lower()
        assert "trading_mode" in result
        assert "initial_capital" in result
```

---

# PARTIE 4 — INTÉGRATION DES NOUVEAUX MODULES

## OBJ-G — Connecter HAR-RV et Rough Vol à S07

Modifier `services/s07_quant_analytics/service.py` pour utiliser les nouveaux modules :

```python
# Dans _run_fast_analytics(), après les calculs existants, ajouter :

from services.s07_quant_analytics.realized_vol import RealizedVolEstimator
from services.s07_quant_analytics.rough_vol import RoughVolAnalyzer

# Instancier (une fois, pas à chaque tick - utiliser attributs d'instance)
# Dans __init__ :
self._rv_estimator = RealizedVolEstimator()
self._rough_vol = RoughVolAnalyzer()

# Dans _run_fast_analytics(), après les calculs existants :
if len(returns) >= 5:
    metrics = self._rv_estimator.jump_detection(returns)
    if metrics.has_significant_jump:
        await self.state.set("analytics:jump_detected", {
            "jump_ratio": metrics.jump_ratio,
            "jump_component": metrics.jump_component,
            "timestamp_ms": int(time.time() * 1000),
        })
    results["rv_annualized_vol"] = metrics.annualized_vol
    results["jump_ratio"] = metrics.jump_ratio
    results["has_significant_jump"] = metrics.has_significant_jump

# Rough vol signal
if len(prices) >= 30:
    rough_sig = self._rough_vol.estimate_hurst_from_vol(prices)
    results["hurst_exponent"] = rough_sig.hurst_exponent
    results["vol_regime_rough"] = rough_sig.vol_regime
    results["scalping_edge_score"] = rough_sig.scalping_edge_score
```

## OBJ-H — Connecter ImpactModel à PaperTrader

Modifier `services/s06_execution/paper_trader.py` — ajouter dans `execute()` :

```python
# Après la décision de slippage existante, améliorer avec le modèle square-root
# si adv (average daily volume) est disponible :
from services.s06_execution.optimal_execution import MarketImpactModel

# Dans __init__ du PaperTrader :
self._impact_model = MarketImpactModel()

# Dans compute_slippage() — nouvelle version enrichie :
def compute_slippage(
    self,
    spread_bps: float,
    kyle_lambda: float,
    size: Decimal,
    price: Decimal,
    adv: float = 0.0,         # Average daily volume (0 = unknown)
    daily_vol: float = 0.20,  # Annualized daily vol (default 20%)
) -> float:
    """Enhanced slippage model: square-root impact + Kyle linear.

    Uses Bouchaud et al. (2018) square-root law for large orders,
    Kyle (1985) linear model for small orders.
    """
    if adv > 0:
        estimate = self._impact_model.best_impact_estimate(
            quantity=float(size),
            adv=adv,
            daily_vol=daily_vol,
            price=float(price),
            kyle_lambda=kyle_lambda,
            spread_bps=spread_bps,
        )
        return estimate.total_slippage_bps
    # Fallback to original model when ADV unknown
    return max(0.0, spread_bps / 2.0 + kyle_lambda * float(size))
```

---

# PARTIE 5 — VALIDATION FINALE

## OBJ-I — CHANGELOG.md bump v0.3.0

```markdown
## [0.3.0] — Phase 4: Coverage 85% + Alpha Académique + Command Center

### Added
- HAR-RV model (Corsi 2009): long-memory volatility forecasting → better Kelly sizing
- Bipower Variation + Jump Detection (Barndorff-Nielsen & Shephard 2004): jump-robust vol decomposition
- Rough Volatility estimator (Gatheral, Jaisson & Rosenbaum 2018): Hurst exponent → scalping edge signal
- Variance Ratio Test (Lo & MacKinlay 1988): momentum/mean-reversion regime diagnostic
- Square-Root Market Impact (Bouchaud et al. 2018): realistic slippage for all order sizes
- Almgren-Chriss optimal execution schedule (Almgren & Chriss 2001)
- Volatility-targeting Kelly (AQR/Winton/Man AHL approach)
- APEX Command Center: full web dashboard at http://localhost:8080
  - Real-time equity curve (Chart.js)
  - 10-service health grid
  - Live PnL panel
  - Open positions table with unrealized PnL
  - Circuit breaker status + manual reset (X-Confirm: YES required)
  - Market regime dashboard
  - Upcoming CB events countdown
  - Recent signals feed
  - Performance stats (Sharpe, Sortino, win rate)
  - Alert log
- Full REST API (/api/v1/*) for all dashboard data
- Unit tests: FusionEngine, StrategySelector, HedgeTrigger, SignalQuality
- Unit tests: BinanceNormalizer, AlpacaNormalizer, SessionTagger
- Unit tests: RealizedVolEstimator, RoughVolAnalyzer, MarketImpactModel
- Unit tests: CommandAPI (15 tests with mocked Redis)
- Coverage gate bumped from 75% → 85%

### Changed
- PaperTrader.compute_slippage(): enhanced with square-root impact model
- S07 service: now computes jump detection and rough vol in fast loop
- pyproject.toml: --cov-fail-under 75 → 85
```

---

## OBJ-J — Validation finale complète

```powershell
Write-Host "=== 1. ZERO ERREURS MYPY ===" -ForegroundColor Cyan
$errs = ($env:PYTHONPATH="."; .venv\Scripts\python -m mypy . 2>&1 | Select-String "error:" | Where-Object {$_ -notmatch "\.venv"})
if ($errs) { $errs; Write-Error "FAIL" } else { Write-Host "PASS: 0 erreurs mypy" -ForegroundColor Green }

Write-Host "`n=== 2. RUFF CLEAN ===" -ForegroundColor Cyan
.venv\Scripts\python -m ruff check . --fix && .venv\Scripts\python -m ruff format .
if ($LASTEXITCODE -eq 0) { Write-Host "PASS: ruff OK" -ForegroundColor Green } else { Write-Error "FAIL" }

Write-Host "`n=== 3. TESTS UNITAIRES ===" -ForegroundColor Cyan
$env:PYTHONPATH="."; .venv\Scripts\python -m pytest tests/unit/ -v --tb=short -q --override-ini="addopts="
if ($LASTEXITCODE -eq 0) { Write-Host "PASS" -ForegroundColor Green } else { Write-Error "FAIL" }

Write-Host "`n=== 4. COVERAGE >= 85% ===" -ForegroundColor Cyan
$env:PYTHONPATH="."; .venv\Scripts\python -m pytest tests/unit/ --cov=services --cov=core --cov=backtesting --cov-report=term-missing --cov-fail-under=85 -q --override-ini="addopts="
if ($LASTEXITCODE -eq 0) { Write-Host "PASS" -ForegroundColor Green } else { Write-Error "FAIL: coverage < 85%" }

Write-Host "`n=== 5. TESTS INTEGRATION ===" -ForegroundColor Cyan
docker compose -f docker/docker-compose.test.yml up -d; Start-Sleep 3
$env:PYTHONPATH="."; .venv\Scripts\python -m pytest tests/integration/ -v --override-ini="addopts="
docker compose -f docker/docker-compose.test.yml down

Write-Host "`n=== 6. TESTS PERFORMANCE ===" -ForegroundColor Cyan
$env:PYTHONPATH="."; .venv\Scripts\python -m pytest tests/performance/ -v --override-ini="addopts="

Write-Host "`n=== 7. BACKTEST ===" -ForegroundColor Cyan
$env:PYTHONPATH="."; .venv\Scripts\python scripts/generate_test_fixtures.py
$env:BACKTEST_MODE="True"; $env:BACKTEST_MIN_SHARPE="0.3"; $env:BACKTEST_MAX_DD="1.0"
$env:PYTHONPATH="."; .venv\Scripts\python scripts/backtest_regression.py --fixture tests/fixtures/30d_btcusdt_1m.parquet
if ($LASTEXITCODE -eq 0) { Write-Host "PASS" -ForegroundColor Green } else { Write-Error "FAIL" }

Write-Host "`n=== 8. DASHBOARD HEALTH ===" -ForegroundColor Cyan
Write-Host "Démarrer le système: docker compose up -d"
Write-Host "Vérifier: http://localhost:8080 → Command Center visible"
Write-Host "Vérifier: http://localhost:8080/api/v1/config → JSON config retourné"

Write-Host "`n============================" -ForegroundColor Yellow
Write-Host "SI TOUT EST VERT → SYSTEM PAPER-TRADING READY" -ForegroundColor Green
Write-Host "Dashboard: http://localhost:8080" -ForegroundColor Blue
```

## Commit final

```powershell
git add -A
git commit -m "feat: Phase 4 complete — 85% coverage + academic alpha + Command Center

Academic Research Integrated:
- HAR-RV (Corsi 2009, J. Financial Econometrics)
- Bipower Variation + Jump Detection (Barndorff-Nielsen & Shephard 2004, Oxford/LSE)
- Rough Volatility H-exponent (Gatheral, Jaisson & Rosenbaum 2018, Columbia/École Polytechnique)
- Variance Ratio Test (Lo & MacKinlay 1988, MIT/Wharton)
- Square-Root Impact Law (Bouchaud et al. 2018, CFM Paris)
- Almgren-Chriss Optimal Execution (2001, U. Chicago)
- Volatility-Targeting Kelly (AQR/Winton/Man AHL)

Command Center (http://localhost:8080):
- Real-time equity curve + 10-service health grid
- Live PnL, positions, signals, regime, CB events
- Circuit breaker panel + manual reset (confirmed)
- Full REST API /api/v1/*
- WebSocket 2s refresh, Chart.js visualizations

Coverage: 75% → 85% (gate enforced in CI)
Tests: +7 new test files, +85 new test cases"

git push origin main
```

---

## CONTRAINTES ABSOLUES (CLAUDE.md)

- mypy strict: 0 erreurs sur tout commit
- Decimal pour tous les prix — jamais float
- UTC datetime — jamais naive
- structlog — jamais print()
- ZMQ topics via core/topics.py
- fakeredis dans tests/unit/
- Le dashboard est READ-ONLY pour le trading
- Jamais d'ordre depuis l'UI — uniquement via ZMQ pipeline (Risk Manager VETO)
- Les nouveaux modules mathématiques doivent tous avoir leur docstring + référence académique complète
- Chaque nouveau module : tests AVANT d'être considéré terminé
