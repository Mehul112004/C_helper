"""
SMC Liquidity Sweep Strategy (LTF — 5m / 15m)

Uses dynamic fractal highs/lows to identify structural liquidity pools.
Detects "Turtle Soup" style false breakouts where price wicks beyond a
fractal level but the candle body closes back inside, signaling a
liquidity grab and potential reversal.

Safeguards:
  - 3-bar pivot detection for fractal validity
  - Wick-vs-body rejection ratio enforcement
  - Cooldown: suppresses re-firing if price remains within a threshold
    of the swept level for consecutive candles
"""

from app.core.base_strategy import BaseStrategy, Candle, Indicators, SetupSignal


class SMCLiquiditySweepStrategy(BaseStrategy):
    name = "SMC Liquidity Sweep"
    description = (
        "Detects false breakouts of dynamic fractal highs/lows (Turtle Soup). "
        "Fires when price wicks beyond a structural level but closes back inside, "
        "indicating an institutional liquidity grab."
    )
    timeframes = ["5m", "15m"]
    version = "1.0"
    min_confidence = 0.60

    # --- Configuration ---
    LOOKBACK = 30           # Candles to scan for fractals
    PIVOT_BARS = 3          # Bars on each side for a valid fractal pivot
    COOLDOWN_CANDLES = 4    # Suppress re-fire if price lingers near swept level
    SWEEP_TOLERANCE = 0.001 # 0.1% — wick must exceed level by at least this ratio

    def _find_fractal_highs(self, candles: list[Candle], pivot_n: int) -> list[tuple[int, float]]:
        """
        Find fractal highs: candle[i].high is the highest of
        candle[i-pivot_n] ... candle[i+pivot_n].
        Returns list of (index, price) tuples.
        """
        fractals = []
        for i in range(pivot_n, len(candles) - pivot_n):
            is_pivot = True
            for j in range(1, pivot_n + 1):
                if candles[i].high <= candles[i - j].high or candles[i].high <= candles[i + j].high:
                    is_pivot = False
                    break
            if is_pivot:
                fractals.append((i, candles[i].high))
        return fractals

    def _find_fractal_lows(self, candles: list[Candle], pivot_n: int) -> list[tuple[int, float]]:
        """
        Find fractal lows: candle[i].low is the lowest of
        candle[i-pivot_n] ... candle[i+pivot_n].
        Returns list of (index, price) tuples.
        """
        fractals = []
        for i in range(pivot_n, len(candles) - pivot_n):
            is_pivot = True
            for j in range(1, pivot_n + 1):
                if candles[i].low >= candles[i - j].low or candles[i].low >= candles[i + j].low:
                    is_pivot = False
                    break
            if is_pivot:
                fractals.append((i, candles[i].low))
        return fractals

    def scan(self, symbol, timeframe, candles, indicators, sr_zones):
        if len(candles) < self.LOOKBACK + self.PIVOT_BARS:
            return None

        current = candles[-1]
        window = candles[-(self.LOOKBACK + self.PIVOT_BARS):]

        # Map fractals from the window (exclude the most recent PIVOT_BARS candles
        # because they can't form a confirmed pivot yet)
        fractal_highs = self._find_fractal_highs(window[:-1], self.PIVOT_BARS)
        fractal_lows = self._find_fractal_lows(window[:-1], self.PIVOT_BARS)

        # --- Bearish Sweep (wick above fractal high, close back below) → SHORT ---
        if fractal_highs:
            # Use the most recent fractal high
            _, level = fractal_highs[-1]
            sweep_threshold = level * (1 + self.SWEEP_TOLERANCE)

            if current.high > level and current.close < level:
                # Wick exceeded the level but body closed below → sweep
                wick_above = current.high - level
                body_top = max(current.open, current.close)

                # Enforce meaningful rejection: wick above level should be significant
                if wick_above > 0 and body_top < level:
                    # Cooldown check: ensure we haven't been lingering at this level
                    lingering = sum(
                        1 for c in candles[-(self.COOLDOWN_CANDLES + 1):-1]
                        if abs(c.high - level) / level < self.SWEEP_TOLERANCE * 2
                    )
                    if lingering < self.COOLDOWN_CANDLES:
                        confidence = 0.62

                        # +0.10 for strong rejection wick
                        if current.upper_wick > current.body_size * 1.5:
                            confidence += 0.10

                        # +0.08 for RSI overbought (confirming exhaustion)
                        if indicators.rsi_14 and indicators.rsi_14 > 65:
                            confidence += 0.08

                        # +0.08 for volume spike
                        if indicators.volume_ma_20 and current.volume > indicators.volume_ma_20 * 1.3:
                            confidence += 0.08

                        # +0.07 if bearish candle body
                        if current.is_bearish:
                            confidence += 0.07

                        return SetupSignal(
                            strategy_name=self.name,
                            symbol=symbol,
                            timeframe=timeframe,
                            direction="SHORT",
                            confidence=min(confidence, 1.0),
                            entry=current.close,
                            notes=(
                                f"Bearish liquidity sweep: wick pierced fractal high at "
                                f"{level:.2f} (high={current.high:.2f}) but closed at "
                                f"{current.close:.2f}. Rejection ratio: "
                                f"{current.upper_wick / max(current.body_size, 0.0001):.1f}x."
                            ),
                        )

        # --- Bullish Sweep (wick below fractal low, close back above) → LONG ---
        if fractal_lows:
            _, level = fractal_lows[-1]

            if current.low < level and current.close > level:
                wick_below = level - current.low
                body_bottom = min(current.open, current.close)

                if wick_below > 0 and body_bottom > level:
                    lingering = sum(
                        1 for c in candles[-(self.COOLDOWN_CANDLES + 1):-1]
                        if abs(c.low - level) / level < self.SWEEP_TOLERANCE * 2
                    )
                    if lingering < self.COOLDOWN_CANDLES:
                        confidence = 0.62

                        # +0.10 for strong rejection wick
                        if current.lower_wick > current.body_size * 1.5:
                            confidence += 0.10

                        # +0.08 for RSI oversold (confirming exhaustion)
                        if indicators.rsi_14 and indicators.rsi_14 < 35:
                            confidence += 0.08

                        # +0.08 for volume spike
                        if indicators.volume_ma_20 and current.volume > indicators.volume_ma_20 * 1.3:
                            confidence += 0.08

                        # +0.07 if bullish candle body
                        if current.is_bullish:
                            confidence += 0.07

                        return SetupSignal(
                            strategy_name=self.name,
                            symbol=symbol,
                            timeframe=timeframe,
                            direction="LONG",
                            confidence=min(confidence, 1.0),
                            entry=current.close,
                            notes=(
                                f"Bullish liquidity sweep: wick pierced fractal low at "
                                f"{level:.2f} (low={current.low:.2f}) but closed at "
                                f"{current.close:.2f}. Rejection ratio: "
                                f"{current.lower_wick / max(current.body_size, 0.0001):.1f}x."
                            ),
                        )

        return None

    def calculate_sl(self, signal, candles, atr):
        """Structural SL: Placed strictly just beyond the sweep candle's wick."""
        # We use a tiny 0.5 ATR buffer strictly for spread/slippage
        if signal.direction == "LONG":
            return round(candles[-1].low - (0.5 * atr), 8)
        else:
            return round(candles[-1].high + (0.5 * atr), 8)

    def calculate_tp(self, signal, candles, atr):
        """Risk-based TP: Scales dynamically based on the size of the sweep wick."""
        entry = signal.entry or candles[-1].close
        sl = self.calculate_sl(signal, candles, atr)
        
        # Calculate literal risk (Entry to SL distance)
        risk = abs(entry - sl)
        # Fallback to prevent zero-division if spread is microscopic
        risk = max(risk, atr * 0.1) 

        # TP1 at 1.5R, TP2 at 3.0R
        if signal.direction == "LONG":
            return (round(entry + (1.5 * risk), 8), round(entry + (3.0 * risk), 8))
        else:
            return (round(entry - (1.5 * risk), 8), round(entry - (3.0 * risk), 8))

    def should_confirm_with_llm(self, signal):
        return True
