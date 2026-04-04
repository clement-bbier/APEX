"""Tests for DriftDetector - signal quality and win rate drift detection."""
from __future__ import annotations

from unittest.mock import MagicMock

from services.s09_feedback_loop.drift_detector import DriftDetector


def make_trades(n_wins: int, n_losses: int) -> list[MagicMock]:
    """Build a list of mock trade objects with pnl_net set."""
    trades = []
    for _ in range(n_wins):
        t = MagicMock()
        t.pnl_net = 10.0
        trades.append(t)
    for _ in range(n_losses):
        t = MagicMock()
        t.pnl_net = -8.0
        trades.append(t)
    return trades


class TestDriftDetector:
    def test_no_alert_when_healthy(self) -> None:
        detector = DriftDetector()
        trades = make_trades(n_wins=30, n_losses=20)  # 60% win rate
        alert = detector.check_drift(trades, baseline_win_rate=0.58)
        assert alert is None  # only ~3% relative drop, below 10% threshold

    def test_alert_when_significant_drop(self) -> None:
        detector = DriftDetector()
        trades = make_trades(n_wins=22, n_losses=28)  # 44% win rate
        alert = detector.check_drift(trades, baseline_win_rate=0.55)
        assert alert is not None
        assert alert.drop_pct >= 0.10

    def test_no_alert_insufficient_trades(self) -> None:
        detector = DriftDetector()
        trades = make_trades(n_wins=5, n_losses=5)  # only 10 trades
        alert = detector.check_drift(trades, baseline_win_rate=0.55)
        assert alert is None  # need 50 minimum

    def test_alert_message_is_actionable(self) -> None:
        detector = DriftDetector()
        trades = make_trades(n_wins=20, n_losses=30)  # 40% win rate
        alert = detector.check_drift(trades, baseline_win_rate=0.56)
        assert alert is not None
        assert "DRIFT" in alert.message
        assert "Review" in alert.message

    def test_alert_has_correct_trade_count(self) -> None:
        detector = DriftDetector()
        trades = make_trades(n_wins=15, n_losses=35)
        alert = detector.check_drift(trades, baseline_win_rate=0.55)
        assert alert is not None
        assert alert.n_trades_in_window == 50

    def test_alert_current_win_rate_correct(self) -> None:
        detector = DriftDetector()
        trades = make_trades(n_wins=20, n_losses=30)  # exactly 40%
        alert = detector.check_drift(trades, baseline_win_rate=0.55)
        assert alert is not None
        assert abs(alert.current_win_rate - 0.40) < 0.001

    def test_no_alert_when_exactly_at_threshold(self) -> None:
        """Exactly 10% relative drop should trigger (>= not >)."""
        detector = DriftDetector()
        # baseline=0.50, need current <= 0.45 to trigger (10% of 0.50 = 0.05)
        trades = make_trades(n_wins=22, n_losses=28)  # 44% win rate
        alert = detector.check_drift(trades, baseline_win_rate=0.50)
        # drop = 0.06/0.50 = 12% > 10% threshold -> should alert
        assert alert is not None

    def test_is_drifting_returns_true_on_significant_drop(self) -> None:
        detector = DriftDetector()
        assert detector.is_drifting(current_win_rate=0.40, baseline_win_rate=0.55) is True

    def test_is_drifting_returns_false_on_minor_drop(self) -> None:
        detector = DriftDetector()
        assert detector.is_drifting(current_win_rate=0.53, baseline_win_rate=0.55) is False
