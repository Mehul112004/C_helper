"""
Institutional Order Block (OB) Retest Strategy v4.0 — Confluence Engine Edition

Phase 2 rewrite: Pure logic gates and confidence scoring.
All mathematical OB/FVG/BOS/ChoCh detection delegated to app/core/ extraction layer.

Signal generation:
  Base requirement: OB active + price in zone (2 hard gates, down from 7)
  Additive modifiers: FVG presence, RSI room, volume confirmation, recent ChoCh/BOS,
                       wick quality, impulse strength (confidence breaks 0.70 threshold)

Confidence budget design:
  Base (must pass):    0.50  (OB active + price in zone)
  Primary confluence:  0.18  (FVG overlap) 
  Secondary:           0.12  (RSI momentum room)
  Tertiary:            0.08  (volume, ChoCh/BOS recent)
  Minor:               0.05  (wick quality, impulse strength)
  Threshold:           0.70  (requires base + at least 1 primary or 2 secondary)

The legacy scan() method is preserved for backward compatibility.
"""

import numpy as np
import pandas as pd
from typing import Optional

from app.core.base_strategy import BaseStrategy, Candle, Indicators, SetupSignal
from app.core.base_strategy import safe_lt, safe_gt, safe_between
from app.core.fractals import find_fractal_points


