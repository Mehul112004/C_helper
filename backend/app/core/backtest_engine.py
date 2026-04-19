"""
Backtesting Engine
Core engine for running strategies against historical data and computing
performance metrics.

Hybrid approach:
- Indicators are computed vectorized across the full dataset (fast)
- Strategies are executed bar-by-bar via StrategyRunner.scan_historical()
  to maintain 1:1 parity with the live engine
- Trade outcome resolution (SL/TP hit detection) is fully vectorized
"""

import json
import uuid
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional

from app.core.base_strategy import BaseStrategy, SetupSignal
from app.core.indicators import IndicatorService
from app.core.sr_engine import SREngine
from app.core.strategy_runner import StrategyRunner
from app.models.db import db, Candle, BacktestRun, BacktestTrade


class BacktestEngine:
    """
    Orchestrates a full backtest: data loading, indicator computation,
    strategy execution, trade simulation, and metrics calculation.
    """

    VALID_TIMEFRAMES = ['5m', '15m', '1h', '4h', '1D']

    # ---------- Indicator Computation (Vectorized, no DB fetch) ----------

    @staticmethod
    def compute_indicators_from_df(df: pd.DataFrame) -> dict:
        """
        Compute all indicator series directly from a DataFrame.
        Returns indicator series in the same format as IndicatorService
        (list of {time, value} dicts) for compatibility with StrategyRunner.

        Args:
            df: DataFrame with columns [open_time, open, high, low, close, volume]
                sorted by open_time ascending.

        Returns:
            Dict of indicator_name → list of {time, value} dicts.
        """
        closes = df['close']
        highs = df['high']
        lows = df['low']
        volumes = df['volume']
        timestamps = df['open_time'].dt.strftime('%Y-%m-%dT%H:%M:%SZ').tolist()

        ema_9 = IndicatorService.compute_ema(closes, 9)
        ema_21 = IndicatorService.compute_ema(closes, 21)
        ema_50 = IndicatorService.compute_ema(closes, 50)
        ema_100 = IndicatorService.compute_ema(closes, 100)
        ema_200 = IndicatorService.compute_ema(closes, 200)
        rsi_14 = IndicatorService.compute_rsi(closes, 14)
        macd = IndicatorService.compute_macd(closes, 12, 26, 9)
        bb = IndicatorService.compute_bollinger(closes, 20, 2.0)
        kc = IndicatorService.compute_keltner(highs, lows, closes, 20, 10, 1.5)
        atr_14 = IndicatorService.compute_atr(highs, lows, closes, 14)
        vol_ma_20 = IndicatorService.compute_volume_ma(volumes, 20)

        def _series_to_list(series: pd.Series) -> list:
            result = []
            for i, val in enumerate(series):
                if pd.notna(val):
                    result.append({'time': timestamps[i], 'value': round(float(val), 6)})
                else:
                    result.append({'time': timestamps[i], 'value': None})
            return result

        return {
            'ema_9': _series_to_list(ema_9),
            'ema_21': _series_to_list(ema_21),
            'ema_50': _series_to_list(ema_50),
            'ema_100': _series_to_list(ema_100),
            'ema_200': _series_to_list(ema_200),
            'rsi_14': _series_to_list(rsi_14),
            'macd_line': _series_to_list(macd['macd_line']),
            'macd_signal': _series_to_list(macd['macd_signal']),
            'macd_histogram': _series_to_list(macd['macd_histogram']),
            'bb_upper': _series_to_list(bb['bb_upper']),
            'bb_middle': _series_to_list(bb['bb_middle']),
            'bb_lower': _series_to_list(bb['bb_lower']),
            'bb_width': _series_to_list(bb['bb_width']),
            'kc_upper': _series_to_list(kc['kc_upper']),
            'kc_lower': _series_to_list(kc['kc_lower']),
            'atr_14': _series_to_list(atr_14),
            'volume_ma_20': _series_to_list(vol_ma_20),
        }

    # ---------- Trade Simulation (Vectorized) ----------

    @staticmethod
    def simulate_trades(
        signals: list[SetupSignal],
        candle_df: pd.DataFrame,
        initial_capital: float,
        risk_pct: float,
    ) -> list[dict]:
        """
        Resolve trade outcomes using vectorized pandas operations.

        For each signal, forward-scans from the entry bar to find which
        price level (SL, TP1, TP2) is breached first.

        Same-bar conflict rule: If SL and TP are hit on the same candle,
        SL wins (conservative assumption).

        Args:
            signals: List of SetupSignal objects from strategy execution.
            candle_df: Full OHLCV DataFrame sorted by open_time.
            initial_capital: Starting capital for position sizing.
            risk_pct: Fraction of capital risked per trade (e.g. 0.01 = 1%).

        Returns:
            List of trade dicts with all fields needed for BacktestTrade.
        """
        if not signals:
            return []

        trades = []
        highs = candle_df['high'].values
        lows = candle_df['low'].values
        closes = candle_df['close'].values
        times = candle_df['open_time'].values

        # Build a time→index lookup for fast entry bar resolution
        time_index = {}
        for i, t in enumerate(times):
            ts = pd.Timestamp(t)
            time_index[ts] = i

        for trade_num, signal in enumerate(signals, start=1):
            entry = signal.entry or signal.timestamp
            sl = signal.sl
            tp1 = signal.tp1
            tp2 = signal.tp2

            if entry is None or sl is None or tp1 is None or tp2 is None:
                continue

            # Find entry bar index
            sig_time = pd.Timestamp(signal.timestamp)
            entry_idx = time_index.get(sig_time)
            if entry_idx is None:
                # Find closest bar
                sig_time_naive = sig_time.tz_localize(None) if sig_time.tzinfo else sig_time
                diffs = np.abs(times.astype('datetime64[ns]') - np.datetime64(sig_time_naive))
                entry_idx = int(np.argmin(diffs))

            entry_price = signal.entry if signal.entry else closes[entry_idx]

            # Skip if entry is after last bar
            if entry_idx >= len(candle_df) - 1:
                continue

            # Forward slice from the bar AFTER entry
            fwd_start = entry_idx + 1
            fwd_highs = highs[fwd_start:]
            fwd_lows = lows[fwd_start:]
            fwd_times = times[fwd_start:]

            if len(fwd_highs) == 0:
                continue

            # Detect level hits
            if signal.direction == 'LONG':
                sl_hits = fwd_lows <= sl
                tp1_hits = fwd_highs >= tp1
                tp2_hits = fwd_highs >= tp2
            else:  # SHORT
                sl_hits = fwd_highs >= sl
                tp1_hits = fwd_lows <= tp1
                tp2_hits = fwd_lows <= tp2

            # Find first bar where each level is hit (-1 if never)
            sl_bar = int(np.argmax(sl_hits)) if sl_hits.any() else -1
            tp1_bar = int(np.argmax(tp1_hits)) if tp1_hits.any() else -1
            tp2_bar = int(np.argmax(tp2_hits)) if tp2_hits.any() else -1

            # Validate: argmax returns 0 for all-False arrays; verify the hit actually occurred
            if sl_bar == 0 and not sl_hits[0]:
                sl_bar = -1
            if tp1_bar == 0 and not tp1_hits[0]:
                tp1_bar = -1
            if tp2_bar == 0 and not tp2_hits[0]:
                tp2_bar = -1

            # Determine outcome: which level was hit first
            candidates = []
            if sl_bar >= 0:
                candidates.append(('HIT_SL', sl_bar, sl))
            if tp2_bar >= 0:
                candidates.append(('HIT_TP2', tp2_bar, tp2))
            if tp1_bar >= 0:
                candidates.append(('HIT_TP1', tp1_bar, tp1))

            if not candidates:
                # No level hit — trade expires at end of data
                exit_idx = len(fwd_times) - 1
                exit_price = float(closes[fwd_start + exit_idx])
                exit_time = pd.Timestamp(fwd_times[exit_idx]).to_pydatetime()
                outcome = 'EXPIRED'
            else:
                # Sort by bar index; on tie, SL wins (conservative)
                priority = {'HIT_SL': 0, 'HIT_TP1': 1, 'HIT_TP2': 2}
                candidates.sort(key=lambda x: (x[1], priority.get(x[0], 99)))
                outcome, exit_bar_offset, exit_price = candidates[0]
                exit_price = float(exit_price)
                exit_time = pd.Timestamp(fwd_times[exit_bar_offset]).to_pydatetime()

            # Calculate PnL
            risk_amount = initial_capital * risk_pct
            risk_distance = abs(entry_price - sl)
            if risk_distance == 0:
                position_size = 0
            else:
                position_size = risk_amount / risk_distance

            if signal.direction == 'LONG':
                pnl = position_size * (exit_price - entry_price)
            else:
                pnl = position_size * (entry_price - exit_price)

            pnl_pct = (pnl / initial_capital) * 100 if initial_capital > 0 else 0

            # R/R achieved
            if risk_distance > 0:
                if signal.direction == 'LONG':
                    rr_ratio = (exit_price - entry_price) / risk_distance
                else:
                    rr_ratio = (entry_price - exit_price) / risk_distance
            else:
                rr_ratio = 0

            # Duration
            entry_datetime = pd.Timestamp(times[entry_idx]).to_pydatetime()
            duration_mins = (exit_time - entry_datetime).total_seconds() / 60.0

            trades.append({
                'trade_number': trade_num,
                'entry_time': entry_datetime,
                'exit_time': exit_time,
                'symbol': signal.symbol,
                'timeframe': signal.timeframe,
                'direction': signal.direction,
                'strategy_name': signal.strategy_name,
                'confidence': signal.confidence,
                'entry_price': float(entry_price),
                'sl_price': float(sl),
                'tp1_price': float(tp1),
                'tp2_price': float(tp2),
                'exit_price': float(exit_price),
                'outcome': outcome,
                'pnl': round(float(pnl), 2),
                'pnl_pct': round(float(pnl_pct), 4),
                'rr_ratio': round(float(rr_ratio), 4),
                'duration_mins': round(float(duration_mins), 2),
                'notes': signal.notes,
            })

        return trades

    # ---------- Equity Curve ----------

    @staticmethod
    def build_equity_curve(
        trades: list[dict],
        initial_capital: float,
        candle_df: pd.DataFrame,
    ) -> list[dict]:
        """
        Build an equity curve as a list of {time, value} dicts.
        Steps through trades chronologically, updating portfolio value.

        Also includes start and end data points for a complete curve.
        """
        if not trades:
            first_time = candle_df['open_time'].iloc[0]
            last_time = candle_df['open_time'].iloc[-1]
            return [
                {'time': first_time.strftime('%Y-%m-%dT%H:%M:%SZ'), 'value': initial_capital},
                {'time': last_time.strftime('%Y-%m-%dT%H:%M:%SZ'), 'value': initial_capital},
            ]

        sorted_trades = sorted(trades, key=lambda t: t['exit_time'])
        curve = []
        equity = initial_capital

        # Starting point
        start_time = candle_df['open_time'].iloc[0]
        curve.append({
            'time': start_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'value': round(equity, 2),
        })

        for trade in sorted_trades:
            pnl = trade.get('pnl', 0) or 0
            equity += pnl
            exit_time = trade['exit_time']
            if isinstance(exit_time, datetime):
                time_str = exit_time.strftime('%Y-%m-%dT%H:%M:%SZ')
            else:
                time_str = pd.Timestamp(exit_time).strftime('%Y-%m-%dT%H:%M:%SZ')

            curve.append({
                'time': time_str,
                'value': round(equity, 2),
            })

        return curve

    # ---------- Metrics Calculator ----------

    @staticmethod
    def compute_metrics(
        trades: list[dict],
        initial_capital: float,
        equity_curve: list[dict],
    ) -> dict:
        """
        Compute all summary performance metrics from trade results.

        Returns dict with: total_trades, win_rate, total_pnl, total_pnl_pct,
        sharpe_ratio, sortino_ratio, max_drawdown, max_drawdown_pct,
        avg_rr, profit_factor, avg_trade_duration_mins, best_trade_pnl,
        worst_trade_pnl.
        """
        if not trades:
            return {
                'total_trades': 0, 'win_rate': 0, 'total_pnl': 0,
                'total_pnl_pct': 0, 'sharpe_ratio': 0, 'sortino_ratio': 0,
                'max_drawdown': 0, 'max_drawdown_pct': 0, 'avg_rr': 0,
                'profit_factor': 0, 'avg_trade_duration_mins': 0,
                'best_trade_pnl': 0, 'worst_trade_pnl': 0,
            }

        pnls = [t.get('pnl', 0) or 0 for t in trades]
        pnl_array = np.array(pnls, dtype=float)

        total_trades = len(trades)
        winners = sum(1 for t in trades if t['outcome'] in ('HIT_TP1', 'HIT_TP2'))
        win_rate = (winners / total_trades) * 100 if total_trades > 0 else 0

        total_pnl = float(np.sum(pnl_array))
        total_pnl_pct = (total_pnl / initial_capital) * 100 if initial_capital > 0 else 0

        # Sharpe Ratio (annualized)
        if len(pnl_array) > 1 and np.std(pnl_array) > 0:
            returns = pnl_array / initial_capital
            sharpe = float(np.mean(returns) / np.std(returns) * np.sqrt(252))
        else:
            sharpe = 0.0

        # Sortino Ratio (annualized, only downside deviation)
        if len(pnl_array) > 1:
            returns = pnl_array / initial_capital
            negative_returns = returns[returns < 0]
            if len(negative_returns) > 0 and np.std(negative_returns) > 0:
                sortino = float(np.mean(returns) / np.std(negative_returns) * np.sqrt(252))
            else:
                sortino = float(np.mean(returns) * np.sqrt(252)) if np.mean(returns) > 0 else 0.0
        else:
            sortino = 0.0

        # Max Drawdown from equity curve
        if equity_curve and len(equity_curve) > 1:
            values = np.array([p['value'] for p in equity_curve], dtype=float)
            peaks = np.maximum.accumulate(values)
            drawdowns = peaks - values
            max_dd = float(np.max(drawdowns))
            max_dd_pct = float((max_dd / np.max(peaks)) * 100) if np.max(peaks) > 0 else 0.0
        else:
            max_dd = 0.0
            max_dd_pct = 0.0

        # Profit Factor
        gross_profit = float(np.sum(pnl_array[pnl_array > 0]))
        gross_loss = float(np.abs(np.sum(pnl_array[pnl_array < 0])))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (
            float('inf') if gross_profit > 0 else 0
        )
        # Cap for JSON serialization
        if profit_factor == float('inf'):
            profit_factor = 999.99

        # Average R/R for winners
        rr_values = [t.get('rr_ratio', 0) or 0 for t in trades if t['outcome'] in ('HIT_TP1', 'HIT_TP2')]
        avg_rr = float(np.mean(rr_values)) if rr_values else 0

        # Average trade duration
        durations = [t.get('duration_mins', 0) or 0 for t in trades]
        avg_duration = float(np.mean(durations)) if durations else 0

        # Best / worst
        best_pnl = float(np.max(pnl_array)) if len(pnl_array) > 0 else 0
        worst_pnl = float(np.min(pnl_array)) if len(pnl_array) > 0 else 0

        return {
            'total_trades': int(total_trades),
            'win_rate': round(float(win_rate), 2),
            'total_pnl': round(float(total_pnl), 2),
            'total_pnl_pct': round(float(total_pnl_pct), 2),
            'sharpe_ratio': round(float(sharpe), 4),
            'sortino_ratio': round(float(sortino), 4),
            'max_drawdown': round(float(max_dd), 2),
            'max_drawdown_pct': round(float(max_dd_pct), 2),
            'avg_rr': round(float(avg_rr), 4),
            'profit_factor': round(float(profit_factor), 4),
            'avg_trade_duration_mins': round(float(avg_duration), 2),
            'best_trade_pnl': round(float(best_pnl), 2),
            'worst_trade_pnl': round(float(worst_pnl), 2),
        }

    # ---------- Main Entry Point ----------

    @classmethod
    def run(
        cls,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        strategies: list[BaseStrategy],
        strategy_names: list[str],
        initial_capital: float = 10000.0,
        risk_pct: float = 0.01,
    ) -> dict:
        """
        Execute a full backtest.

        Args:
            symbol: Trading pair (e.g. "BTCUSDT")
            timeframe: Candle timeframe (e.g. "1h")
            start_date: Start of backtest window
            end_date: End of backtest window
            strategies: List of strategy instances to run
            strategy_names: List of strategy name strings (for DB record)
            initial_capital: Starting capital in USD
            risk_pct: Fraction of capital risked per trade

        Returns:
            Dict containing run_id, status, metrics, equity_curve, trades, etc.
        """
        run_id = str(uuid.uuid4())

        # Create the run record
        run_record = BacktestRun(
            id=run_id,
            symbol=symbol,
            timeframe=timeframe,
            strategy_names=json.dumps(strategy_names),
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            risk_per_trade=risk_pct,
            status='RUNNING',
        )
        db.session.add(run_record)
        db.session.commit()

        try:
            # 1. Fetch candles from DB
            candles = (
                Candle.query
                .filter_by(symbol=symbol, timeframe=timeframe)
                .filter(Candle.open_time >= start_date)
                .filter(Candle.open_time <= end_date)
                .order_by(Candle.open_time.asc())
                .all()
            )

            if len(candles) < 50:
                raise ValueError(
                    f"Insufficient candle data: {len(candles)} candles "
                    f"(need at least 50 for strategy warmup)"
                )

            data = [c.to_dict() for c in candles]
            candle_df = pd.DataFrame(data)
            candle_df['open_time'] = pd.to_datetime(candle_df['open_time'])
            candle_df = candle_df.sort_values('open_time').reset_index(drop=True)

            # 2. Compute indicators across full dataset (vectorized)
            indicator_series = cls.compute_indicators_from_df(candle_df)

            # 3. Detect S/R zones from the dataset
            atr_series = IndicatorService.compute_atr(
                candle_df['high'], candle_df['low'], candle_df['close'], 14
            )
            current_atr = float(atr_series.iloc[-1]) if pd.notna(atr_series.iloc[-1]) else 0
            current_price = float(candle_df['close'].iloc[-1])

            if current_atr <= 0:
                current_atr = current_price * 0.01

            # Detect zones from the candle data directly (avoid DB query in detect_zones)
            all_zones_raw = []
            swing_zones = SREngine.detect_swing_points(candle_df, lookback=5)
            all_zones_raw.extend(swing_zones)
            round_zones = SREngine.detect_round_numbers(symbol, current_price)
            all_zones_raw.extend(round_zones)

            # Calculate zone widths and merge
            for zone in all_zones_raw:
                upper, lower = SREngine.calculate_zone_width(zone['price_level'], current_atr)
                zone['zone_upper'] = upper
                zone['zone_lower'] = lower

            merged_zones = SREngine.merge_zones(all_zones_raw, current_atr)
            for zone in merged_zones:
                upper, lower = SREngine.calculate_zone_width(zone['price_level'], current_atr)
                zone['zone_upper'] = upper
                zone['zone_lower'] = lower
                SREngine.score_zone(zone, candle_df, timeframe)
                zone['symbol'] = symbol
                zone['timeframe'] = timeframe

            sr_zones = merged_zones

            # 4. Run strategies bar-by-bar
            signals = StrategyRunner.scan_historical(
                strategies=strategies,
                symbol=symbol,
                timeframe=timeframe,
                candle_df=candle_df,
                indicator_series=indicator_series,
                sr_zones=sr_zones,
            )

            # 5. Simulate trades
            trade_results = cls.simulate_trades(
                signals=signals,
                candle_df=candle_df,
                initial_capital=initial_capital,
                risk_pct=risk_pct,
            )

            # 6. Build equity curve
            equity_curve = cls.build_equity_curve(
                trades=trade_results,
                initial_capital=initial_capital,
                candle_df=candle_df,
            )

            # 7. Compute metrics
            metrics = cls.compute_metrics(
                trades=trade_results,
                initial_capital=initial_capital,
                equity_curve=equity_curve,
            )

            # 8. Persist results
            run_record.status = 'COMPLETED'
            run_record.completed_at = datetime.utcnow()
            run_record.total_trades = metrics['total_trades']
            run_record.win_rate = metrics['win_rate']
            run_record.total_pnl = metrics['total_pnl']
            run_record.total_pnl_pct = metrics['total_pnl_pct']
            run_record.sharpe_ratio = metrics['sharpe_ratio']
            run_record.sortino_ratio = metrics['sortino_ratio']
            run_record.max_drawdown = metrics['max_drawdown']
            run_record.max_drawdown_pct = metrics['max_drawdown_pct']
            run_record.avg_rr = metrics['avg_rr']
            run_record.profit_factor = metrics['profit_factor']
            run_record.avg_trade_duration_mins = metrics['avg_trade_duration_mins']
            run_record.best_trade_pnl = metrics['best_trade_pnl']
            run_record.worst_trade_pnl = metrics['worst_trade_pnl']
            run_record.equity_curve = json.dumps(equity_curve)

            # Persist individual trades
            for t in trade_results:
                trade_record = BacktestTrade(
                    run_id=run_id,
                    trade_number=t['trade_number'],
                    entry_time=t['entry_time'],
                    exit_time=t['exit_time'],
                    symbol=t['symbol'],
                    timeframe=t['timeframe'],
                    direction=t['direction'],
                    strategy_name=t['strategy_name'],
                    confidence=t['confidence'],
                    entry_price=t['entry_price'],
                    sl_price=t['sl_price'],
                    tp1_price=t['tp1_price'],
                    tp2_price=t['tp2_price'],
                    exit_price=t['exit_price'],
                    outcome=t['outcome'],
                    pnl=t['pnl'],
                    pnl_pct=t['pnl_pct'],
                    rr_ratio=t['rr_ratio'],
                    duration_mins=t['duration_mins'],
                    notes=t.get('notes', ''),
                )
                db.session.add(trade_record)

            db.session.commit()

            return {
                'run_id': run_id,
                'status': 'COMPLETED',
                'metrics': metrics,
                'equity_curve': equity_curve,
                'trades': trade_results,
                'trade_count': len(trade_results),
                'candle_count': len(candle_df),
            }

        except Exception as e:
            run_record.status = 'FAILED'
            run_record.error_message = str(e)
            run_record.completed_at = datetime.utcnow()
            db.session.commit()

            return {
                'run_id': run_id,
                'status': 'FAILED',
                'error': str(e),
                'metrics': None,
                'equity_curve': [],
                'trades': [],
                'trade_count': 0,
                'candle_count': 0,
            }
