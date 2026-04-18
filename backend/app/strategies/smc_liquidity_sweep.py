"""
SMC Liquidity Sweep Strategy (LTF — 5m / 15m)

Uses dynamic fractal highs/lows to identify structural liquidity pools.
Detects "Turtle Soup" style false breakouts where price wicks beyond an
UNBROKEN fractal extreme but the candle body closes back inside, signaling a
liquidity grab and potential reversal.

Safeguards:
  - 3-bar pivot detection for fractal validity
  - Extreme level validation (ignores internal broken structure)
  - Wick-vs-body rejection ratio enforcement
  - Cooldown: suppresses re-firing if price remains within a threshold
  - Volume Climax Gate: Requires institutional volume footprint
  - Sniper Entry: Limit orders at 50% wick retracement
"""

from app.core.base_strategy import BaseStrategy, Candle, Indicators, SetupSignal
from app.core.fractals import find_fractal_points

CLUSTER_TOLERANCE = 0.001   # Fractals within 0.1% are considered "equal"

def find_strongest_unbroken_fractal(fractals, absolute_extreme, direction):
    """
    Returns (average_level, cluster_size) for the densest price cluster that 
    has NOT been invalidated by a more extreme price in the window.
    direction: 1 for highs, -1 for lows.
    """
    if not fractals:
        return None, 0
    
    valid_fractals = []
    for idx, lvl in fractals:
        if direction == 1 and lvl >= absolute_extreme * (1 - CLUSTER_TOLERANCE):
            valid_fractals.append((idx, lvl))
        elif direction == -1 and lvl <= absolute_extreme * (1 + CLUSTER_TOLERANCE):
            valid_fractals.append((idx, lvl))

    if not valid_fractals:
        return None, 0

    best_level, best_count = None, 0
    for _, lvl in valid_fractals:
        cluster = [l for _, l in valid_fractals if abs(l - lvl) / lvl < CLUSTER_TOLERANCE]
        if len(cluster) > best_count:
            best_count = len(cluster)
            best_level = sum(cluster) / len(cluster)
            
    return best_level, best_count


