"""
Institutional Order Block (OB) Retest Strategy — Confluent Edition
Smart Money Concept focusing on institutional accumulation/distribution zones
WITH Fair Value Gap (FVG) imbalance validation.

Bullish OB: The last down candle before a significant bullish impulse.
When price returns to this block's range, we look for a rejection to go LONG
— BUT ONLY if the impulse away from the OB left behind an unmitigated FVG,
proving aggressive institutional displacement.

Bearish OB: The last up candle before a significant bearish impulse.
Requires the impulse to have left an FVG to confirm institutional intent.

An Order Block without an FVG lacks the "imbalance" required to prove
aggressive institutional involvement — these are filtered out.
"""

from app.core.base_strategy import BaseStrategy, Candle, Indicators, SetupSignal


class OrderBlockRetestStrategy(BaseStrategy):
    name = "Order Block Retest"
    description = "Detects OB retests only when the departure impulse left an unmitigated FVG — enforces displacement confluence."
    timeframes = ["1h", "4h", "1d"]
    version = "2.0"
    min_confidence = 0.60

    def _impulse_has_bullish_fvg(self, candles: list[Candle], impulse_start: int, impulse_end: int) -> dict | None:
        """
        Check whether the bullish impulse (from impulse_start to impulse_end)
        left behind an unmitigated Fair Value Gap.

        A bullish FVG exists when candle[j].low > candle[j-2].high for some j
        in the impulse range — i.e., a gap between wicks that price never filled.

        Returns the FVG zone dict or None.
        """
        for j in range(impulse_start + 2, min(impulse_end + 1, len(candles))):
            c_before = candles[j - 2]
            c_after = candles[j]
            if c_after.low > c_before.high:
                fvg_top = c_after.low
                fvg_bottom = c_before.high

                # Check if the FVG has been mitigated (price returned and filled it)
                # by any candle after the FVG formation up to now
                mitigated = False
                for k in range(j + 1, len(candles)):
                    if candles[k].low <= fvg_bottom:
                        mitigated = True
                        break

                if not mitigated:
                    return {'top': fvg_top, 'bottom': fvg_bottom, 'index': j}

        return None

    def _impulse_has_bearish_fvg(self, candles: list[Candle], impulse_start: int, impulse_end: int) -> dict | None:
        """
        Check whether the bearish impulse left behind a bearish FVG.
        A bearish FVG: candle[j].high < candle[j-2].low
        """
        for j in range(impulse_start + 2, min(impulse_end + 1, len(candles))):
            c_before = candles[j - 2]
            c_after = candles[j]
            if c_after.high < c_before.low:
                fvg_top = c_before.low
                fvg_bottom = c_after.high

                mitigated = False
                for k in range(j + 1, len(candles)):
                    if candles[k].high >= fvg_top:
                        mitigated = True
                        break

                if not mitigated:
                    return {'top': fvg_top, 'bottom': fvg_bottom, 'index': j}

        return None

    def scan(self, symbol, timeframe, candles, indicators, sr_zones):
        if len(candles) < 20:
            return None

        current_candle = candles[-1]

        # Look back to find a valid order block (OB) created in the past 15 candles
        for i in range(len(candles) - 15, len(candles) - 3):
            if i < 0:
                continue

            # ═══════ Bullish OB: Bearish candle → strong bullish impulse ═══════
            if candles[i].is_bearish:
                # Check next 2 candles for strong bullish impulse
                impulse_candles = candles[i+1:i+3]
                if len(impulse_candles) >= 2 and all(c.is_bullish for c in impulse_candles):
                    impulse_size = impulse_candles[-1].close - impulse_candles[0].open
                    avg_body = sum(c.body_size for c in impulse_candles) / len(impulse_candles)

                    if impulse_size > avg_body * 1.5:
                        ob_high = candles[i].high
                        ob_low = candles[i].low

                        # ★ CONFLUENCE: The impulse must have left a bullish FVG ★
                        fvg = self._impulse_has_bullish_fvg(candles, i + 1, i + 3)
                        if fvg is None:
                            continue  # No FVG displacement — skip this OB

                        # Verify price has retraced to the OB
                        if ob_low <= current_candle.low <= ob_high or ob_low <= current_candle.close <= ob_high:
                            # Rejection condition: lower wick shows buying pressure
                            if current_candle.lower_wick > current_candle.body_size * 0.8:
                                confidence = 0.67  # Higher base due to FVG confluence

                                # +0.08 if RSI supports (not overbought)
                                if indicators.rsi_14 and indicators.rsi_14 < 55:
                                    confidence += 0.08

                                # +0.08 if volume confirms
                                if indicators.volume_ma_20 and current_candle.volume > indicators.volume_ma_20:
                                    confidence += 0.08

                                # +0.05 bonus if the FVG is still completely unmitigated
                                if fvg:
                                    confidence += 0.05

                                return SetupSignal(
                                    strategy_name=self.name,
                                    symbol=symbol,
                                    timeframe=timeframe,
                                    direction="LONG",
                                    confidence=min(confidence, 1.0),
                                    entry=current_candle.close,
                                    notes=(
                                        f"Bullish OB retest with FVG confluence. "
                                        f"OB zone: {ob_low:.2f}-{ob_high:.2f}. "
                                        f"Unmitigated FVG: {fvg['bottom']:.2f}-{fvg['top']:.2f}. "
                                        f"Originated at {candles[i].open_time.strftime('%Y-%m-%d %H:%M')}."
                                    ),
                                )

            # ═══════ Bearish OB: Bullish candle → strong bearish impulse ═══════
            if candles[i].is_bullish:
                impulse_candles = candles[i+1:i+3]
                if len(impulse_candles) >= 2 and all(c.is_bearish for c in impulse_candles):
                    impulse_size = impulse_candles[0].open - impulse_candles[-1].close
                    avg_body = sum(c.body_size for c in impulse_candles) / len(impulse_candles)

                    if impulse_size > avg_body * 1.5:
                        ob_high = candles[i].high
                        ob_low = candles[i].low

                        # ★ CONFLUENCE: The impulse must have left a bearish FVG ★
                        fvg = self._impulse_has_bearish_fvg(candles, i + 1, i + 3)
                        if fvg is None:
                            continue

                        if ob_low <= current_candle.high <= ob_high or ob_low <= current_candle.close <= ob_high:
                            if current_candle.upper_wick > current_candle.body_size * 0.8:
                                confidence = 0.67

                                if indicators.rsi_14 and indicators.rsi_14 > 45:
                                    confidence += 0.08

                                if indicators.volume_ma_20 and current_candle.volume > indicators.volume_ma_20:
                                    confidence += 0.08

                                if fvg:
                                    confidence += 0.05

                                return SetupSignal(
                                    strategy_name=self.name,
                                    symbol=symbol,
                                    timeframe=timeframe,
                                    direction="SHORT",
                                    confidence=min(confidence, 1.0),
                                    entry=current_candle.close,
                                    notes=(
                                        f"Bearish OB retest with FVG confluence. "
                                        f"OB zone: {ob_low:.2f}-{ob_high:.2f}. "
                                        f"Unmitigated FVG: {fvg['bottom']:.2f}-{fvg['top']:.2f}. "
                                        f"Originated at {candles[i].open_time.strftime('%Y-%m-%d %H:%M')}."
                                    ),
                                )

        return None

    def calculate_sl(self, signal, candles, atr):
        """Structural SL: Behind the rejection candle's wick at the OB zone."""
        if signal.direction == "LONG":
            return round(candles[-1].low - (0.1 * atr), 8)
        else:
            return round(candles[-1].high + (0.1 * atr), 8)

    def calculate_tp(self, signal, candles, atr):
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
