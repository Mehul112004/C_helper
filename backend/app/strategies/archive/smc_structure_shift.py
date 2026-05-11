"""
SMC Structure Shift Strategy v2.0 — Confluence Engine Edition

Phase 2 rewrite: Pure logic gates and confidence scoring.
All ChoCh/BOS detection delegated to app/core/events.py extraction layer.

Signal generation:
  Base requirement: ChoCh or BOS event fires (1 hard gate, down from 6)
  Additive modifiers: volume > 1.2x MA, strong body (>60% of range),
                       RSI momentum alignment, FVG presence nearby

Confidence budget design:
  Base (must pass):      0.50  (event fires)
  Primary confluence:    0.15  (volume spike)
  Secondary:             0.12  (strong body)
  Tertiary:              0.10  (RSI momentum)
  Minor:                 0.05  (FVG nearby)
  Threshold:             0.70  (requires event + volume or event + body + RSI)

ChoCh vs BOS differentiation:
  - BOS: trend continuation, higher base reliability
  - ChoCh: trend reversal, requires stronger confluence to fire
"""

import numpy as np
import pandas as pd
from typing import Optional

from app.core.base_strategy import BaseStrategy, Candle, Indicators, SetupSignal
from app.core.base_strategy import safe_lt, safe_gt, safe_between