class SMCLiquiditySweepStrategy(BaseStrategy):
    name = "SMC Liquidity Sweep"
    description = (
        "Detects false breakouts of unmitigated structural extremes. "
        "Filters for high-volume institutional footprints and utilizes "
        "50% wick limit entries for maximized RR."
    )
    timeframes = ["5m", "15m"]
    version = "1.2" # Bumped for Volume Gate & 50% Wick Limit Entries
    min_confidence = 0.60

    # --- Configuration ---
    LOOKBACK = 30           
    PIVOT_BARS = 3          
    COOLDOWN_CANDLES = 4    
    SWEEP_TOLERANCE = 0.001 

    def scan(self, symbol, timeframe, candles, indicators, sr_zones, htf_candles=None):
        if len(candles) < self.LOOKBACK + self.PIVOT_BARS + 2:
            return None

        current = candles[-1]
        window = candles[-(self.LOOKBACK + self.PIVOT_BARS):-1]

        # ═══════ Exhaustion Guards ═══════
        if indicators.atr_14 and current.body_size > 2 * indicators.atr_14:
            return None

        fractal_highs, fractal_lows = find_fractal_points(window[:-self.PIVOT_BARS], self.PIVOT_BARS)

        htf_bias = None
        if htf_candles and len(htf_candles) >= 20:
            htf_mid  = (htf_candles[-20].high + htf_candles[-20].low) / 2
            htf_bias = "BULL" if htf_candles[-1].close > htf_mid else "BEAR"

        RSI_OVERSOLD   = 30
        RSI_OVERBOUGHT = 70
        window_range = max(c.high for c in window) - min(c.low for c in window)

        # ═══════ Bearish Sweep (SHORT) ═══════
        if fractal_highs and indicators.atr_14:
            window_high = max(c.high for c in window)
            level, cluster_count = find_strongest_unbroken_fractal(fractal_highs, window_high, direction=1)
            
            if level is not None:
                non_fractal_highs = [c.high for i, c in enumerate(window) if i not in [f[0] for f in fractal_highs]]
                avg_high = sum(non_fractal_highs) / len(non_fractal_highs) if non_fractal_highs else level
                prominence = level - avg_high

                if prominence >= indicators.atr_14 * 0.5 and window_range >= indicators.atr_14 * 1.0:
                    sweep_threshold = level * (1 + self.SWEEP_TOLERANCE)

                    if current.high > sweep_threshold and current.close < level:
                        if indicators.rsi_14 is not None and indicators.rsi_14 < RSI_OVERSOLD:
                            pass 
                        else:
                            lingering = sum(
                                1 for c in candles[-(self.COOLDOWN_CANDLES + 1):-1]
                                if abs(max(c.open, c.close) - level) / level < self.SWEEP_TOLERANCE * 2
                            )
                            if lingering < 2:
                                candle_range = current.high - current.low
                                if candle_range > 0:
                                    if current.upper_wick >= current.body_size * 1.2:
                                        close_position = (current.close - current.low) / candle_range
                                        if close_position <= 0.40:
                                            
                                            # TWEAK 2: Volume Climax Gate (Hard Filter)
                                            if indicators.volume_ma_20 and current.volume < (indicators.volume_ma_20 * 1.2):
                                                pass 
                                            else:
                                                confidence = 0.65

                                                if current.upper_wick > current.body_size * 2.0:
                                                    confidence += 0.10
                                                if indicators.rsi_14 and indicators.rsi_14 > RSI_OVERBOUGHT:
                                                    confidence += 0.08
                                                if cluster_count >= 2:
                                                    confidence += 0.08
                                                if htf_bias == "BULL":
                                                    confidence -= 0.15

                                                if confidence >= self.min_confidence:
                                                    prev = candles[-2]
                                                    ob_top = max(prev.open, prev.close)
                                                    ob_bottom = min(prev.open, prev.close)
                                                    
                                                    # TWEAK 1: Sniper Limit Entry (50% Wick)
                                                    entry = round(current.close + ((current.high - current.close) * 0.5), 8)
                                                    entry_note = f"... Aggressive Limit Entry at 50% wick: {entry:.2f}."

                                                    return SetupSignal(
                                                        strategy_name=self.name,
                                                        symbol=symbol, timeframe=timeframe, direction="SHORT",
                                                        confidence=min(confidence, 1.0), entry=entry,
                                                        notes=(f"Bearish Sweep: Wick pierced unmitigated high at "
                                                               f"{level:.2f} but closed lower. "
                                                               f"Rejection wick is {current.upper_wick / max(current.body_size, 0.0001):.1f}x body. "
                                                               f"{entry_note} Target OB: [{ob_bottom:.2f} - {ob_top:.2f}].")
                                                    )

        # ═══════ Bullish Sweep (LONG) ═══════
        if fractal_lows and indicators.atr_14:
            window_low = min(c.low for c in window)
            level, cluster_count = find_strongest_unbroken_fractal(fractal_lows, window_low, direction=-1)
            
            if level is not None:
                non_fractal_lows = [c.low for i, c in enumerate(window) if i not in [f[0] for f in fractal_lows]]
                avg_low = sum(non_fractal_lows) / len(non_fractal_lows) if non_fractal_lows else level
                prominence = avg_low - level

                if prominence >= indicators.atr_14 * 0.5 and window_range >= indicators.atr_14 * 1.0:
                    sweep_threshold = level * (1 - self.SWEEP_TOLERANCE)

                    if current.low < sweep_threshold and current.close > level:
                        if indicators.rsi_14 is not None and indicators.rsi_14 > RSI_OVERBOUGHT:
                            pass 
                        else:
                            lingering = sum(
                                1 for c in candles[-(self.COOLDOWN_CANDLES + 1):-1]
                                if abs(min(c.open, c.close) - level) / level < self.SWEEP_TOLERANCE * 2
                            )
                            if lingering < 2:
                                candle_range = current.high - current.low
                                if candle_range > 0:
                                    if current.lower_wick >= current.body_size * 1.2:
                                        close_position = (current.close - current.low) / candle_range
                                        if close_position >= 0.60:
                                            
                                            # TWEAK 2: Volume Climax Gate (Hard Filter)
                                            if indicators.volume_ma_20 and current.volume < (indicators.volume_ma_20 * 1.2):
                                                pass
                                            else:
                                                confidence = 0.65

                                                if current.lower_wick > current.body_size * 2.0:
                                                    confidence += 0.10
                                                if indicators.rsi_14 and indicators.rsi_14 < RSI_OVERSOLD:
                                                    confidence += 0.08
                                                if cluster_count >= 2:
                                                    confidence += 0.08
                                                if htf_bias == "BEAR":
                                                    confidence -= 0.15

                                                if confidence >= self.min_confidence:
                                                    prev = candles[-2]
                                                    ob_top = max(prev.open, prev.close)
                                                    ob_bottom = min(prev.open, prev.close)
                                                    
                                                    # TWEAK 1: Sniper Limit Entry (50% Wick)
                                                    entry = round(current.close - ((current.close - current.low) * 0.5), 8)
                                                    entry_note = f"... Aggressive Limit Entry at 50% wick: {entry:.2f}."

                                                    return SetupSignal(
                                                        strategy_name=self.name,
                                                        symbol=symbol, timeframe=timeframe, direction="LONG",
                                                        confidence=min(confidence, 1.0), entry=entry,
                                                        notes=(f"Bullish Sweep: Wick pierced unmitigated low at "
                                                               f"{level:.2f} but closed higher. "
                                                               f"Rejection wick is {current.lower_wick / max(current.body_size, 0.0001):.1f}x body. "
                                                               f"{entry_note} Target OB: [{ob_bottom:.2f} - {ob_top:.2f}].")
                                                    )

        return None

    def calculate_sl(self, signal, candles, atr):
        """
        Structural SL: placed beyond the extreme wick of the sweep candle.
        TWEAK 3: Buffer widened to 0.5 ATR to survive institutional "double sweeps".
        """
        buffer = atr * 0.5
        if signal.direction == "LONG":
            return round(candles[-1].low - buffer, 8)
        else:
            return round(candles[-1].high + buffer, 8)

    def calculate_tp(self, signal, candles, atr, sr_zones=None):
        """
        Structural TP: targets the nearest opposing liquidity pool.
        Falls back to R-multiples if no structural target is found.
        """
        entry = signal.entry or candles[-1].close
        sl = self.calculate_sl(signal, candles, atr)
        risk = max(abs(entry - sl), atr * 0.1)

        window = candles[-self.LOOKBACK:]
        fractal_highs, fractal_lows = find_fractal_points(
            window[:-self.PIVOT_BARS], self.PIVOT_BARS
        )

        if signal.direction == "SHORT" and fractal_lows:
            below = [(i, lvl) for i, lvl in fractal_lows if lvl < entry]
            if below:
                tp1 = round(below[-1][1], 8)
                tp2 = round(below[0][1], 8) if len(below) > 1 else round(entry - 3.0 * risk, 8)
                return (tp1, tp2)

        if signal.direction == "LONG" and fractal_highs:
            above = [(i, lvl) for i, lvl in fractal_highs if lvl > entry]
            if above:
                tp1 = round(above[0][1], 8)
                tp2 = round(above[-1][1], 8) if len(above) > 1 else round(entry + 3.0 * risk, 8)
                return (tp1, tp2)

        if signal.direction == "LONG":
            return (round(entry + 1.5 * risk, 8), round(entry + 3.0 * risk, 8))
        else:
            return (round(entry - 1.5 * risk, 8), round(entry - 3.0 * risk, 8))

    def should_confirm_with_llm(self, signal):
        return True