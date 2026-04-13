"""
Fair Value Gap (FVG) Mitigation Strategy
Smart Money Concept focusing on market imbalances.

Bullish FVG: Fast rally leaves a gap between C1 High and C3 Low. When price drops back into this gap and shows rejection, go LONG.
Bearish FVG: Fast drop leaves a gap between C1 Low and C3 High. When price rallies back into this gap and shows rejection, go SHORT.
"""

from app.core.base_strategy import BaseStrategy, Candle, Indicators, SetupSignal

class FVGMitigationStrategy(BaseStrategy):
    name = "FVG Mitigation"
    description = "Trades the mitigation of Fair Value Gaps (Imbalances) with confluence"
    timeframes = ["15m", "1h", "4h"]
    version = "1.1"
    min_confidence = 0.55

    def scan(self, symbol, timeframe, candles, indicators, sr_zones):
        if len(candles) < 15:
            return None

        # We look back up to 10 candles to find an unmitigated FVG
        # A bullish FVG is formed by candles at i-2, i-1, i
        # Gap is between i-2 High and i Low
        
        current_candle = candles[-1]
        
        # Look for Bullish FVG in the last 10 candles
        for i in range(len(candles) - 10, len(candles) - 1):
            if i < 2:
                continue
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
                    if current_candle.is_bullish:
                        confidence = 0.60
                        
                        # +0.10 if RSI below 50 (not overbought, room to grow)
                        if indicators.rsi_14 and indicators.rsi_14 < 50:
                            confidence += 0.10
                        
                        # +0.15 if strong rejection wick
                        if current_candle.lower_wick > current_candle.body_size * 1.5:
                            confidence += 0.15
                        
                        # +0.10 if volume confirms
                        if indicators.volume_ma_20 and current_candle.volume > indicators.volume_ma_20:
                            confidence += 0.10
                            
                        return SetupSignal(
                            strategy_name=self.name,
                            symbol=symbol,
                            timeframe=timeframe,
                            direction="LONG",
                            confidence=min(confidence, 1.0),
                            entry=current_candle.close,
                            notes=f"Bullish FVG mitigation detected from candles {c1.open_time.strftime('%H:%M')} to {c3.open_time.strftime('%H:%M')}. FVG Zone: {fvg_bottom:.2f}-{fvg_top:.2f}",
                        )

            # Bearish FVG
            if c3.high < c1.low:
                fvg_top = c1.low
                fvg_bottom = c3.high
                
                # Check if current price is inside the FVG (mitigating it)
                if fvg_bottom <= current_candle.high <= fvg_top or fvg_bottom <= current_candle.close <= fvg_top:
                    # We are in the gap. Do we have a bearish reversal sign?
                    if current_candle.is_bearish:
                        confidence = 0.60
                        
                        # +0.10 if RSI above 50 (not oversold, room to drop)
                        if indicators.rsi_14 and indicators.rsi_14 > 50:
                            confidence += 0.10
                        
                        # +0.15 if strong rejection wick
                        if current_candle.upper_wick > current_candle.body_size * 1.5:
                            confidence += 0.15
                        
                        # +0.10 if volume confirms
                        if indicators.volume_ma_20 and current_candle.volume > indicators.volume_ma_20:
                            confidence += 0.10
                            
                        return SetupSignal(
                            strategy_name=self.name,
                            symbol=symbol,
                            timeframe=timeframe,
                            direction="SHORT",
                            confidence=min(confidence, 1.0),
                            entry=current_candle.close,
                            notes=f"Bearish FVG mitigation detected from candles {c1.open_time.strftime('%H:%M')} to {c3.open_time.strftime('%H:%M')}. FVG Zone: {fvg_bottom:.2f}-{fvg_top:.2f}",
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
