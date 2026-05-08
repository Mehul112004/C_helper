"""
SMC Structure Shift Strategy (HTF — 1H / 4H)

Detects Change of Character (ChoCh) and Break of Structure (BOS) using
dynamically mapped swing highs and lows.

Key distinction:
  - BOS (trend continuation): Price breaks the most recent swing point
    in the direction of the existing trend with a body close.
  - ChoCh (trend reversal): Price breaks the most recent swing point
    *against* the prevailing trend direction with a body close.

Safeguards:
  - Only body closes count — wick-only piercings are treated as
    liquidity sweeps and are explicitly rejected.
  - Requires at least 2 prior swing points to establish a trend context
    before any signal can fire.
"""

from datetime import datetime

from app.core.fractals import build_swing_map
from app.core.base_strategy import (
    ActiveZone, BaseStrategy, Candle, ExecutionMode, Indicators, SetupSignal,
)


class SMCStructureShiftStrategy(BaseStrategy):
    name = "SMC Structure Shift"
    description = (
        "Detects Change of Character (ChoCh) or Break of Structure (BOS) "
        "using dynamically mapped swing highs/lows. Only body closes count — "
        "wick sweeps are rejected."
    )
    timeframes = ["1h", "4h"]
    version = "1.0"
    min_confidence = 0.60

    execution_mode = ExecutionMode.HYBRID
    context_tf = "4h"
    execution_tf = "15m"

    LOOKBACK = 40
    PIVOT_BARS = 3    # Bars on each side for swing detection

    def _determine_trend(self, swings: list[dict]) -> str:
        """
        Determine prevailing trend from the last few swing points.
        Returns 'bullish', 'bearish', or 'neutral'.
        """
        if len(swings) < 4:
            return 'neutral'

        # Look at the last 4 swing points
        recent = swings[-4:]
        highs = [s for s in recent if s['type'] == 'high']
        lows = [s for s in recent if s['type'] == 'low']

        # Accelerating trends might only have one valid lower opposite swing point in the window
        # We ensure there are at least 2 highs + lows in total and the direction aligns
        if len(highs) + len(lows) >= 3:
            higher_highs = highs[-1]['price'] > highs[-2]['price'] if len(highs) >= 2 else True
            higher_lows = lows[-1]['price'] > lows[-2]['price'] if len(lows) >= 2 else True
            lower_highs = highs[-1]['price'] < highs[-2]['price'] if len(highs) >= 2 else True
            lower_lows = lows[-1]['price'] < lows[-2]['price'] if len(lows) >= 2 else True
            
            # Avoid cases where we assume True because len() < 2 but the existing ones contradict
            has_hh = len(highs) >= 2 and higher_highs
            has_hl = len(lows) >= 2 and higher_lows
            has_lh = len(highs) >= 2 and lower_highs
            has_ll = len(lows) >= 2 and lower_lows

            if (has_hh and higher_lows) or (higher_highs and has_hl):
                return 'bullish'
            elif (has_lh and lower_lows) or (lower_highs and has_ll):
                return 'bearish'

        return 'neutral'

    def scan(self, symbol, timeframe, candles, indicators, sr_zones, htf_candles=None):
        if len(candles) < self.LOOKBACK + self.PIVOT_BARS:
            return None

        window = candles[-(self.LOOKBACK + self.PIVOT_BARS):]
        current = candles[-1]
        atr = indicators.atr_14 or 0
        swings = build_swing_map(window, self.PIVOT_BARS)

        if len(swings) < 4:
            return None

        trend = self._determine_trend(swings)
        if trend == 'neutral':
            return None

        # Find the most recent swing high and swing low
        last_swing_high = None
        last_swing_low = None
        for s in reversed(swings):
            if s['type'] == 'high' and last_swing_high is None:
                last_swing_high = s
            if s['type'] == 'low' and last_swing_low is None:
                last_swing_low = s
            if last_swing_high and last_swing_low:
                break

        if not last_swing_high or not last_swing_low:
            return None

        # --- Bullish BOS: Price body closes above the last swing high in a bullish trend ---
        if trend == 'bullish' and last_swing_high:
            level = last_swing_high['price']
            # Body close must be above (not just wick)
            body_close_above = current.close > level and min(current.open, current.close) > level * 0.998

            # Reject if only wick touched (body stayed below or equal)
            wick_only = current.high > level and max(current.open, current.close) <= level

            if body_close_above and not wick_only:
                confidence = 0.65
                signal_type = "BOS"

                # +0.10 for volume confirmation
                if indicators.volume_ma_20 and current.volume > indicators.volume_ma_20 * 1.2:
                    confidence += 0.10

                # +0.08 for strong body (low wick ratio)
                if current.body_size > current.range_size * 0.6:
                    confidence += 0.08

                # +0.07 for RSI momentum (not yet overbought)
                if indicators.rsi_14 and 50 < indicators.rsi_14 < 75:
                    confidence += 0.07

                # SL behind the opposite swing (last swing low) + 1.0 ATR
                sl_price = round(last_swing_low['price'] - (1.0 * atr), 8) if atr > 0 else None

                return SetupSignal(
                    strategy_name=self.name,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="LONG",
                    confidence=min(confidence, 1.0),
                    entry=current.close,
                    sl=sl_price,
                    notes=(
                        f"Bullish {signal_type}: body closed above swing high at {level:.2f}. "
                        f"Trend: {trend}. Close: {current.close:.2f}. "
                        f"SL ref: swing low {last_swing_low['price']:.2f}."
                    ),
                )

        # --- Bearish BOS: Price body closes below the last swing low in a bearish trend ---
        if trend == 'bearish' and last_swing_low:
            level = last_swing_low['price']
            body_close_below = current.close < level and max(current.open, current.close) < level * 1.002

            wick_only = current.low < level and min(current.open, current.close) >= level

            if body_close_below and not wick_only:
                confidence = 0.65
                signal_type = "BOS"

                if indicators.volume_ma_20 and current.volume > indicators.volume_ma_20 * 1.2:
                    confidence += 0.10

                if current.body_size > current.range_size * 0.6:
                    confidence += 0.08

                if indicators.rsi_14 and 25 < indicators.rsi_14 < 50:
                    confidence += 0.07

                # SL behind the opposite swing (last swing high) + 1.0 ATR
                sl_price = round(last_swing_high['price'] + (1.0 * atr), 8) if atr > 0 else None

                return SetupSignal(
                    strategy_name=self.name,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="SHORT",
                    confidence=min(confidence, 1.0),
                    entry=current.close,
                    sl=sl_price,
                    notes=(
                        f"Bearish {signal_type}: body closed below swing low at {level:.2f}. "
                        f"Trend: {trend}. Close: {current.close:.2f}. "
                        f"SL ref: swing high {last_swing_high['price']:.2f}."
                    ),
                )

        # --- ChoCh: Reversal against prevailing trend ---
        # Bullish ChoCh: bearish trend, but price breaks last swing high
        if trend == 'bearish' and last_swing_high:
            level = last_swing_high['price']
            body_close_above = current.close > level and min(current.open, current.close) > level * 0.998
            wick_only = current.high > level and max(current.open, current.close) <= level

            if body_close_above and not wick_only:
                confidence = 0.60  # Slightly lower — reversal is riskier

                if indicators.volume_ma_20 and current.volume > indicators.volume_ma_20 * 1.3:
                    confidence += 0.12

                if current.body_size > current.range_size * 0.6:
                    confidence += 0.08

                if indicators.rsi_14 and indicators.rsi_14 > 50:
                    confidence += 0.05

                # ChoCh SL: behind the last swing low + 1.5 ATR (wider for reversals)
                sl_price = round(last_swing_low['price'] - (1.5 * atr), 8) if atr > 0 else None

                return SetupSignal(
                    strategy_name=self.name,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="LONG",
                    confidence=min(confidence, 1.0),
                    entry=current.close,
                    sl=sl_price,
                    notes=(
                        f"Bullish ChoCh: body broke above swing high at {level:.2f} "
                        f"against prevailing bearish trend. Potential reversal. "
                        f"SL ref: swing low {last_swing_low['price']:.2f}."
                    ),
                )

        # Bearish ChoCh: bullish trend, but price breaks last swing low
        if trend == 'bullish' and last_swing_low:
            level = last_swing_low['price']
            body_close_below = current.close < level and max(current.open, current.close) < level * 1.002
            wick_only = current.low < level and min(current.open, current.close) >= level

            if body_close_below and not wick_only:
                confidence = 0.60

                if indicators.volume_ma_20 and current.volume > indicators.volume_ma_20 * 1.3:
                    confidence += 0.12

                if current.body_size > current.range_size * 0.6:
                    confidence += 0.08

                if indicators.rsi_14 and indicators.rsi_14 < 50:
                    confidence += 0.05

                # ChoCh SL: behind the last swing high + 1.5 ATR (wider for reversals)
                sl_price = round(last_swing_high['price'] + (1.5 * atr), 8) if atr > 0 else None

                return SetupSignal(
                    strategy_name=self.name,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="SHORT",
                    confidence=min(confidence, 1.0),
                    entry=current.close,
                    sl=sl_price,
                    notes=(
                        f"Bearish ChoCh: body broke below swing low at {level:.2f} "
                        f"against prevailing bullish trend. Potential reversal. "
                        f"SL ref: swing high {last_swing_high['price']:.2f}."
                    ),
                )

        return None

    def calculate_sl(self, signal, candles, atr):
        """Structural SL: Uses the swing-level SL attached at scan time.
        Falls back to 3-candle pivot + 1.0 ATR if signal.sl was not set."""
        if signal.sl is not None:
            return signal.sl

        # Fallback: structural pivot + 1.0 ATR buffer
        if signal.direction == "LONG":
            recent_low = min(c.low for c in candles[-5:])
            return round(recent_low - (1.0 * atr), 8)
        else:
            recent_high = max(c.high for c in candles[-5:])
            return round(recent_high + (1.0 * atr), 8)

    def calculate_tp(self, signal, candles, atr, sr_zones=None):
        """Risk-based TP: 2.0R and 4.0R from structural stop."""
        entry = signal.entry or candles[-1].close
        sl = self.calculate_sl(signal, candles, atr)
        risk = abs(entry - sl)
        risk = max(risk, atr * 0.1)
        if signal.direction == "LONG":
            return (round(entry + (2.0 * risk), 8), round(entry + (4.0 * risk), 8))
        else:
            return (round(entry - (2.0 * risk), 8), round(entry - (4.0 * risk), 8))

    def should_confirm_with_llm(self, signal):
        return True

    def update_context(self, symbol, htf_candles, htf_indicators, sr_zones):
        ctx = self._context_state
        ctx.clear()

        if len(htf_candles) < self.LOOKBACK + self.PIVOT_BARS:
            return

        window = htf_candles[-(self.LOOKBACK + self.PIVOT_BARS):]
        swings = build_swing_map(window, self.PIVOT_BARS)

        if len(swings) < 4:
            return

        trend = self._determine_trend(swings)
        if trend == 'neutral':
            return

        ctx.regime = trend

        last_swing_high = None
        last_swing_low = None
        for s in reversed(swings):
            if s['type'] == 'high' and last_swing_high is None:
                last_swing_high = s
            if s['type'] == 'low' and last_swing_low is None:
                last_swing_low = s
            if last_swing_high and last_swing_low:
                break

        if last_swing_high:
            ctx.active_zones.append(ActiveZone(
                zone_type="swing_point",
                direction="BEAR",
                top=last_swing_high['price'] * 1.002,
                bottom=last_swing_high['price'] * 0.998,
                metadata={'swing_type': 'high', 'price': last_swing_high['price'], 'index': last_swing_high['index']},
            ))

        if last_swing_low:
            ctx.active_zones.append(ActiveZone(
                zone_type="swing_point",
                direction="BULL",
                top=last_swing_low['price'] * 1.002,
                bottom=last_swing_low['price'] * 0.998,
                metadata={'swing_type': 'low', 'price': last_swing_low['price'], 'index': last_swing_low['index']},
            ))

        ctx.indicators_snapshot = {
            'rsi_14': htf_indicators.rsi_14,
            'atr_14': htf_indicators.atr_14,
        }
        ctx.last_updated = datetime.utcnow()

    def evaluate_trigger(self, symbol, timeframe, ltf_candles, ltf_indicators, current_price):
        ctx = self._context_state
        if not ctx.last_updated:
            return None

        if not ctx.active_zones or not ltf_candles:
            return None

        current = ltf_candles[-1]
        atr = ltf_indicators.atr_14 or 0

        last_swing_high = None
        last_swing_low = None
        for az in ctx.active_zones:
            if az.metadata.get('swing_type') == 'high':
                last_swing_high = az.metadata
            elif az.metadata.get('swing_type') == 'low':
                last_swing_low = az.metadata

        if not last_swing_high or not last_swing_low:
            return None

        trend = ctx.regime
        signal = None

        # --- Bullish BOS ---
        if trend == 'bullish':
            level = last_swing_high['price']
            body_close_above = current.close > level and min(current.open, current.close) > level * 0.998
            wick_only = current.high > level and max(current.open, current.close) <= level

            if body_close_above and not wick_only:
                confidence = 0.65
                if ltf_indicators.volume_ma_20 and current.volume > ltf_indicators.volume_ma_20 * 1.2:
                    confidence += 0.10
                if current.body_size > current.range_size * 0.6:
                    confidence += 0.08
                if ltf_indicators.rsi_14 and 50 < ltf_indicators.rsi_14 < 75:
                    confidence += 0.07
                sl_price = round(last_swing_low['price'] - (1.0 * atr), 8) if atr > 0 else None
                signal = SetupSignal(
                    strategy_name=self.name, symbol=symbol, timeframe=timeframe,
                    direction="LONG", confidence=min(confidence, 1.0),
                    entry=current.close, sl=sl_price,
                    notes=f"Bullish BOS: body closed above swing high at {level:.2f}. Trend: {trend}.",
                )

        # --- Bearish BOS ---
        if trend == 'bearish' and not signal:
            level = last_swing_low['price']
            body_close_below = current.close < level and max(current.open, current.close) < level * 1.002
            wick_only = current.low < level and min(current.open, current.close) >= level

            if body_close_below and not wick_only:
                confidence = 0.65
                if ltf_indicators.volume_ma_20 and current.volume > ltf_indicators.volume_ma_20 * 1.2:
                    confidence += 0.10
                if current.body_size > current.range_size * 0.6:
                    confidence += 0.08
                if ltf_indicators.rsi_14 and 25 < ltf_indicators.rsi_14 < 50:
                    confidence += 0.07
                sl_price = round(last_swing_high['price'] + (1.0 * atr), 8) if atr > 0 else None
                signal = SetupSignal(
                    strategy_name=self.name, symbol=symbol, timeframe=timeframe,
                    direction="SHORT", confidence=min(confidence, 1.0),
                    entry=current.close, sl=sl_price,
                    notes=f"Bearish BOS: body closed below swing low at {level:.2f}. Trend: {trend}.",
                )

        # --- Bullish ChoCh ---
        if trend == 'bearish' and not signal:
            level = last_swing_high['price']
            body_close_above = current.close > level and min(current.open, current.close) > level * 0.998
            wick_only = current.high > level and max(current.open, current.close) <= level

            if body_close_above and not wick_only:
                confidence = 0.60
                if ltf_indicators.volume_ma_20 and current.volume > ltf_indicators.volume_ma_20 * 1.3:
                    confidence += 0.12
                if current.body_size > current.range_size * 0.6:
                    confidence += 0.08
                if ltf_indicators.rsi_14 and ltf_indicators.rsi_14 > 50:
                    confidence += 0.05
                sl_price = round(last_swing_low['price'] - (1.5 * atr), 8) if atr > 0 else None
                signal = SetupSignal(
                    strategy_name=self.name, symbol=symbol, timeframe=timeframe,
                    direction="LONG", confidence=min(confidence, 1.0),
                    entry=current.close, sl=sl_price,
                    notes=f"Bullish ChoCh: body broke above swing high at {level:.2f} against bearish trend.",
                )

        # --- Bearish ChoCh ---
        if trend == 'bullish' and not signal:
            level = last_swing_low['price']
            body_close_below = current.close < level and max(current.open, current.close) < level * 1.002
            wick_only = current.low < level and min(current.open, current.close) >= level

            if body_close_below and not wick_only:
                confidence = 0.60
                if ltf_indicators.volume_ma_20 and current.volume > ltf_indicators.volume_ma_20 * 1.3:
                    confidence += 0.12
                if current.body_size > current.range_size * 0.6:
                    confidence += 0.08
                if ltf_indicators.rsi_14 and ltf_indicators.rsi_14 < 50:
                    confidence += 0.05
                sl_price = round(last_swing_high['price'] + (1.5 * atr), 8) if atr > 0 else None
                signal = SetupSignal(
                    strategy_name=self.name, symbol=symbol, timeframe=timeframe,
                    direction="SHORT", confidence=min(confidence, 1.0),
                    entry=current.close, sl=sl_price,
                    notes=f"Bearish ChoCh: body broke below swing low at {level:.2f} against bullish trend.",
                )

        if signal is None:
            return None

        signal.htf_context_summary = f"HTF trend: {trend}, swing_high={last_swing_high['price']:.2f}, swing_low={last_swing_low['price']:.2f}"
        signal.ltf_trigger_summary = f"Body close through structural level on {timeframe}"
        return signal
