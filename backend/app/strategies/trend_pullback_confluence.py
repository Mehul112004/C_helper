"""
Trend Pullback Confluence Strategy v2.0 — Confluence Engine Edition

Phase 2 rewrite: Pure logic gates and confidence scoring.
EMA ordering and RSI hook evaluation use indicator values, not inline math.

Signal generation:
  Base requirement: EMA stack aligned (1 hard gate, down from 3)
  Additive modifiers: price near EMA 50, RSI momentum hook, bullish/bearish candle,
                       wick rejection, volume confirmation, FVG active

Confidence budget design:
  Base (must pass):      0.50  (EMA stack aligned: 50 > 100 > 200 or 50 < 100 < 200)
  Primary confluence:    0.15  (price near EMA 50)
  Secondary:             0.12  (RSI momentum hook)
  Tertiary:             0.08   (bullish/bearish candle, volume)
  Minor:                 0.05   (wick rejection, FVG active)
  Threshold:             0.70  (requires stack + near EMA + at least 1 tertiary)
"""

import numpy as np
import pandas as pd
from typing import Optional

from app.core.base_strategy import BaseStrategy, Candle, Indicators, SetupSignal
from app.core.base_strategy import safe_lt, safe_gt, safe_between


class TrendPullbackConfluenceStrategy(BaseStrategy):
    name = "Trend Pullback Confluence"
    description = (
        "Detects EMA stack alignment pullbacks with confluence scoring: "
        "EMA stack + RSI hook + price-at-EMA + volume + FVG."
    )
    timeframes = ["15m"]
    version = "2.0"
    min_confidence = 0.70

    # ── Phase 2: Feature Declaration ──
    required_features = ['ema', 'rsi', 'atr', 'volume_ma', 'fvg']
    feature_config = {
        'ema_periods': [50, 100, 200],
        'rsi_period': 14,
        'atr_period': 14,
        'volume_ma_period': 20,
    }

    # ── Phase 2: Weighted Scoring Matrix ──

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Confluence scoring for trend pullbacks.

        Hard gate:
          - EMA stack aligned (bullish: 50 > 100 > 200, bearish: 50 < 100 < 200)

        Additive modifiers:
          - Price near EMA 50 (±0.3 * ATR, +0.15)
          - RSI momentum hook (recent dip below 45 recovering, or spike above 55 declining, +0.12)
          - Bullish/bearish candle (+0.08)
          - Volume confirmation (+0.08)
          - Wick rejection (+0.05)
          - FVG active (+0.05)
        """
        ema_ok = (
            df['ema_50'].notna() & df['ema_100'].notna() & df['ema_200'].notna()
        )
        # Bullish stack: 50 > 100 > 200
        bullish_stack = ema_ok & (df['ema_50'] > df['ema_100']) & (df['ema_100'] > df['ema_200'])
        # Bearish stack: 50 < 100 < 200
        bearish_stack = ema_ok & (df['ema_50'] < df['ema_100']) & (df['ema_100'] < df['ema_200'])

        # ── Hard Gate 2: Price must be near EMA 50 (pullback to the moving average) ──
        atr_ok = df['atr'].notna() & (df['atr'] > 0)
        near_ema50_tolerance = 0.2 * df['atr']  # Tightened from 0.3: stricter pullback requirement
        near_ema50 = atr_ok & (
            (bullish_stack & (df['low'] <= df['ema_50'] + near_ema50_tolerance) &
             (df['close'] > df['ema_50'])) |
            (bearish_stack & (df['high'] >= df['ema_50'] - near_ema50_tolerance) &
             (df['close'] < df['ema_50']))
        )

        # ── Hard Gate 3: Falling knife protection ──
        candle_range = df['high'] - df['low']
        not_falling_knife = atr_ok & (candle_range < 1.8 * df['atr'])

        base_setup = (bullish_stack | bearish_stack) & near_ema50 & not_falling_knife

        # ── Base confidence ──
        df['confidence'] = np.where(base_setup, 0.50, 0.0)
        df['conf_base'] = df['confidence'].copy()

        # ── Modifier: RSI momentum hook (+0.15) ──
        rsi_ok = df['rsi'].notna()
        # Check if RSI was below 45 in last 5 bars and now rising
        rsi_hook_bull = pd.Series(False, index=df.index)
        rsi_hook_bear = pd.Series(False, index=df.index)
        for i in range(5, len(df)):
            past_rsi = df['rsi'].iloc[i - 5:i]
            curr_rsi = df['rsi'].iloc[i]
            if pd.notna(curr_rsi):
                # Bullish: RSI dipped below 45 recently, now rising, not overbought
                rsi_hook_bull.iloc[i] = (
                    (past_rsi.min() < 45) & (curr_rsi > past_rsi.iloc[-2]) & (curr_rsi < 65)
                )
                # Bearish: RSI spiked above 55 recently, now falling, not oversold
                rsi_hook_bear.iloc[i] = (
                    (past_rsi.max() > 55) & (curr_rsi < past_rsi.iloc[-2]) & (curr_rsi > 35)
                )
        rsi_hook = (bullish_stack & rsi_hook_bull) | (bearish_stack & rsi_hook_bear)
        df['conf_rsi'] = np.where(base_setup & rsi_hook, 0.15, 0.0)
        df['confidence'] += df['conf_rsi']

        # ── Modifier: Directional candle ──
        bullish_candle = df['close'] > df['open']
        bearish_candle = df['close'] < df['open']
        dir_candle = (bullish_stack & bullish_candle) | (bearish_stack & bearish_candle)
        df['conf_candle'] = np.where(base_setup & dir_candle, 0.08, 0.0)
        df['confidence'] += df['conf_candle']

        # ── Modifier: Volume confirmation ──
        vol_ok = df['volume_ma'].notna() & (df['volume'] > df['volume_ma'])
        df['conf_vol'] = np.where(base_setup & vol_ok, 0.08, 0.0)
        df['confidence'] += df['conf_vol']

        # ── Modifier: Wick rejection ──
        body = (df['close'] - df['open']).abs()
        lower_wick = np.minimum(df['open'], df['close']) - df['low']
        upper_wick = df['high'] - np.maximum(df['open'], df['close'])
        wick_bull = bullish_stack & (lower_wick > body * 1.2)
        wick_bear = bearish_stack & (upper_wick > body * 1.2)
        df['conf_wick'] = np.where(base_setup & (wick_bull | wick_bear), 0.05, 0.0)
        df['confidence'] += df['conf_wick']

        # ── Modifier: FVG active ──
        fvg_active = df['fvg_active'].notna() & (df['fvg_active'] == True)
        df['conf_fvg'] = np.where(base_setup & fvg_active, 0.05, 0.0)
        df['confidence'] += df['conf_fvg']

        # ── Trigger ──
        df['signal'] = np.where(df['confidence'] >= self.min_confidence, 1, 0)

        # ── Direction ──
        df['direction'] = None
        df.loc[(df['signal'] == 1) & bullish_stack, 'direction'] = 'LONG'
        df.loc[(df['signal'] == 1) & bearish_stack, 'direction'] = 'SHORT'

        return df

    # ── Legacy scan() — preserved for backward compatibility ──

    def _rsi_hook(self, indicators, direction):
        history = indicators.rsi_14_history or []
        if len(history) < 5: return False
        curr = (indicators.rsi_14 or 50)
        if direction == "LONG":
            return min(history) < 45 and curr > history[-2] and curr < 65
        else:
            return max(history) > 55 and curr < history[-2] and curr > 35

    def scan(self, symbol, timeframe, candles, indicators, sr_zones, htf_candles=None):
        if len(candles) < 30: return None
        current = candles[-1]
        atr = indicators.atr_14 or 0
        if atr <= 0: return None
        if current.range_size > 1.8 * atr: return None

        ema50 = indicators.ema_50
        ema100 = indicators.ema_100
        ema200 = indicators.ema_200
        if not all([ema50, ema100, ema200]): return None

        if ema50 > ema100 > ema200:
            if current.low <= ema50 + 0.2 * atr and current.close > ema50:
                if not (current.body_size >= 1.2 * atr):
                    if self._rsi_hook(indicators, "LONG"):
                        confidence = 0.65
                        if current.is_bullish: confidence += 0.10
                        if current.lower_wick > current.body_size * 1.2: confidence += 0.08
                        if indicators.volume_ma_20 and current.volume > indicators.volume_ma_20: confidence += 0.07
                        if indicators.macd_histogram and indicators.macd_histogram > 0: confidence += 0.05
                        confidence = min(confidence, 1.0)
                        if confidence >= self.min_confidence:
                            return SetupSignal(
                                strategy_name=self.name, symbol=symbol, timeframe=timeframe,
                                direction="LONG", confidence=confidence, entry=current.close,
                                notes=f"Bullish trend pullback. EMA stack aligned. RSI hook. Close: {current.close:.2f}.",
                            )
        elif ema50 < ema100 < ema200:
            if current.high >= ema50 - 0.2 * atr and current.close < ema50:
                if not (current.body_size >= 1.2 * atr):
                    if self._rsi_hook(indicators, "SHORT"):
                        confidence = 0.65
                        if current.is_bearish: confidence += 0.10
                        if current.upper_wick > current.body_size * 1.2: confidence += 0.08
                        if indicators.volume_ma_20 and current.volume > indicators.volume_ma_20: confidence += 0.07
                        if indicators.macd_histogram and indicators.macd_histogram < 0: confidence += 0.05
                        confidence = min(confidence, 1.0)
                        if confidence >= self.min_confidence:
                            return SetupSignal(
                                strategy_name=self.name, symbol=symbol, timeframe=timeframe,
                                direction="SHORT", confidence=confidence, entry=current.close,
                                notes=f"Bearish trend pullback. EMA stack aligned. RSI hook. Close: {current.close:.2f}.",
                            )
        return None

    def calculate_sl(self, signal, candles, atr):
        if signal.direction == "LONG": return round(min(c.low for c in candles[-5:]) - (0.5 * atr), 8)
        else: return round(max(c.high for c in candles[-5:]) + (0.5 * atr), 8)

    def calculate_tp(self, signal, candles, atr, sr_zones=None):
        entry = signal.entry or candles[-1].close
        sl = self.calculate_sl(signal, candles, atr)
        risk = max(abs(entry - sl), atr * 0.1)
        if signal.direction == "LONG": return (round(entry + (1.5 * risk), 8), round(entry + (3.0 * risk), 8))
        else: return (round(entry - (1.5 * risk), 8), round(entry - (3.0 * risk), 8))

    def should_confirm_with_llm(self, signal):
        return True
