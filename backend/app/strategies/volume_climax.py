"""
Volume Climax / Absorption Reversal Strategy
Detects institutional absorption via volume anomalies.

Logic:
Looks for a high volume candle (Volume > 2x MA20) with a relatively small body indicating absorption of limit orders.
Occurring after a directional trend, this often spots local bottoms or tops before a reversal.
"""

from app.core.base_strategy import BaseStrategy, Candle, Indicators, SetupSignal

class VolumeClimaxStrategy(BaseStrategy):
    name = "Volume Climax"
    description = "Detects institutional stopping volume or climax buying for trend reversals."
    timeframes = ["5m", "15m", "1h"]
    version = "1.1"
    min_confidence = 0.55

    def scan(self, symbol, timeframe, candles, indicators, sr_zones):
        if len(candles) < 10 or not indicators.volume_ma_20:
            return None

        current_candle = candles[-1]
        
        # We need a significant volume anomaly (2x MA is already notable)
        if current_candle.volume <= indicators.volume_ma_20 * 2:
            return None

        volume_ratio = current_candle.volume / indicators.volume_ma_20
            
        # Check for Capitulation / Stopping Volume (Bullish Reversal)
        # Check against EMA_50 to ensure we are actually extended
        if not indicators.ema_50: return None

        # Price must be extended at least 2.5% below the 50 EMA to be a capitulation
        is_extended_down = current_candle.close < (indicators.ema_50 * 0.975)
        # Require a sustained downtrend (9 out of 15 candles bearish)
        bearish_momentum = sum(1 for c in candles[-15:-1] if c.is_bearish) >= 9

        if is_extended_down and bearish_momentum:
            # The climax candle should have a long lower wick or be a small-bodied reversal candle
            has_reversal_pattern = (
                current_candle.lower_wick > current_candle.body_size * 1.5 or
                current_candle.body_size < current_candle.range_size * 0.35
            )
            if has_reversal_pattern:
                confidence = 0.60
                
                # +0.15 if RSI oversold (< 30)
                if indicators.rsi_14 and indicators.rsi_14 < 30:
                    confidence += 0.15
                
                # +0.10 for extreme volume (3x+ MA)
                if volume_ratio >= 3:
                    confidence += 0.10
                
                # +0.05 if near S/R support zone
                if sr_zones:
                    for zone in sr_zones:
                        if zone.get('zone_type', '') in ('support', 'both'):
                            distance_pct = abs(current_candle.close - zone.get('price_level', 0)) / current_candle.close
                            if distance_pct < 0.02:
                                confidence += 0.05
                                break

                return SetupSignal(
                    strategy_name=self.name,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="LONG",
                    confidence=min(confidence, 1.0),
                    entry=current_candle.close,
                    notes=f"Volume Climax Detected: Volume is {current_candle.volume:.2f} "
                          f"({volume_ratio:.1f}x MA: {indicators.volume_ma_20:.2f}) after a downtrend. "
                          f"RSI: {indicators.rsi_14:.1f}" if indicators.rsi_14 else
                          f"Volume Climax Detected: Volume is {current_candle.volume:.2f} "
                          f"({volume_ratio:.1f}x MA: {indicators.volume_ma_20:.2f}) after a downtrend.",
                )

        # Check for Climax Buying (Bearish Reversal)
        # Price must be extended at least 2.5% above the 50 EMA
        is_extended_up = current_candle.close > (indicators.ema_50 * 1.025)
        # Require a sustained uptrend (9 out of 15 candles bullish)
        bullish_momentum = sum(1 for c in candles[-15:-1] if c.is_bullish) >= 9

        if is_extended_up and bullish_momentum:
            # The climax candle should have a long upper wick or be a small-bodied exhaustive candle
            has_exhaustion_pattern = (
                current_candle.upper_wick > current_candle.body_size * 1.5 or
                current_candle.body_size < current_candle.range_size * 0.35
            )
            if has_exhaustion_pattern:
                confidence = 0.60
                
                # +0.15 if RSI overbought (> 70)
                if indicators.rsi_14 and indicators.rsi_14 > 70:
                    confidence += 0.15
                
                # +0.10 for extreme volume (3x+ MA)
                if volume_ratio >= 3:
                    confidence += 0.10
                
                # +0.05 if near S/R resistance zone
                if sr_zones:
                    for zone in sr_zones:
                        if zone.get('zone_type', '') in ('resistance', 'both'):
                            distance_pct = abs(current_candle.close - zone.get('price_level', 0)) / current_candle.close
                            if distance_pct < 0.02:
                                confidence += 0.05
                                break

                return SetupSignal(
                    strategy_name=self.name,
                    symbol=symbol,
                    timeframe=timeframe,
                    direction="SHORT",
                    confidence=min(confidence, 1.0),
                    entry=current_candle.close,
                    notes=f"Climax Buying Detected: Volume is {current_candle.volume:.2f} "
                          f"({volume_ratio:.1f}x MA: {indicators.volume_ma_20:.2f}) after an uptrend. "
                          f"RSI: {indicators.rsi_14:.1f}" if indicators.rsi_14 else
                          f"Climax Buying Detected: Volume is {current_candle.volume:.2f} "
                          f"({volume_ratio:.1f}x MA: {indicators.volume_ma_20:.2f}) after an uptrend.",
                )

        return None

    def calculate_sl(self, signal, candles, atr):
        """Structural SL: Behind the climax candle's wick — the invalidation point."""
        if signal.direction == "LONG":
            return round(candles[-1].low - (0.5 * atr), 8)
        else:
            return round(candles[-1].high + (0.5 * atr), 8)

    def calculate_tp(self, signal, candles, atr):
        """Risk-based TP: 1.5R and 3.0R from structural stop."""
        entry = signal.entry or candles[-1].close
        sl = self.calculate_sl(signal, candles, atr)
        risk = abs(entry - sl)
        risk = max(risk, atr * 0.2)
        if signal.direction == "LONG":
            return (round(entry + (1.5 * risk), 8), round(entry + (3.0 * risk), 8))
        else:
            return (round(entry - (1.5 * risk), 8), round(entry - (3.0 * risk), 8))

    def should_confirm_with_llm(self, signal: SetupSignal) -> bool:
        return True