class OrderBlockRetestStrategy(BaseStrategy):
    name = "Order Block Retest"
    description = (
        "Detects institutional OB retests with confluence scoring: "
        "OB active + FVG + ChoCh/BOS + RSI + volume + wick quality."
    )
    timeframes = ["1h", "4h", "1d"]
    version = "4.0"
    min_confidence = 0.70

    # ── Phase 2: Feature Declaration ──
    required_features = ['ob', 'fvg', 'choch', 'bos', 'rsi', 'ema', 'atr', 'volume_ma']
    feature_config = {
        'rsi_period': 14,
        'ema_periods': [200],
        'atr_period': 14,
        'volume_ma_period': 20,
    }

    # ── Risk config (preserved from v3.3) ──
    MAX_RISK_ATR = 2.5
    TP_FRACTAL_LOOKBACK = 40
    PIVOT_BARS = 3

    # ── Phase 2: Weighted Scoring Matrix ──

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Confluence scoring for OB retest.

        Hard gates (must pass):
          - OB active (ob_active == True)
          - Price in OB zone (low or close or high between ob_lower and ob_upper)

        Additive modifiers:
          - FVG active and overlapping (+0.18)
          - RSI < 55 for longs or RSI > 45 for shorts (+0.12)
          - Volume above MA (+0.08)
          - Recent bullish/bearish ChoCh or BOS (+0.08)
          - Wick quality: lower wick > 0.5 * body (LONG) or upper wick > 0.5 * body (SHORT) (+0.05)
          - Impulse strength proxy: ATR > 0 and zone width < 2*ATR (+0.05)
        """
        # ── Hard Gate 1: OB active ──
        ob_active = df['ob_active'].notna() & (df['ob_active'] == True)

        # ── Hard Gate 2: Price in OB zone ──
        ob_upper_ok = df['ob_upper'].notna()
        ob_lower_ok = df['ob_lower'].notna()
        price_in_zone = (
            ob_upper_ok & ob_lower_ok &
            (
                ((df['low'] >= df['ob_lower']) & (df['low'] <= df['ob_upper'])) |
                ((df['close'] >= df['ob_lower']) & (df['close'] <= df['ob_upper'])) |
                ((df['high'] >= df['ob_lower']) & (df['high'] <= df['ob_upper']))
            )
        )

        base_setup = ob_active & price_in_zone

        # ── Direction from OB direction ──
        ob_bullish = df['ob_direction'].notna() & (df['ob_direction'] == 'bullish')
        ob_bearish = df['ob_direction'].notna() & (df['ob_direction'] == 'bearish')

        # ── Base confidence ──
        df['confidence'] = np.where(base_setup, 0.50, 0.0)
        df['conf_base'] = df['confidence'].copy()

        # ── Modifier: FVG overlap ──
        fvg_active = df['fvg_active'].notna() & (df['fvg_active'] == True)
        fvg_overlap = (
            fvg_active &
            df['fvg_lower'].notna() & df['ob_upper'].notna() &
            (df['fvg_lower'] <= df['ob_upper']) &
            (df['fvg_upper'] >= df['ob_lower'])
        )
        df['conf_fvg'] = np.where(base_setup & fvg_overlap, 0.18, 0.0)
        df['confidence'] += df['conf_fvg']

        # ── Modifier: RSI momentum room ──
        rsi_ok = df['rsi'].notna() & (
            (ob_bullish & (df['rsi'] < 55)) |
            (ob_bearish & (df['rsi'] > 45))
        )
        df['conf_rsi'] = np.where(base_setup & rsi_ok, 0.12, 0.0)
        df['confidence'] += df['conf_rsi']

        # ── Modifier: Volume confirmation ──
        vol_ok = df['volume_ma'].notna() & (df['volume'] > df['volume_ma'])
        df['conf_vol'] = np.where(base_setup & vol_ok, 0.08, 0.0)
        df['confidence'] += df['conf_vol']

        # ── Modifier: Recent structural event ──
        choch_bull = df.get('event_choch_bullish_recent', pd.Series(False, index=df.index))
        choch_bear = df.get('event_choch_bearish_recent', pd.Series(False, index=df.index))
        bos_bull = df.get('event_bos_bullish_recent', pd.Series(False, index=df.index))
        bos_bear = df.get('event_bos_bearish_recent', pd.Series(False, index=df.index))
        recent_structure = (
            (ob_bullish & ((choch_bull == True) | (bos_bull == True))) |
            (ob_bearish & ((choch_bear == True) | (bos_bear == True)))
        )
        df['conf_structure'] = np.where(base_setup & recent_structure, 0.08, 0.0)
        df['confidence'] += df['conf_structure']

        # ── Modifier: Wick quality ──
        body = (df['close'] - df['open']).abs()
        lower_wick = np.minimum(df['open'], df['close']) - df['low']
        upper_wick = df['high'] - np.maximum(df['open'], df['close'])
        wick_ok = (
            (ob_bullish & (body > 0) & (lower_wick > 0.5 * body)) |
            (ob_bearish & (body > 0) & (upper_wick > 0.5 * body))
        )
        df['conf_wick'] = np.where(base_setup & wick_ok, 0.05, 0.0)
        df['confidence'] += df['conf_wick']

        # ── Modifier: Impulse strength (zone compactness) ──
        atr_ok = df['atr'].notna() & (df['atr'] > 0)
        zone_compact = atr_ok & ob_upper_ok & ob_lower_ok & (
            (df['ob_upper'] - df['ob_lower']) < 2 * df['atr']
        )
        df['conf_zone'] = np.where(base_setup & zone_compact, 0.05, 0.0)
        df['confidence'] += df['conf_zone']

        # ── Trigger ──
        df['signal'] = np.where(df['confidence'] >= self.min_confidence, 1, 0)

        # ── Direction ──
        df['direction'] = None
        df.loc[(df['signal'] == 1) & ob_bullish, 'direction'] = 'LONG'
        df.loc[(df['signal'] == 1) & ob_bearish, 'direction'] = 'SHORT'

        return df

    # ── Legacy scan() — preserved for backward compatibility ──

    LOOKBACK = 20
    MAX_IMPULSE_LEN = 5
    MIN_IMPULSE_LEN = 2
    ATR_DISPLACEMENT = 1.5
    BOS_LOOKBACK = 15
    MIN_RR = 1.5
    STRICT_HTF_ALIGNMENT = True
    COOLDOWN_CANDLES = 5

    def _find_fvg(self, candles, impulse_start, impulse_end, direction):
        upper_bound = min(impulse_end + 1, len(candles))
        for j in range(impulse_start + 2, upper_bound):
            c_before = candles[j - 2]
            c_after = candles[j]
            if direction == "BULL" and c_after.low > c_before.high:
                fvg_top = c_after.low
                fvg_bottom = c_before.high
                for k in range(j + 1, len(candles) - 1):
                    if candles[k].low <= fvg_bottom: break
                else: return {"top": fvg_top, "bottom": fvg_bottom, "index": j}
            elif direction == "BEAR" and c_after.high < c_before.low:
                fvg_top = c_before.low
                fvg_bottom = c_after.high
                for k in range(j + 1, len(candles) - 1):
                    if candles[k].high >= fvg_top: break
                else: return {"top": fvg_top, "bottom": fvg_bottom, "index": j}
        return None

    def _has_bos(self, candles, ob_index, impulse_end, direction):
        lookback_start = max(0, ob_index - self.BOS_LOOKBACK)
        if lookback_start >= ob_index: return False
        prior_candles = candles[lookback_start:ob_index]
        impulse_candles = candles[ob_index + 1: impulse_end + 1]
        if not prior_candles or not impulse_candles: return False
        if direction == "BULL":
            return max(c.high for c in impulse_candles) > max(c.high for c in prior_candles)
        else:
            return min(c.low for c in impulse_candles) < min(c.low for c in prior_candles)

    def _ob_is_mitigated(self, candles, impulse_end, ob_low, ob_high, direction):
        for k in range(impulse_end + 1, len(candles)):
            c = candles[k]
            if direction == "BULL" and c.close < ob_low: return True
            if direction == "BEAR" and c.close > ob_high: return True
        return False

    def _in_cooldown(self, candles, impulse_end, ob_low, ob_high):
        candles_in_zone = 0
        for c in candles[impulse_end + 1: -1]:
            body_top = max(c.open, c.close)
            body_bottom = min(c.open, c.close)
            if body_top >= ob_low and body_bottom <= ob_high:
                candles_in_zone += 1
                if candles_in_zone >= self.COOLDOWN_CANDLES: return True
        return False

    def _evaluate_ob_candidate(self, candles, indicators, ob_idx, direction,
                                symbol, timeframe, current, htf_bias):
        ob_candle = candles[ob_idx]
        if direction == "BULL" and not ob_candle.is_bearish: return None
        if direction == "BEAR" and not ob_candle.is_bullish: return None

        impulse_candles = []
        for j in range(ob_idx + 1, min(ob_idx + 1 + self.MAX_IMPULSE_LEN, len(candles) - 1)):
            c = candles[j]
            if direction == "BULL" and c.is_bullish: impulse_candles.append(c)
            elif direction == "BEAR" and c.is_bearish: impulse_candles.append(c)
            else: break

        if len(impulse_candles) < self.MIN_IMPULSE_LEN: return None

        impulse_end_idx = ob_idx + len(impulse_candles)
        if direction == "BULL":
            impulse_size = impulse_candles[-1].close - impulse_candles[0].open
        else:
            impulse_size = impulse_candles[0].open - impulse_candles[-1].close

        if indicators.atr_14 and impulse_size < indicators.atr_14 * self.ATR_DISPLACEMENT:
            return None

        if not self._has_bos(candles, ob_idx, impulse_end_idx, direction): return None

        fvg = self._find_fvg(candles, ob_idx + 1, impulse_end_idx, direction)
        ob_high, ob_low = ob_candle.high, ob_candle.low

        if self._ob_is_mitigated(candles, impulse_end_idx, ob_low, ob_high, direction): return None
        if self._in_cooldown(candles, impulse_end_idx, ob_low, ob_high): return None

        price_in_zone = (
            (ob_low <= current.low <= ob_high) or
            (ob_low <= current.close <= ob_high) or
            (ob_low <= current.high <= ob_high)
        )
        if not price_in_zone: return None

        if direction == "BULL" and current.close < ob_low: return None
        if direction == "BEAR" and current.close > ob_high: return None

        if self.STRICT_HTF_ALIGNMENT and htf_bias:
            if direction == "BULL" and htf_bias == "BEAR": return None
            if direction == "BEAR" and htf_bias == "BULL": return None

        if direction == "BULL" and current.lower_wick < current.body_size * 0.5: return None
        if direction == "BEAR" and current.upper_wick < current.body_size * 0.5: return None

        candle_mid = (current.high + current.low) / 2
        if direction == "BULL" and current.close <= candle_mid: return None
        if direction == "BEAR" and current.close >= candle_mid: return None

        trade_direction = "LONG" if direction == "BULL" else "SHORT"
        atr = indicators.atr_14 or 0

        if direction == "BULL": sl = round(ob_low - (0.5 * atr), 8)
        else: sl = round(ob_high + (0.5 * atr), 8)

        entry = current.close
        risk = abs(entry - sl)
        if atr > 0 and risk > atr * self.MAX_RISK_ATR: return None
        risk = max(risk, atr * 0.1)

        tp1, tp2 = self._compute_structural_tp(candles, entry, sl, risk, direction, atr)
        projected_rr = abs(tp1 - entry) / risk if risk > 0 else 0

        confidence = 0.55
        if fvg: confidence += 0.10
        if direction == "BULL" and indicators.rsi_14 and indicators.rsi_14 < 55: confidence += 0.08
        if direction == "BEAR" and indicators.rsi_14 and indicators.rsi_14 > 45: confidence += 0.08
        if indicators.volume_ma_20 and current.volume > indicators.volume_ma_20: confidence += 0.08
        if len(impulse_candles) >= 3: confidence += 0.05
        confidence = min(max(confidence, 0.0), 1.0)
        if confidence < self.min_confidence: return None

        fvg_text = f"FVG: {fvg['bottom']:.2f}-{fvg['top']:.2f}. " if fvg else "No FVG (soft gate). "

        return SetupSignal(
            strategy_name=self.name, symbol=symbol, timeframe=timeframe,
            direction=trade_direction, confidence=round(confidence, 4),
            entry=entry, sl=sl, tp1=tp1, tp2=tp2,
            notes=(
                f"{'Bullish' if direction == 'BULL' else 'Bearish'} OB retest. "
                f"OB zone: {ob_low:.2f}-{ob_high:.2f}. {fvg_text}"
                f"Proj. RR: {projected_rr:.2f}R. HTF bias: {htf_bias or 'N/A'}."
            ),
        )

    def _compute_structural_tp(self, candles, entry, sl, risk, direction, atr):
        window_start = max(0, len(candles) - self.TP_FRACTAL_LOOKBACK)
        window = candles[window_start:]
        fractal_highs, fractal_lows = [], []
        if len(window) > self.PIVOT_BARS * 2 + 1:
            fractal_highs, fractal_lows = find_fractal_points(
                window[: -self.PIVOT_BARS], self.PIVOT_BARS
            )
        if direction == "BULL" and fractal_highs:
            above = sorted([lvl for _, lvl in fractal_highs if lvl > entry])
            valid = [lvl for lvl in above if (lvl - entry) / risk >= self.MIN_RR]
            if valid: return (round(valid[0], 8), round(valid[-1], 8) if len(valid) > 1 else round(entry + 3.0 * risk, 8))
        if direction == "BEAR" and fractal_lows:
            below = sorted([lvl for _, lvl in fractal_lows if lvl < entry], reverse=True)
            valid = [lvl for lvl in below if (entry - lvl) / risk >= self.MIN_RR]
            if valid: return (round(valid[0], 8), round(valid[-1], 8) if len(valid) > 1 else round(entry - 3.0 * risk, 8))
        if direction == "BULL": return (round(entry + (self.MIN_RR * risk), 8), round(entry + (3.0 * risk), 8))
        else: return (round(entry - (self.MIN_RR * risk), 8), round(entry - (3.0 * risk), 8))

    def scan(self, symbol, timeframe, candles, indicators, sr_zones, htf_candles=None):
        if len(candles) < self.LOOKBACK + self.MAX_IMPULSE_LEN + 5: return None
        if indicators.atr_14 is None: return None
        current = candles[-1]
        if current.body_size > 2 * indicators.atr_14: return None
        htf_bias = None
        if htf_candles and len(htf_candles) >= 20:
            htf_baseline = sum(c.close for c in htf_candles[-20:]) / 20
            htf_bias = "BULL" if htf_candles[-1].close > htf_baseline else "BEAR"
        scan_start = max(0, len(candles) - self.LOOKBACK)
        scan_end = len(candles) - self.MIN_IMPULSE_LEN - 1
        for i in range(scan_start, scan_end):
            for direction in ("BULL", "BEAR"):
                signal = self._evaluate_ob_candidate(candles, indicators, i, direction,
                                                      symbol, timeframe, current, htf_bias)
                if signal is not None: return signal
        return None

    def calculate_sl(self, signal, candles, atr):
        if signal.sl is not None: return signal.sl
        if signal.direction == "LONG": return round(min(c.low for c in candles[-3:]) - (1.0 * atr), 8)
        else: return round(max(c.high for c in candles[-3:]) + (1.0 * atr), 8)

    def calculate_tp(self, signal, candles, atr, sr_zones=None):
        if signal.tp1 is not None and signal.tp2 is not None: return (signal.tp1, signal.tp2)
        entry = signal.entry or candles[-1].close
        sl = self.calculate_sl(signal, candles, atr)
        risk = max(abs(entry - sl), atr * 0.1)
        if signal.direction == "LONG": return (round(entry + 1.5 * risk, 8), round(entry + 3.0 * risk, 8))
        else: return (round(entry - 1.5 * risk, 8), round(entry - 3.0 * risk, 8))

    def should_confirm_with_llm(self, signal):
        return True
