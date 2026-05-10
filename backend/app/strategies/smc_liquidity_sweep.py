"""
SMC Liquidity Sweep Strategy v2.0 — Confluence Engine Edition

Phase 2 rewrite: Pure logic gates and confidence scoring.
All sweep detection and volume climax detection delegated to extraction layer.

Signal generation:
  Base requirement: Liquidity sweep event fires (1 hard gate, down from 5)
  Additive modifiers: volume climax, RSI extreme alignment, close recovery strength,
                       FVG nearby, EMA trend alignment

Confidence budget design:
  Base (must pass):      0.50  (sweep event fires)
  Primary confluence:    0.15  (volume climax)
  Secondary:             0.12  (close recovery strength)
  Tertiary:              0.10  (RSI extreme alignment)
  Minor:                 0.05  (FVG nearby, EMA trend)
  Threshold:             0.70  (requires event + volume climax or event + 2 secondary)
"""

import numpy as np
import pandas as pd
from typing import Optional

from app.core.base_strategy import BaseStrategy, Candle, Indicators, SetupSignal
from app.core.base_strategy import safe_lt, safe_gt


class SMCLiquiditySweepStrategy(BaseStrategy):
    name = "SMC Liquidity Sweep"
    description = (
        "Detects liquidity sweeps (turtle soup) with confluence scoring: "
        "sweep event + volume climax + close recovery + RSI + FVG."
    )
    timeframes = ["5m", "15m"]
    version = "2.0"
    min_confidence = 0.70

    # ── Phase 2: Feature Declaration ──
    required_features = ['liquidity_sweep', 'volume_climax', 'rsi', 'ema', 'atr', 'volume_ma', 'fvg']
    feature_config = {
        'rsi_period': 14,
        'ema_periods': [50],
        'atr_period': 14,
        'volume_ma_period': 20,
    }

    # ── Phase 2: Weighted Scoring Matrix ──

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Confluence scoring for liquidity sweeps.

        Hard gate:
          - Sweep event fires (bullish or bearish)

        Additive modifiers:
          - Volume climax (+0.15)
          - Strong close recovery: close in upper/lower 40% of range (+0.12)
          - RSI extreme alignment (+0.10)
          - FVG active nearby (+0.05)
          - EMA 50 trend alignment (+0.05)
        """
        # ── Hard Gate: Sweep event ──
        sweep_bull = df.get('event_sweep_bullish', pd.Series(False, index=df.index))
        sweep_bear = df.get('event_sweep_bearish', pd.Series(False, index=df.index))
        sweep_fires = (sweep_bull == True) | (sweep_bear == True)
        base_setup = sweep_fires

        # ── Direction ──
        is_bullish = sweep_bull == True
        is_bearish = sweep_bear == True

        # ── Base confidence ──
        df['confidence'] = np.where(base_setup, 0.50, 0.0)
        df['conf_base'] = df['confidence'].copy()

        # ── Modifier: Volume climax ──
        vol_climax = df.get('event_volume_climax', pd.Series(False, index=df.index))
        df['conf_vol'] = np.where(base_setup & (vol_climax == True), 0.15, 0.0)
        df['confidence'] += df['conf_vol']

        # ── Modifier: Strong close recovery ──
        candle_range = df['high'] - df['low']
        close_position = (df['close'] - df['low']) / candle_range.replace(0, np.nan)
        strong_recovery = (
            candle_range > 0 & close_position.notna() &
            ((is_bullish & (close_position > 0.60)) |
             (is_bearish & (close_position < 0.40)))
        )
        df['conf_close'] = np.where(base_setup & strong_recovery, 0.12, 0.0)
        df['confidence'] += df['conf_close']

        # ── Modifier: RSI extreme alignment ──
        rsi_ok = df['rsi'].notna() & (
            (is_bullish & (df['rsi'] < 35)) |
            (is_bearish & (df['rsi'] > 65))
        )
        df['conf_rsi'] = np.where(base_setup & rsi_ok, 0.10, 0.0)
        df['confidence'] += df['conf_rsi']

        # ── Modifier: FVG active ──
        fvg_active = df['fvg_active'].notna() & (df['fvg_active'] == True)
        df['conf_fvg'] = np.where(base_setup & fvg_active, 0.05, 0.0)
        df['confidence'] += df['conf_fvg']

        # ── Modifier: EMA 50 trend alignment ──
        ema50_ok = df['ema_50'].notna() & (
            (is_bullish & (df['close'] > df['ema_50'])) |
            (is_bearish & (df['close'] < df['ema_50']))
        )
        df['conf_ema'] = np.where(base_setup & ema50_ok, 0.05, 0.0)
        df['confidence'] += df['conf_ema']

        # ── Trigger ──
        df['signal'] = np.where(df['confidence'] >= self.min_confidence, 1, 0)

        # ── Direction ──
        df['direction'] = None
        df.loc[(df['signal'] == 1) & is_bullish, 'direction'] = 'LONG'
        df.loc[(df['signal'] == 1) & is_bearish, 'direction'] = 'SHORT'

        return df

    # ── Legacy scan() — preserved for backward compatibility ──

    LOOKBACK = 30
    PIVOT_BARS = 3

    def _find_strongest_unbroken_fractal(self, fractals_list, direction, candles, window_start):
        if not fractals_list: return None, None
        window = candles[window_start:]
        if not window: return None, None
        if direction == 'HIGH':
            window_extreme = max(c.high for c in window)
            cluster_candidates = [(idx, price) for idx, price in fractals_list
                                   if abs(price - window_extreme) <= window_extreme * 0.001]
        else:
            window_extreme = min(c.low for c in window)
            cluster_candidates = [(idx, price) for idx, price in fractals_list
                                   if abs(price - window_extreme) <= window_extreme * 0.001]
        if not cluster_candidates: return None, None
        best = cluster_candidates[0]
        return best[1], len(cluster_candidates)

    def scan(self, symbol, timeframe, candles, indicators, sr_zones, htf_candles=None):
        from app.core.fractals import find_fractal_points

        if len(candles) < self.LOOKBACK: return None
        window = candles[-self.LOOKBACK:]
        current = candles[-1]
        atr = indicators.atr_14 or 0
        if atr <= 0: return None

        lookback_excl_current = window[:-1]
        if len(lookback_excl_current) < self.PIVOT_BARS * 2 + 1: return None

        fractal_highs, fractal_lows = find_fractal_points(lookback_excl_current, self.PIVOT_BARS)

        # Bearish sweep (SHORT)
        sweep_level, density = self._find_strongest_unbroken_fractal(
            fractal_highs, 'HIGH', candles, -self.LOOKBACK)
        if sweep_level and indicators.rsi_14 and indicators.rsi_14 < 30: sweep_level = None
        if sweep_level and current.high > sweep_level * 1.001 and current.close < sweep_level:
            if current.range_size > 0 and current.upper_wick >= 1.2 * current.body_size:
                if (current.close - current.low) <= 0.4 * current.range_size:
                    if indicators.volume_ma_20 and current.volume >= 1.2 * indicators.volume_ma_20:
                        confidence = 0.65
                        if current.upper_wick > current.body_size * 2: confidence += 0.10
                        if indicators.rsi_14 and indicators.rsi_14 > 60: confidence += 0.08
                        if density and density >= 2: confidence += 0.08
                        confidence = min(confidence, 1.0)
                        if confidence >= self.min_confidence:
                            return SetupSignal(
                                strategy_name=self.name, symbol=symbol, timeframe=timeframe,
                                direction="SHORT", confidence=confidence,
                                entry=current.close + (current.high - current.close) * 0.5,
                                notes=f"Bearish sweep at {sweep_level:.2f}. Density: {density}.",
                            )

        # Bullish sweep (LONG)
        sweep_level, density = self._find_strongest_unbroken_fractal(
            fractal_lows, 'LOW', candles, -self.LOOKBACK)
        if sweep_level and indicators.rsi_14 and indicators.rsi_14 > 70: sweep_level = None
        if sweep_level and current.low < sweep_level * 0.999 and current.close > sweep_level:
            if current.range_size > 0 and current.lower_wick >= 1.2 * current.body_size:
                if (current.close - current.low) >= 0.6 * current.range_size:
                    if indicators.volume_ma_20 and current.volume >= 1.2 * indicators.volume_ma_20:
                        confidence = 0.65
                        if current.lower_wick > current.body_size * 2: confidence += 0.10
                        if indicators.rsi_14 and indicators.rsi_14 < 40: confidence += 0.08
                        if density and density >= 2: confidence += 0.08
                        confidence = min(confidence, 1.0)
                        if confidence >= self.min_confidence:
                            return SetupSignal(
                                strategy_name=self.name, symbol=symbol, timeframe=timeframe,
                                direction="LONG", confidence=confidence,
                                entry=current.low + (current.close - current.low) * 0.5,
                                notes=f"Bullish sweep at {sweep_level:.2f}. Density: {density}.",
                            )
        return None

    def calculate_sl(self, signal, candles, atr):
        if signal.direction == "LONG": return round(min(c.low for c in candles[-3:]) - (1.0 * atr), 8)
        else: return round(max(c.high for c in candles[-3:]) + (1.0 * atr), 8)

    def calculate_tp(self, signal, candles, atr, sr_zones=None):
        entry = signal.entry or candles[-1].close
        sl = self.calculate_sl(signal, candles, atr)
        risk = max(abs(entry - sl), atr * 0.1)
        if signal.direction == "LONG": return (round(entry + (2.0 * risk), 8), round(entry + (4.0 * risk), 8))
        else: return (round(entry - (2.0 * risk), 8), round(entry - (4.0 * risk), 8))

    def should_confirm_with_llm(self, signal):
        return True
