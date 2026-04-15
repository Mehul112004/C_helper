import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from app.core.backtest_engine import BacktestEngine
from app.core.base_strategy import BaseStrategy, SetupSignal
from app.models.db import db, Candle

class MockStrategy(BaseStrategy):
    name = "Mock Strategy"
    timeframes = ["1h"]
    
    def scan(self, symbol, timeframe, candles, indicators, sr_zones):
        # We don't actually run this in the vectorized tests below, 
        # but needed to satisfy the type hits if we test full run()
        pass


@pytest.fixture
def sample_candle_df():
    # 5 candles, 1h interval
    times = [datetime(2025, 1, 1, 0) + timedelta(hours=i) for i in range(5)]
    data = {
        'open_time': times,
        'open': [100, 105, 110, 108, 112],
        'high': [106, 112, 115, 114, 120],
        'low': [98, 104, 107, 105, 110],
        'close': [105, 110, 108, 112, 118],
        'volume': [10, 15, 12, 20, 25]
    }
    return pd.DataFrame(data)


def test_simulate_trades_long_hit_tp():
    # Trade entry at candle 0, TP hit at candle 2
    candle_df = pd.DataFrame({
        'open_time': [datetime(2025, 1, 1, 0, 0) + timedelta(hours=i) for i in range(4)],
        'open': [100, 100, 100, 100],
        'high': [100, 105, 120, 110], # High hits TP (115) at index 2
        'low': [100, 95, 95, 95],
        'close': [100, 100, 100, 100],
    })
    
    signals = [
        SetupSignal(
            strategy_name="Mock", symbol="BTCUSDT", timeframe="1h",
            direction="LONG", confidence=1.0, entry=100.0,
            sl=90.0, tp1=110.0, tp2=115.0,
            timestamp=candle_df['open_time'].iloc[0]
        )
    ]
    
    trades = BacktestEngine.simulate_trades(signals, candle_df, initial_capital=1000, risk_pct=0.01)
    assert len(trades) == 1
    trade = trades[0]
    
    assert trade['outcome'] == 'HIT_TP1'
    assert trade['exit_price'] == 110.0
    assert trade['rr_ratio'] == 1.0  # (110-100) / (100-90)
    assert trade['pnl'] == 10.0     # risk = $10, size = 1, pnl = 1 * 10


def test_simulate_trades_short_hit_sl():
    # Trade entry at candle 0, SL hit at candle 1
    candle_df = pd.DataFrame({
        'open_time': [datetime(2025, 1, 1, 0, 0) + timedelta(hours=i) for i in range(3)],
        'open': [100, 100, 100],
        'high': [100, 115, 100], # High hits SL (110) at index 1
        'low': [100, 95, 95],
        'close': [100, 100, 100],
    })
    
    signals = [
        SetupSignal(
            strategy_name="Mock", symbol="BTCUSDT", timeframe="1h",
            direction="SHORT", confidence=1.0, entry=100.0,
            sl=110.0, tp1=90.0, tp2=85.0,
            timestamp=candle_df['open_time'].iloc[0]
        )
    ]
    
    trades = BacktestEngine.simulate_trades(signals, candle_df, initial_capital=1000, risk_pct=0.01)
    trade = trades[0]
    
    assert trade['outcome'] == 'HIT_SL'
    assert trade['exit_price'] == 110.0
    assert trade['pnl'] == -10.0   # risk = $10, size = 1, loss = 1 * -10


def test_simulate_trades_same_bar_conflict():
    # Both SL and TP breached on the exact same bar
    candle_df = pd.DataFrame({
        'open_time': [datetime(2025, 1, 1), datetime(2025, 1, 2)],
        'open': [100, 100],
        'high': [100, 120], # Hits TP (115)
        'low': [100, 80],   # Hits SL (90)
        'close': [100, 100],
    })
    
    signals = [
        SetupSignal(
            strategy_name="Mock", symbol="BTCUSDT", timeframe="1h",
            direction="LONG", confidence=1.0, entry=100.0,
            sl=90.0, tp1=110.0, tp2=115.0,
            timestamp=candle_df['open_time'].iloc[0]
        )
    ]
    
    trades = BacktestEngine.simulate_trades(signals, candle_df, initial_capital=1000, risk_pct=0.01)
    trade = trades[0]
    
    # According to our conservative rule, SL wins
    assert trade['outcome'] == 'HIT_SL'


def test_compute_metrics():
    trades = [
        {'outcome': 'HIT_TP1', 'pnl': 20.0, 'rr_ratio': 2.0, 'duration_mins': 60},
        {'outcome': 'HIT_SL', 'pnl': -10.0, 'rr_ratio': 0.0, 'duration_mins': 30},
        {'outcome': 'HIT_TP2', 'pnl': 30.0, 'rr_ratio': 3.0, 'duration_mins': 120},
        {'outcome': 'EXPIRED', 'pnl': -5.0, 'rr_ratio': 0.0, 'duration_mins': 240},
    ]
    
    # Equity curve is just roughly simulated
    eq_curve = [
        {'value': 1000},
        {'value': 1020},
        {'value': 1010},
        {'value': 1040},
        {'value': 1035},
    ]
    
    metrics = BacktestEngine.compute_metrics(trades, initial_capital=1000, equity_curve=eq_curve)
    
    assert metrics['total_trades'] == 4
    assert metrics['win_rate'] == 50.0  # (2 / 4) * 100
    assert metrics['total_pnl'] == 35.0 # 20 - 10 + 30 - 5
    assert metrics['profit_factor'] == pytest.approx(50.0 / 15.0, rel=1e-3)  # Gross win / gross loss
    assert metrics['avg_rr'] == 2.5     # (2.0 + 3.0) / 2
    assert metrics['max_drawdown'] == 10.0 # From 1020 down to 1010
