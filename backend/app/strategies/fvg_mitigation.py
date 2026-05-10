"""
Fair Value Gap (FVG) Mitigation Strategy v3.0 — Confluence Engine Edition

Phase 2 rewrite: Pure logic gates and confidence scoring.
All FVG detection and OB detection delegated to app/core/ extraction layer.

Signal generation:
  Base requirement: FVG active + price inside FVG zone (2 hard gates, down from 5)
  Additive modifiers: OB backing, rejection wick quality, RSI momentum room,
                       volume confirmation, double zone confluence

Confidence budget design:
  Base (must pass):     0.50  (FVG active + price in zone)
  Primary confluence:   0.20  (OB backing the FVG)
  Secondary:            0.12  (rejection wick quality)
  Tertiary:             0.08  (RSI room, volume)
  Minor:                0.05  (double confluence - price in both FVG and OB)
  Threshold:            0.70  (requires base + OB backing or base + 2 secondary)
"""

import numpy as np
import pandas as pd
from typing import Optional

from app.core.base_strategy import BaseStrategy, Candle, Indicators, SetupSignal
from app.core.base_strategy import safe_lt, safe_gt


class FVGMitigationStrategy(BaseStrategy):
    name = "FVG Mitigation"
    description = (
        "Trades FVG mitigation with confluence scoring: "
        "FVG active + OB backing + rejection wick + RSI + volume."
    )
    timeframes = ["15m", "1h", "4h"]
    version = "3.0"
    min_confidence = 0.60  # Lowered: single-zone V1 contract reduces FVG count

    # ── Phase 2: Feature Declaration (deferred)
    # Multi-zone FVG tracking works (5 simultaneous zones) but the extraction
    # layer detects FVGs with different boundaries than the inline detector,
    # causing the price-in-zone + rejection wick gates to mismatch. The inline
    # scan() was tuned over months for specific FVG boundary sensitivity.
    # Revert to v1 scan() until extraction layer boundaries are calibrated.
    required_features = []

    # ── Phase 2: Weighted Scoring Matrix ──

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Confluence scoring for FVG mitigation.

        Hard gates:
          - FVG active
          - Price inside FVG zone (low or close within boundaries)

        Additive modifiers:
          - OB backing (+0.20)
          - Rejection wick quality (+0.12)
          - RSI momentum room (+0.08)
          - Volume confirmation (+0.08)
          - Double confluence (price in both FVG and OB zone, +0.05)
        """
        # ── Hard Gate 1: Any FVG active ──
        fvg_active = df['fvg_active'].notna() & (df['fvg_active'] == True)

        # ── Hard Gate 2: Price inside ANY active FVG zone (multi-zone check) ──
        # Check all numbered zone slots (0-4) and the derived nearest zone column
        in_any_zone = pd.Series(False, index=df.index)
        for zi in range(5):
            active_col = f'fvg_{zi}_active'
            if active_col in df.columns:
                zi_active = df[active_col].notna() & (df[active_col] == True)
                upper_val = df.get(f'fvg_{zi}_upper')
                lower_val = df.get(f'fvg_{zi}_lower')
                if upper_val is not None and lower_val is not None:
                    in_this_zone = zi_active & (
                        ((df['low'] >= lower_val) & (df['low'] <= upper_val)) |
                        ((df['close'] >= lower_val) & (df['close'] <= upper_val))
                    )
                    in_any_zone = in_any_zone | in_this_zone
        base_setup = fvg_active & in_any_zone

        # ── Direction: bullish FVG = upper > lower (gap above), bearish = upper < lower doesn't apply ──
        # Both bullish and bearish FVGs have upper > lower. We use price context:
        # Bullish FVG: price drops INTO the gap from above → LONG opportunity
        # Bearish FVG: price rises INTO the gap from below → SHORT opportunity
        # Detect direction from gap position relative to current close
        fvg_bullish = df['fvg_upper'].notna() & (df['close'] <= df['fvg_upper'])
        fvg_bearish = df['fvg_upper'].notna() & (df['close'] >= df['fvg_lower'])

        # ── Base confidence ──
        df['confidence'] = np.where(base_setup, 0.50, 0.0)
        df['conf_base'] = df['confidence'].copy()

        # ── Modifier: OB backing ──
        ob_active = df['ob_active'].notna() & (df['ob_active'] == True)
        ob_direction_ok = (
            ob_active & df['ob_direction'].notna() &
            ((fvg_bullish & (df['ob_direction'] == 'bullish')) |
             (fvg_bearish & (df['ob_direction'] == 'bearish')))
        )
        df['conf_ob'] = np.where(base_setup & ob_direction_ok, 0.20, 0.0)
        df['confidence'] += df['conf_ob']

        # ── Modifier: Rejection wick quality ──
        body = (df['close'] - df['open']).abs()
        lower_wick = np.minimum(df['open'], df['close']) - df['low']
        upper_wick = df['high'] - np.maximum(df['open'], df['close'])
        range_size = df['high'] - df['low']

        wick_quality_long = (
            (df['close'] > df['open']) &
            (range_size > 0) &
            (lower_wick >= 0.6 * range_size)
        )
        wick_quality_short = (
            (df['close'] < df['open']) &
            (range_size > 0) &
            (upper_wick >= 0.6 * range_size)
        )
        wick_ok = (fvg_bullish & wick_quality_long) | (fvg_bearish & wick_quality_short)
        df['conf_wick'] = np.where(base_setup & wick_ok, 0.12, 0.0)
        df['confidence'] += df['conf_wick']

        # ── Modifier: RSI momentum room ──
        rsi_ok = df['rsi'].notna() & (
            (fvg_bullish & (df['rsi'] < 50)) |
            (fvg_bearish & (df['rsi'] > 50))
        )
        df['conf_rsi'] = np.where(base_setup & rsi_ok, 0.08, 0.0)
        df['confidence'] += df['conf_rsi']

        # ── Modifier: Volume confirmation ──
        vol_ok = df['volume_ma'].notna() & (df['volume'] > df['volume_ma'])
        df['conf_vol'] = np.where(base_setup & vol_ok, 0.08, 0.0)
        df['confidence'] += df['conf_vol']

        # ── Modifier: Double confluence (price in both FVG and OB zone) ──
        double_zone = (
            ob_active & df['ob_upper'].notna() & df['ob_lower'].notna() &
            ((df['low'] >= df['ob_lower']) & (df['low'] <= df['ob_upper'])) |
            ((df['close'] >= df['ob_lower']) & (df['close'] <= df['ob_upper']))
        )
        df['conf_double'] = np.where(base_setup & double_zone, 0.05, 0.0)
        df['confidence'] += df['conf_double']

        # ── Trigger ──
        df['signal'] = np.where(df['confidence'] >= self.min_confidence, 1, 0)

        # ── Direction ──
        df['direction'] = None
        df.loc[(df['signal'] == 1) & fvg_bullish, 'direction'] = 'LONG'
        df.loc[(df['signal'] == 1) & fvg_bearish, 'direction'] = 'SHORT'

        return df

    # ── Legacy scan() — preserved for backward compatibility ──

    def _has_adjacent_bullish_ob(self, candles, fvg_candle_idx):
        for offset in range(0, 3):
            ob_idx = fvg_candle_idx - offset
            if ob_idx < 0: break
            candidate = candles[ob_idx]
            if candidate.is_bearish and candidate.body_size > 0:
                if ob_idx + 1 < len(candles) and candles[ob_idx + 1].is_bullish:
                    return {'high': candidate.high, 'low': candidate.low, 'index': ob_idx}
        return None

    def _has_adjacent_bearish_ob(self, candles, fvg_candle_idx):
        for offset in range(0, 3):
            ob_idx = fvg_candle_idx - offset
            if ob_idx < 0: break
            candidate = candles[ob_idx]
            if candidate.is_bullish and candidate.body_size > 0:
                if ob_idx + 1 < len(candles) and candles[ob_idx + 1].is_bearish:
                    return {'high': candidate.high, 'low': candidate.low, 'index': ob_idx}
        return None

    def scan(self, symbol, timeframe, candles, indicators, sr_zones, htf_candles=None):
        if len(candles) < 15: return None
        current_candle = candles[-1]
        if indicators.atr_14 and current_candle.body_size > 2 * indicators.atr_14: return None

        for i in range(len(candles) - 10, len(candles) - 1):
            if i < 2: continue
            c1 = candles[i - 2]
            c3 = candles[i]

            if c3.low > c1.high:
                fvg_top, fvg_bottom = c3.low, c1.high
                already_mitigated = False
                for k in range(i + 1, len(candles) - 1):
                    if candles[k].low <= fvg_bottom: already_mitigated = True; break
                if already_mitigated: continue
                if fvg_bottom <= current_candle.low <= fvg_top or fvg_bottom <= current_candle.close <= fvg_top:
                    if indicators.rsi_14 is not None and indicators.rsi_14 > 75: continue
                    if (current_candle.is_bullish and current_candle.range_size > 0
                            and current_candle.lower_wick >= 0.6 * current_candle.range_size):
                        ob = self._has_adjacent_bullish_ob(candles, i - 2)
                        if ob is None: continue
                        confidence = 0.62
                        if indicators.rsi_14 and indicators.rsi_14 < 50: confidence += 0.10
                        if current_candle.lower_wick > current_candle.body_size * 1.5: confidence += 0.10
                        if indicators.volume_ma_20 and current_candle.volume > indicators.volume_ma_20: confidence += 0.08
                        if ob['low'] <= current_candle.low <= ob['high']: confidence += 0.05
                        return SetupSignal(
                            strategy_name=self.name, symbol=symbol, timeframe=timeframe,
                            direction="LONG", confidence=min(confidence, 1.0),
                            entry=current_candle.close,
                            notes=f"Bullish FVG mitigation with OB. FVG: {fvg_bottom:.2f}-{fvg_top:.2f}. OB: {ob['low']:.2f}-{ob['high']:.2f}.",
                        )

            if c3.high < c1.low:
                fvg_top, fvg_bottom = c1.low, c3.high
                already_mitigated = False
                for k in range(i + 1, len(candles) - 1):
                    if candles[k].high >= fvg_top: already_mitigated = True; break
                if already_mitigated: continue
                if fvg_bottom <= current_candle.high <= fvg_top or fvg_bottom <= current_candle.close <= fvg_top:
                    if indicators.rsi_14 is not None and indicators.rsi_14 < 25: continue
                    if (current_candle.is_bearish and current_candle.range_size > 0
                            and current_candle.upper_wick >= 0.6 * current_candle.range_size):
                        ob = self._has_adjacent_bearish_ob(candles, i - 2)
                        if ob is None: continue
                        confidence = 0.62
                        if indicators.rsi_14 and indicators.rsi_14 > 50: confidence += 0.10
                        if current_candle.upper_wick > current_candle.body_size * 1.5: confidence += 0.10
                        if indicators.volume_ma_20 and current_candle.volume > indicators.volume_ma_20: confidence += 0.08
                        if ob['low'] <= current_candle.high <= ob['high']: confidence += 0.05
                        return SetupSignal(
                            strategy_name=self.name, symbol=symbol, timeframe=timeframe,
                            direction="SHORT", confidence=min(confidence, 1.0),
                            entry=current_candle.close,
                            notes=f"Bearish FVG mitigation with OB. FVG: {fvg_bottom:.2f}-{fvg_top:.2f}. OB: {ob['low']:.2f}-{ob['high']:.2f}.",
                        )
        return None

    def calculate_sl(self, signal, candles, atr):
        if signal.direction == "LONG": return round(candles[-1].low - (1.0 * atr), 8)
        else: return round(candles[-1].high + (1.0 * atr), 8)

    def calculate_tp(self, signal, candles, atr, sr_zones=None):
        entry = signal.entry or candles[-1].close
        sl = self.calculate_sl(signal, candles, atr)
        risk = max(abs(entry - sl), atr * 0.1)
        if signal.direction == "LONG": return (round(entry + (1.5 * risk), 8), round(entry + (3.0 * risk), 8))
        else: return (round(entry - (1.5 * risk), 8), round(entry - (3.0 * risk), 8))

    def should_confirm_with_llm(self, signal):
        return True
