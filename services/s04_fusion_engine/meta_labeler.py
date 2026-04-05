import typing

"""Meta-Labeling for APEX — S04 Fusion Engine.

Meta-labeling (López de Prado 2018, Chapter 3) separates two concerns:

    Primary model (S02 SignalScorer): direction → LONG or SHORT
    Meta-labeler (this module):       binary   → TRADE (1) or NO-TRADE (0)

The meta-labeler learns WHEN to trust the primary model's direction signal.
It does NOT predict direction — it predicts signal reliability / trade viability.

Architecture (Phase 5 = deterministic rules, Phase 6 = trained binary classifier):

    8 features → weighted soft score → threshold → TRADE/NO-TRADE + size_mult

Hard blocks (instant veto, bypasses soft scoring):
    VPIN >= 0.90    : extreme flow toxicity, flash crash risk
    macro_mult <= 0 : crisis regime, system-wide halt ordered by S03
    spread > 50 bps : transaction costs exceed expected edge

Soft scoring (weighted sum → meta_score ∈ [-1, +1]):
    signal_strength  : primary model confidence
    n_triggers       : number of confluent signal sources
    hurst_exponent   : market roughness (low H = trending = more predictable)
    vpin             : flow toxicity (negative weight — high VPIN penalises)
    har_rv_vol       : HAR-RV volatility regime fitness [0.10, 0.30] optimal
    spread_bps       : transaction cost viability
    session × macro  : timing quality composite

Calibration targets (Phase 5 baseline):
    Precision > 0.60  (60 % win rate on approved signals)
    Recall    > 0.70  (capture 70 % of true opportunities)

Phase 6 upgrade path: replace MetaLabeler.score() with a trained logistic
regression or GBM on the MetaFeatureLogger dataset. Interface stays identical.

References:
    López de Prado, M. (2018). Advances in Financial Machine Learning.
        Wiley. Chapter 3: Labeling, Section 3.6 (Meta-Labeling).
        Cornell University → AQR Capital Management.
    López de Prado, M. (2019). A Data Science Solution to the
        Multiple-Testing Crisis in Financial Research.
        Journal of Financial Data Science 1(1), 94-110. AQR Capital.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class MetaFeatures:
    """Feature vector for the meta-labeling classifier.

    All features are floats in predictable ranges to allow future scaling
    for a supervised binary classifier (MetaLabeler v2).

    Attributes:
        signal_strength:      |strength| ∈ [0, 1] from S02 primary model.
        n_triggers:           Number of confluent signal sources (1-5+).
        hurst_exponent:       H ∈ (0, 0.5) from S07 rough vol estimate.
        vpin:                 Flow toxicity ∈ [0, 1] from S02 VPIN calculator.
        har_rv_forecast_vol:  HAR-RV annualised volatility from S07.
        spread_bps:           Bid-ask spread in basis points.
        session_mult:         Session timing multiplier from S03.
        macro_mult:           Macro regime multiplier ∈ [0, 1] from S03.
        kyle_lambda:          Kyle λ market impact coefficient from S07.
    """

    signal_strength: float
    n_triggers: int
    hurst_exponent: float
    vpin: float
    har_rv_forecast_vol: float
    spread_bps: float
    session_mult: float
    macro_mult: float
    kyle_lambda: float


@dataclass
class MetaLabelDecision:
    """Output of the meta-labeling layer.

    Attributes:
        should_trade:        True → forward to Risk Manager; False → drop.
        confidence:          Decision confidence ∈ [0, 1].
        blocking_reason:     Non-None only when should_trade is False.
        adjusted_size_mult:  Final Kelly size multiplier ∈ [0, 1].
        meta_score:          Raw weighted score ∈ [-1, +1].
    """

    should_trade: bool
    confidence: float
    blocking_reason: str | None
    adjusted_size_mult: float
    meta_score: float


class MetaLabeler:
    """Rule-based meta-labeler for S04 Fusion Engine (Phase 5).

    Phase 5 uses deterministic weighted rules. Phase 6 replaces score()
    with a trained logistic regression on the MetaFeatureLogger dataset.
    The public interface (score, get_features_from_redis) remains unchanged.

    Class attributes:
        TRADE_THRESHOLD: Minimum meta_score to approve a trade.
        WEIGHTS:         Feature weights summing to 1.0.
    """

    TRADE_THRESHOLD: float = 0.15

    WEIGHTS: typing.ClassVar[dict[str, float]] = {
        "signal_strength": 0.25,
        "confluence": 0.20,
        "hurst": 0.15,
        "vpin": 0.20,
        "vol_regime": 0.10,
        "spread": 0.05,
        "regime": 0.05,
    }

    def score(self, f: MetaFeatures) -> MetaLabelDecision:
        """Score a MetaFeatures vector and return a TRADE/NO-TRADE decision.

        Hard blocks are evaluated first and bypass the soft scoring entirely.

        Args:
            f: Feature vector extracted from the current system state.

        Returns:
            :class:`MetaLabelDecision` with trade approval and size multiplier.
        """
        # ── Hard blocks (veto — bypasses soft scoring) ────────────────────────
        if f.vpin >= 0.90:
            return MetaLabelDecision(
                should_trade=False,
                confidence=0.0,
                blocking_reason="VPIN extreme (≥0.90): flash crash risk",
                adjusted_size_mult=0.0,
                meta_score=-1.0,
            )
        if f.macro_mult <= 0.0:
            return MetaLabelDecision(
                should_trade=False,
                confidence=0.0,
                blocking_reason="Crisis regime (macro_mult=0): system halt",
                adjusted_size_mult=0.0,
                meta_score=-1.0,
            )
        if f.spread_bps > 50.0:
            return MetaLabelDecision(
                should_trade=False,
                confidence=0.0,
                blocking_reason=f"Spread {f.spread_bps:.1f}bps > 50: not viable",
                adjusted_size_mult=0.0,
                meta_score=-1.0,
            )

        # ── Soft scoring (weighted sum) ───────────────────────────────────────
        meta_score = 0.0

        # Signal strength: strength=1.0 → +0.25, strength=0.25 → 0
        meta_score += self.WEIGHTS["signal_strength"] * (f.signal_strength * 2.0 - 0.5)

        # Confluence: 1 trigger = bad, 3 = good, 4+ = great
        conf_map = {1: -0.5, 2: 0.5, 3: 0.8}
        conf_score = conf_map.get(f.n_triggers, 1.0 if f.n_triggers >= 4 else -0.5)
        meta_score += self.WEIGHTS["confluence"] * conf_score

        # Hurst: H=0 → +1 (trending), H=0.5 → -1 (random walk)
        hurst_s = max(-1.0, min(1.0, 1.0 - f.hurst_exponent / 0.5 * 2.0))
        meta_score += self.WEIGHTS["hurst"] * hurst_s

        # VPIN: high toxicity penalises score (negative weight)
        meta_score += self.WEIGHTS["vpin"] * (-(f.vpin * 2.0 - 1.0))

        # Vol regime: optimal window [10%, 30%], penalise extremes
        v = f.har_rv_forecast_vol
        if 0.10 <= v <= 0.30:
            vol_s = 1.0
        elif 0.05 <= v < 0.10 or 0.30 < v <= 0.50:
            vol_s = 0.0
        else:
            vol_s = -1.0
        meta_score += self.WEIGHTS["vol_regime"] * vol_s

        # Spread: ≤5 bps = full credit, linearly penalised up to 50 bps
        spread_s = (
            1.0 if f.spread_bps <= 5
            else max(-1.0, 1.0 - (f.spread_bps - 5.0) / 15.0)
        )
        meta_score += self.WEIGHTS["spread"] * spread_s

        # Regime composite: session × macro quality
        regime_s = min(1.0, (f.session_mult / 1.5) * f.macro_mult) * 2.0 - 1.0
        meta_score += self.WEIGHTS["regime"] * regime_s

        # Clamp meta_score to ensure mathematically bounded output [-1.0, +1.0]
        meta_score = max(-1.0, min(1.0, meta_score))

        # ── Decision ──────────────────────────────────────────────────────────
        confidence = max(0.0, min(1.0, (meta_score + 1.0) / 2.0))
        size_mult = min(
            1.0,
            confidence
            * max(0.1, 1.0 - f.vpin)
            * max(0.5, 1.0 - f.spread_bps / 100.0)
            * f.macro_mult,
        )
        should_trade = meta_score >= self.TRADE_THRESHOLD
        blocking_reason = (
            None
            if should_trade
            else f"Score {meta_score:.3f} < threshold {self.TRADE_THRESHOLD}"
        )

        return MetaLabelDecision(
            should_trade=should_trade,
            confidence=confidence,
            blocking_reason=blocking_reason,
            adjusted_size_mult=size_mult,
            meta_score=round(meta_score, 4),
        )

    def get_features_from_redis(
        self,
        symbol: str,
        redis_data: dict[str, Any],
    ) -> MetaFeatures:
        """Build MetaFeatures from aggregated Redis state for use in FusionEngine.

        Reads from the following Redis keys (expected in redis_data dict):
            ``vpin:{symbol}``        — VPIN metrics from S02
            ``analytics:fast``       — Hurst, RV, Kyle λ from S07
            ``regime:current``       — Macro/session multipliers from S03
            ``signal:{symbol}``      — Signal strength and triggers from S02

        Args:
            symbol:     Trading symbol, e.g. ``'BTCUSDT'``.
            redis_data: Dict mapping Redis key → parsed value.

        Returns:
            :class:`MetaFeatures` populated with safe defaults for missing keys.
        """
        vpin: dict[str, Any] = redis_data.get(f"vpin:{symbol}") or {}
        analytics: dict[str, Any] = redis_data.get("analytics:fast") or {}
        raw_regime = redis_data.get("regime:current")
        regime: dict[str, Any] = raw_regime if isinstance(raw_regime, dict) else {}
        raw_signal = redis_data.get(f"signal:{symbol}")
        signal: dict[str, Any] = raw_signal if isinstance(raw_signal, dict) else {}
        raw_session = regime.get("session")
        session: dict[str, Any] = raw_session if isinstance(raw_session, dict) else {}
        raw_feats = signal.get("features")
        feats: dict[str, Any] = raw_feats if isinstance(raw_feats, dict) else {}

        return MetaFeatures(
            signal_strength=float(abs(signal.get("strength", 0.5) or 0.5)),
            n_triggers=len(signal.get("triggers", []) or []),
            hurst_exponent=float(analytics.get("hurst_exponent", 0.3) or 0.3),
            vpin=float(vpin.get("vpin", 0.5) or 0.5),
            har_rv_forecast_vol=float(
                analytics.get("rv_annualized_vol", 0.20) or 0.20
            ),
            spread_bps=float(feats.get("spread_bps", 5.0) or 5.0),
            session_mult=float(session.get("session_mult", 1.0) or 1.0),
            macro_mult=float(regime.get("macro_mult", 1.0) or 1.0),
            kyle_lambda=float(analytics.get("kyle_lambda", 0.0) or 0.0),
        )
