"""
Fair Value Gap (FVG) Mitigation Strategy — Confluent Edition
Smart Money Concept focusing on market imbalances WITH Order Block backing.

Bullish FVG: Fast rally leaves a gap between C1 High and C3 Low. When price
drops back into this gap and shows rejection, go LONG — BUT ONLY if the
FVG is backed by a valid bullish Order Block (the last bearish candle
before the impulse that created the gap).

Bearish FVG: Fast drop leaves a gap between C1 Low and C3 High. When price
rallies back into this gap and shows rejection, go SHORT — BUT ONLY if
backed by a valid bearish Order Block.

This confluence requirement eliminates weak FVGs that lack structural
institutional backing and are likely to be sliced through.
"""

from app.core.base_strategy import BaseStrategy, Candle, Indicators, SetupSignal


class FVGMitigationStrategy(BaseStrategy):
    name = "FVG Mitigation"
    description = "Trades FVG mitigation only when backed by a valid Order Block — enforces structural confluence"
    timeframes = ["15m", "1h", "4h"]
    version = "2.0"
    min_confidence = 0.55

    def _has_adjacent_bullish_ob(self, candles: list[Candle], fvg_candle_idx: int) -> dict | None:
        """
        Check if there's a valid bullish Order Block adjacent to the FVG.
        A bullish OB is the last bearish candle before the bullish impulse
        that created the FVG. We look at the 1-3 candles immediately before
        the FVG formation candle (C1, the start of the gap).

        Returns the OB candle info dict or None.
        """
        # The FVG is formed by candles at (i-2, i-1, i). The impulse starts at i-1.
        # The OB should be a bearish candle at or just before i-2.
        for offset in range(0, 3):
            ob_idx = fvg_candle_idx - offset
            if ob_idx < 0:
                break
            candidate = candles[ob_idx]
            if candidate.is_bearish and candidate.body_size > 0:
                # Verify the candle after the OB was bullish (impulse away from OB)
                if ob_idx + 1 < len(candles) and candles[ob_idx + 1].is_bullish:
                    return {
                        'high': candidate.high,
                        'low': candidate.low,
                        'index': ob_idx,
                    }
        return None

    def _has_adjacent_bearish_ob(self, candles: list[Candle], fvg_candle_idx: int) -> dict | None:
        """
        Check if there's a valid bearish Order Block adjacent to the FVG.
        A bearish OB is the last bullish candle before the bearish impulse
        that created the FVG.
        """
        for offset in range(0, 3):
            ob_idx = fvg_candle_idx - offset
            if ob_idx < 0:
                break
            candidate = candles[ob_idx]
            if candidate.is_bullish and candidate.body_size > 0:
                if ob_idx + 1 < len(candles) and candles[ob_idx + 1].is_bearish:
                    return {
                        'high': candidate.high,
                        'low': candidate.low,
                        'index': ob_idx,
                    }
        return None

    def scan(self, symbol, timeframe, candles, indicators, sr_zones, htf_candles=None):
        if len(candles) < 15:
            return None

        current_candle = candles[-1]

        # ═══════ Exhaustion Guards ═══════
        # Reject if the current candle body is overextended (> 2× ATR)
        if indicators.atr_14 and current_candle.body_size > 2 * indicators.atr_14:
            return None

        # Look for FVGs in the last 10 candles
        for i in range(len(candles) - 10, len(candles) - 1):
            if i < 2:
                continue
            c1 = candles[i-2]
            # c2 = candles[i-1]  # The impulse candle
            c3 = candles[i]

            # ═══════ Bullish FVG ═══════
            if c3.low > c1.high:
                fvg_top = c3.low
                fvg_bottom = c1.high

                # Check if ANY intervening candle already filled this gap
                already_mitigated = False
                for k in range(i + 1, len(candles) - 1):
                    if candles[k].low <= fvg_bottom:
                        already_mitigated = True
                        break

                if already_mitigated:
                    continue  # Skip, this is a stale/dead FVG

                # Check if current price is inside the FVG (mitigating it)
                if fvg_bottom <= current_candle.low <= fvg_top or fvg_bottom <= current_candle.close <= fvg_top:
                    # RSI exhaustion: already overbought → don't go LONG
                    if indicators.rsi_14 is not None and indicators.rsi_14 > 75:
                        continue

                    # Require rejection candle: bullish + hammer/pin bar pattern
                    if (current_candle.is_bullish
                            and current_candle.range_size > 0
                            and current_candle.lower_wick >= 0.6 * current_candle.range_size):
                        # ★ CONFLUENCE: Require an adjacent bullish Order Block ★
                        ob = self._has_adjacent_bullish_ob(candles, i - 2)
                        if ob is None:
                            continue  # No OB backing — skip this FVG

                        confidence = 0.62  # Slightly higher base due to OB confluence

                        # +0.10 if RSI below 50 (not overbought, room to grow)
                        if indicators.rsi_14 and indicators.rsi_14 < 50:
                            confidence += 0.10

                        # +0.10 if strong rejection wick
                        if current_candle.lower_wick > current_candle.body_size * 1.5:
                            confidence += 0.10

                        # +0.08 if volume confirms
                        if indicators.volume_ma_20 and current_candle.volume > indicators.volume_ma_20:
                            confidence += 0.08

                        # +0.05 if price is also inside the OB zone (double confluence)
                        if ob['low'] <= current_candle.low <= ob['high']:
                            confidence += 0.05

                        return SetupSignal(
                            strategy_name=self.name,
                            symbol=symbol,
                            timeframe=timeframe,
                            direction="LONG",
                            confidence=min(confidence, 1.0),
                            entry=current_candle.close,
                            notes=(
                                f"Bullish FVG mitigation with OB confluence. "
                                f"FVG Zone: {fvg_bottom:.2f}-{fvg_top:.2f}. "
                                f"Backing OB: {ob['low']:.2f}-{ob['high']:.2f}."
                            ),
                        )

            # ═══════ Bearish FVG ═══════
            if c3.high < c1.low:
                fvg_top = c1.low
                fvg_bottom = c3.high

                # Check if ANY intervening candle already filled this gap
                already_mitigated = False
                for k in range(i + 1, len(candles) - 1):
                    if candles[k].high >= fvg_top:
                        already_mitigated = True
                        break

                if already_mitigated:
                    continue  # Skip, this is a stale/dead FVG

                if fvg_bottom <= current_candle.high <= fvg_top or fvg_bottom <= current_candle.close <= fvg_top:
                    # RSI exhaustion: already oversold → don't go SHORT
                    if indicators.rsi_14 is not None and indicators.rsi_14 < 25:
                        continue

                    # Require rejection candle: bearish + shooting star pattern
                    if (current_candle.is_bearish
                            and current_candle.range_size > 0
                            and current_candle.upper_wick >= 0.6 * current_candle.range_size):
                        # ★ CONFLUENCE: Require an adjacent bearish Order Block ★
                        ob = self._has_adjacent_bearish_ob(candles, i - 2)
                        if ob is None:
                            continue

                        confidence = 0.62

                        if indicators.rsi_14 and indicators.rsi_14 > 50:
                            confidence += 0.10

                        if current_candle.upper_wick > current_candle.body_size * 1.5:
                            confidence += 0.10

                        if indicators.volume_ma_20 and current_candle.volume > indicators.volume_ma_20:
                            confidence += 0.08

                        if ob['low'] <= current_candle.high <= ob['high']:
                            confidence += 0.05

                        return SetupSignal(
                            strategy_name=self.name,
                            symbol=symbol,
                            timeframe=timeframe,
                            direction="SHORT",
                            confidence=min(confidence, 1.0),
                            entry=current_candle.close,
                            notes=(
                                f"Bearish FVG mitigation with OB confluence. "
                                f"FVG Zone: {fvg_bottom:.2f}-{fvg_top:.2f}. "
                                f"Backing OB: {ob['low']:.2f}-{ob['high']:.2f}."
                            ),
                        )

        return None

    def calculate_sl(self, signal, candles, atr):
        """Structural SL: Behind the rejection candle's wick at the FVG zone."""
        if signal.direction == "LONG":
            return round(candles[-1].low - (1.0 * atr), 8)
        else:
            return round(candles[-1].high + (1.0 * atr), 8)

    def calculate_tp(self, signal, candles, atr, sr_zones=None):
        """Risk-based TP: 1.5R and 3.0R from structural stop."""
        entry = signal.entry or candles[-1].close
        sl = self.calculate_sl(signal, candles, atr)
        risk = abs(entry - sl)
        risk = max(risk, atr * 0.1)
        if signal.direction == "LONG":
            return (round(entry + (1.5 * risk), 8), round(entry + (3.0 * risk), 8))
        else:
            return (round(entry - (1.5 * risk), 8), round(entry - (3.0 * risk), 8))

    def should_confirm_with_llm(self, signal: SetupSignal) -> bool:
        return True