class SMCStructureShiftStrategy(BaseStrategy):
    name = "SMC Structure Shift"
    description = (
        "Detects ChoCh/BOS events with confluence scoring: "
        "event + volume + body strength + RSI + FVG."
    )
    timeframes = ["1h", "4h"]
    version = "2.0"
    min_confidence = 0.70

    # ── Phase 2: Feature Declaration ──
    required_features = ['choch', 'bos', 'rsi', 'ema', 'atr', 'volume_ma', 'fvg']
    feature_config = {
        'rsi_period': 14,
        'ema_periods': [50],
        'atr_period': 14,
        'volume_ma_period': 20,
    }

    # ── Phase 2: Weighted Scoring Matrix ──

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Confluence scoring for ChoCh/BOS events.

        Hard gate:
          - Any structural event fires (ChoCh or BOS, either direction)

        Additive modifiers:
          - Volume > 1.2x MA (+0.15)
          - Strong body (>60% of range, +0.12)
          - RSI momentum alignment (+0.10)
          - FVG active nearby (+0.05)

        BOS bonus: +0.05 over ChoCh (continuation is more reliable than reversal)
        """
        # ── Hard Gate: Any structural event ──
        choch_bull = df.get('event_choch_bullish', pd.Series(False, index=df.index))
        choch_bear = df.get('event_choch_bearish', pd.Series(False, index=df.index))
        bos_bull = df.get('event_bos_bullish', pd.Series(False, index=df.index))
        bos_bear = df.get('event_bos_bearish', pd.Series(False, index=df.index))

        event_fires = (
            (choch_bull == True) | (choch_bear == True) |
            (bos_bull == True) | (bos_bear == True)
        )
        base_setup = event_fires

        # ── Direction ──
        is_bullish = ((choch_bull == True) | (bos_bull == True))
        is_bearish = ((choch_bear == True) | (bos_bear == True))
        is_choch = ((choch_bull == True) | (choch_bear == True))
        is_bos = ((bos_bull == True) | (bos_bear == True))

        # ── Base confidence ──
        df['confidence'] = np.where(base_setup, 0.50, 0.0)
        df['conf_base'] = df['confidence'].copy()

        # ── BOS bonus over ChoCh ──
        df['conf_bos'] = np.where(base_setup & is_bos, 0.05, 0.0)
        df['confidence'] += df['conf_bos']

        # ── Modifier: Volume spike ──
        vol_spike = df['volume_ma'].notna() & (df['volume'] > df['volume_ma'] * 1.2)
        df['conf_vol'] = np.where(base_setup & vol_spike, 0.15, 0.0)
        df['confidence'] += df['conf_vol']

        # ── Modifier: Strong body ──
        body = (df['close'] - df['open']).abs()
        candle_range = df['high'] - df['low']
        strong_body = (candle_range > 0) & (body > 0.6 * candle_range)
        df['conf_body'] = np.where(base_setup & strong_body, 0.12, 0.0)
        df['confidence'] += df['conf_body']

        # ── Modifier: RSI momentum ──
        rsi_ok = df['rsi'].notna() & (
            (is_bullish & df['rsi'].between(50, 75)) |
            (is_bearish & df['rsi'].between(25, 50))
        )
        df['conf_rsi'] = np.where(base_setup & rsi_ok, 0.10, 0.0)
        df['confidence'] += df['conf_rsi']

        # ── Modifier: FVG nearby ──
        fvg_active = df['fvg_active'].notna() & (df['fvg_active'] == True)
        df['conf_fvg'] = np.where(base_setup & fvg_active, 0.05, 0.0)
        df['confidence'] += df['conf_fvg']

        # ── Trigger ──
        df['signal'] = np.where(df['confidence'] >= self.min_confidence, 1, 0)

        # ── Direction ──
        df['direction'] = None
        df.loc[(df['signal'] == 1) & is_bullish, 'direction'] = 'LONG'
        df.loc[(df['signal'] == 1) & is_bearish, 'direction'] = 'SHORT'

        return df

    # ── Legacy scan() — preserved for backward compatibility ──

    LOOKBACK = 40
    PIVOT_BARS = 3

    def _determine_trend(self, swings):
        if len(swings) < 4: return 'neutral'
        recent = swings[-4:]
        highs = [s for s in recent if s['type'] == 'high']
        lows = [s for s in recent if s['type'] == 'low']
        if len(highs) + len(lows) < 3: return 'neutral'
        higher_highs = highs[-1]['price'] > highs[-2]['price'] if len(highs) >= 2 else False
        higher_lows = lows[-1]['price'] > lows[-2]['price'] if len(lows) >= 2 else False
        lower_highs = highs[-1]['price'] < highs[-2]['price'] if len(highs) >= 2 else False
        lower_lows = lows[-1]['price'] < lows[-2]['price'] if len(lows) >= 2 else False
        has_hh = len(highs) >= 2 and higher_highs
        has_hl = len(lows) >= 2 and higher_lows
        has_lh = len(highs) >= 2 and lower_highs
        has_ll = len(lows) >= 2 and lower_lows
        if (has_hh and higher_lows) or (higher_highs and has_hl): return 'bullish'
        elif (has_lh and lower_lows) or (lower_highs and has_ll): return 'bearish'
        return 'neutral'

    def scan(self, symbol, timeframe, candles, indicators, sr_zones, htf_candles=None):
        from app.core.fractals import build_swing_map

        if len(candles) < self.LOOKBACK + self.PIVOT_BARS: return None
        window = candles[-(self.LOOKBACK + self.PIVOT_BARS):]
        current = candles[-1]
        atr = indicators.atr_14 or 0
        swings = build_swing_map(window, self.PIVOT_BARS)
        if len(swings) < 4: return None
        trend = self._determine_trend(swings)
        if trend == 'neutral': return None

        last_swing_high = last_swing_low = None
        for s in reversed(swings):
            if s['type'] == 'high' and last_swing_high is None: last_swing_high = s
            if s['type'] == 'low' and last_swing_low is None: last_swing_low = s
            if last_swing_high and last_swing_low: break

        if not last_swing_high or not last_swing_low: return None

        # BOS Bullish
        if trend == 'bullish' and last_swing_high:
            level = last_swing_high['price']
            body_close_above = current.close > level and min(current.open, current.close) > level * 0.998
            wick_only = current.high > level and max(current.open, current.close) <= level
            if body_close_above and not wick_only:
                confidence = 0.65
                if indicators.volume_ma_20 and current.volume > indicators.volume_ma_20 * 1.2: confidence += 0.10
                if current.body_size > current.range_size * 0.6: confidence += 0.08
                if indicators.rsi_14 and 50 < indicators.rsi_14 < 75: confidence += 0.07
                sl_price = round(last_swing_low['price'] - (1.0 * atr), 8) if atr > 0 else None
                return SetupSignal(strategy_name=self.name, symbol=symbol, timeframe=timeframe,
                                   direction="LONG", confidence=min(confidence, 1.0),
                                   entry=current.close, sl=sl_price,
                                   notes=f"Bullish BOS: body closed above swing high at {level:.2f}. Trend: {trend}.")

        # BOS Bearish
        if trend == 'bearish' and last_swing_low:
            level = last_swing_low['price']
            body_close_below = current.close < level and max(current.open, current.close) < level * 1.002
            wick_only = current.low < level and min(current.open, current.close) >= level
            if body_close_below and not wick_only:
                confidence = 0.65
                if indicators.volume_ma_20 and current.volume > indicators.volume_ma_20 * 1.2: confidence += 0.10
                if current.body_size > current.range_size * 0.6: confidence += 0.08
                if indicators.rsi_14 and 25 < indicators.rsi_14 < 50: confidence += 0.07
                sl_price = round(last_swing_high['price'] + (1.0 * atr), 8) if atr > 0 else None
                return SetupSignal(strategy_name=self.name, symbol=symbol, timeframe=timeframe,
                                   direction="SHORT", confidence=min(confidence, 1.0),
                                   entry=current.close, sl=sl_price,
                                   notes=f"Bearish BOS: body closed below swing low at {level:.2f}. Trend: {trend}.")

        # ChoCh Bullish
        if trend == 'bearish' and last_swing_high:
            level = last_swing_high['price']
            body_close_above = current.close > level and min(current.open, current.close) > level * 0.998
            wick_only = current.high > level and max(current.open, current.close) <= level
            if body_close_above and not wick_only:
                confidence = 0.60
                if indicators.volume_ma_20 and current.volume > indicators.volume_ma_20 * 1.3: confidence += 0.12
                if current.body_size > current.range_size * 0.6: confidence += 0.08
                if indicators.rsi_14 and indicators.rsi_14 > 50: confidence += 0.05
                sl_price = round(last_swing_low['price'] - (1.5 * atr), 8) if atr > 0 else None
                return SetupSignal(strategy_name=self.name, symbol=symbol, timeframe=timeframe,
                                   direction="LONG", confidence=min(confidence, 1.0),
                                   entry=current.close, sl=sl_price,
                                   notes=f"Bullish ChoCh: body broke above swing high at {level:.2f} against bearish trend.")

        # ChoCh Bearish
        if trend == 'bullish' and last_swing_low:
            level = last_swing_low['price']
            body_close_below = current.close < level and max(current.open, current.close) < level * 1.002
            wick_only = current.low < level and min(current.open, current.close) >= level
            if body_close_below and not wick_only:
                confidence = 0.60
                if indicators.volume_ma_20 and current.volume > indicators.volume_ma_20 * 1.3: confidence += 0.12
                if current.body_size > current.range_size * 0.6: confidence += 0.08
                if indicators.rsi_14 and indicators.rsi_14 < 50: confidence += 0.05
                sl_price = round(last_swing_high['price'] + (1.5 * atr), 8) if atr > 0 else None
                return SetupSignal(strategy_name=self.name, symbol=symbol, timeframe=timeframe,
                                   direction="SHORT", confidence=min(confidence, 1.0),
                                   entry=current.close, sl=sl_price,
                                   notes=f"Bearish ChoCh: body broke below swing low at {level:.2f} against bullish trend.")
        return None

    def calculate_sl(self, signal, candles, atr):
        if signal.sl is not None: return signal.sl
        if signal.direction == "LONG": return round(min(c.low for c in candles[-5:]) - (1.0 * atr), 8)
        else: return round(max(c.high for c in candles[-5:]) + (1.0 * atr), 8)

    def calculate_tp(self, signal, candles, atr, sr_zones=None):
        entry = signal.entry or candles[-1].close
        sl = self.calculate_sl(signal, candles, atr)
        risk = max(abs(entry - sl), atr * 0.1)
        if signal.direction == "LONG": return (round(entry + (2.0 * risk), 8), round(entry + (4.0 * risk), 8))
        else: return (round(entry - (2.0 * risk), 8), round(entry - (4.0 * risk), 8))

    def should_confirm_with_llm(self, signal):
        return True
