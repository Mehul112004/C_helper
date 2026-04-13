"""
Fair Value Gap (FVG) Mitigation Strategy
Smart Money Concept focusing on market imbalances.

Bullish FVG: Fast rally leaves a gap between C1 High and C3 Low. When price drops back into this gap and shows rejection, go LONG.
Bearish FVG: Fast drop leaves a gap between C1 Low and C3 High. When price rallies back into this gap and shows rejection, go SHORT.
"""

from app.core.base_strategy import BaseStrategy, Candle, Indicators, SetupSignal

class FVGMitigationStrategy(BaseStrategy):
    name = "FVG Mitigation"
    description = "Trades the mitigation of Fair Value Gaps (Imbalances) with RSI confluence"
    timeframes = ["15m", "1h", "4h"]
    version = "1.0"
    min_confidence = 0.65

    def scan(self, symbol, timeframe, candles, indicators, sr_zones):
        if len(candles) < 15:
            return None

        # We look back up to 10 candles to find an unmitigated FVG
        # A bullish FVG is formed by candles at i-2, i-1, i
        # Gap is between i-2 High and i Low
        
        current_candle = candles[-1]
        
        # Look for Bullish FVG in the last 10 candles
        for i in range(len(candles) - 10, len(candles) - 1):
            c1 = candles[i-2]
            # c2 = candles[i-1] # The impulse candle
            c3 = candles[i]
            
            # Bullish FVG
            if c3.low > c1.high:
                fvg_top = c3.low
                fvg_bottom = c1.high
                
                # Check if current price is inside the FVG (mitigating it)
                if fvg_bottom <= current_candle.low <= fvg_top or fvg_bottom <= current_candle.close <= fvg_top:
                    # We are in the gap. Do we have a bullish reversal sign?
                    if current_candle.is_bullish and indicators.rsi_14 and indicators.rsi_14 < 45:
                        confidence = 0.70
                        if current_candle.lower_wick > current_candle.body_size * 1.5:
                            confidence += 0.15 # Strong rejection wick
                            
                        return SetupSignal(
                            strategy_name=self.name,
                            symbol=symbol,
                            timeframe=timeframe,
                            direction="LONG",
                            confidence=min(confidence, 1.0),
                            entry=current_candle.close,
                            notes=f"Bullish FVG mitigation detected from candles {c1.open_time.strftime('%H:%M')} to {c3.open_time.strftime('%H:%M')}. FVG Zone: {fvg_bottom}-{fvg_top}",
                        )

            # Bearish FVG
            if c3.high < c1.low:
                fvg_top = c1.low
                fvg_bottom = c3.high
                
                # Check if current price is inside the FVG (mitigating it)
                if fvg_bottom <= current_candle.high <= fvg_top or fvg_bottom <= current_candle.close <= fvg_top:
                    # We are in the gap. Do we have a bearish reversal sign?
                    if current_candle.is_bearish and indicators.rsi_14 and indicators.rsi_14 > 55:
                        confidence = 0.70
                        if current_candle.upper_wick > current_candle.body_size * 1.5:
                            confidence += 0.15 # Strong rejection wick
                            
                        return SetupSignal(
                            strategy_name=self.name,
                            symbol=symbol,
                            timeframe=timeframe,
                            direction="SHORT",
                            confidence=min(confidence, 1.0),
                            entry=current_candle.close,
                            notes=f"Bearish FVG mitigation detected from candles {c1.open_time.strftime('%H:%M')} to {c3.open_time.strftime('%H:%M')}. FVG Zone: {fvg_bottom}-{fvg_top}",
                        )

        return None

    def calculate_sl(self, signal, candles, atr):
        """Volatility-based SL."""
        entry = signal.entry or candles[-1].close
        if signal.direction == "LONG":
            return round(entry - (1.5 * atr), 8)
        else:
            return round(entry + (1.5 * atr), 8)

    def should_confirm_with_llm(self, signal: SetupSignal) -> bool:
        return True
