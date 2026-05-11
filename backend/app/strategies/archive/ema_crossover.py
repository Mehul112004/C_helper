from app.core.base_strategy import BaseStrategy, Candle, Indicators, SetupSignal

class EMACrossoverStrategy(BaseStrategy):
    name = "EMA Crossover"
    description = "EMA 9 crosses EMA 21 with EMA 50 trend filter"
    timeframes = ["5m", "15m", "1h", "4h"]
    version = "1.4"

    def scan(self, symbol, timeframe, candles, indicators, sr_zones, htf_candles=None):
        if len(candles) < 4:
            return None

        atr = indicators.atr_14 if indicators.atr_14 is not None else (candles[-1].range_size * 1.5)

        if indicators.prev_ema_9 is None or indicators.prev_ema_21 is None:
            return None
        if indicators.ema_9 is None or indicators.ema_21 is None:
            return None

        volume_check_candle = candles[-2] if len(candles) >= 2 else candles[-1]
        if indicators.volume_ma_20 is not None and volume_check_candle.volume < (indicators.volume_ma_20 * 0.8):
            return None

        prev_above = indicators.prev_ema_9 >= indicators.prev_ema_21
        curr_above = indicators.ema_9 > indicators.ema_21
        prev_below = indicators.prev_ema_9 <= indicators.prev_ema_21
        curr_below = indicators.ema_9 < indicators.ema_21

        bullish_cross = prev_below and curr_above
        bearish_cross = prev_above and curr_below

        if not bullish_cross and not bearish_cross:
            return None

        close = candles[-1].close
        direction = "LONG" if bullish_cross else "SHORT"

        if indicators.ema_50 is not None:
            if bullish_cross and close < indicators.ema_50:
                return None
            if bearish_cross and close > indicators.ema_50:
                return None

        if indicators.ema_21_history and len(indicators.ema_21_history) >= 5:
            ema_21_old = indicators.ema_21_history[-5]
            if abs(indicators.ema_21 - ema_21_old) < (0.02 * atr):
                return None

        if htf_candles and len(htf_candles) >= 2:
            htf_closed = htf_candles[-2]
            if direction == "LONG" and not htf_closed.is_bullish:
                return None
            if direction == "SHORT" and not htf_closed.is_bearish:
                return None

        # --- MINIMUM RR GATE ---
        # FIX 5 (SL): Tightened buffer from 0.3 → 0.15 ATR to reduce risk denominator
        sl_proxy = (
            min(c.low for c in candles[-4:]) - (0.15 * atr)
            if direction == "LONG"
            else max(c.high for c in candles[-4:]) + (0.15 * atr)
        )
        risk = max(abs(close - sl_proxy), atr * 0.2)

        # FIX 6 (TP): Raised TP1 multiplier from 1.5 → 2.0 for higher reward ceiling
        base_tp = close + (2.0 * risk) if direction == "LONG" else close - (2.0 * risk)
        compressed_tp = base_tp

        if sr_zones:
            if direction == "LONG":
                for zone in sr_zones:
                    # FIX 7: Raised SR strength threshold from 0.5 → 0.7
                    # Avoids compressing TP into weak zones price frequently breaks through
                    if zone.get('zone_type') in ('resistance', 'both') and zone.get('strength_score', 0) > 0.7:
                        z_lower = zone.get('zone_lower', zone.get('price_level', 0))
                        if close < z_lower < compressed_tp:
                            compressed_tp = min(compressed_tp, z_lower - (0.05 * atr))
            else:
                for zone in sr_zones:
                    if zone.get('zone_type') in ('support', 'both') and zone.get('strength_score', 0) > 0.7:
                        z_upper = zone.get('zone_upper', zone.get('price_level', 0))
                        if close > z_upper > compressed_tp:
                            # FIX 1 (SHORT compression): Was `z_upper + 0.05 * atr` which pushed
                            # compressed_tp ABOVE z_upper, and could exceed `close` entirely.
                            # Correct intent is to pull TP up to just BELOW the zone.
                            compressed_tp = max(compressed_tp, z_upper - (0.05 * atr))

        actual_reward = abs(compressed_tp - close)

        # FIX 2: Guard against negative reward from a badly placed SHORT zone
        if actual_reward <= 0:
            return None

        actual_rr = actual_reward / risk

        # FIX 3: Raised gate from 1.0 → 1.5 to match the new TP1 multiplier.
        # The old gate accepted trades already compressed below TP1 target.
        if actual_rr < 1.5:
            return None
        # -----------------------

        confidence = 0.60

        if volume_check_candle.volume > indicators.volume_ma_20 * 1.5:
            confidence += 0.05

        if indicators.ema_200 is not None:
            if direction == "LONG" and close > indicators.ema_200:
                confidence += 0.10
            elif direction == "SHORT" and close < indicators.ema_200:
                confidence += 0.10

        if indicators.rsi_14 is not None:
            if direction == "LONG" and 40 <= indicators.rsi_14 <= 75:
                confidence += 0.05
            elif direction == "SHORT" and 25 <= indicators.rsi_14 <= 60:
                confidence += 0.05

        cross_type = "bullish" if bullish_cross else "bearish"

        return SetupSignal(
            strategy_name=self.name,
            symbol=symbol,
            timeframe=timeframe,
            direction=direction,
            confidence=min(confidence, 1.0),
            entry=close,
            notes=f"EMA 9/21 {cross_type} crossover on {timeframe}",
        )

    def calculate_sl(self, signal, candles, atr):
        if len(candles) < 4:
            return None

        # FIX 5 (SL): Buffer reduced from 0.3 → 0.15 ATR, consistent with scan() proxy
        if signal.direction == "LONG":
            recent_low = min(c.low for c in candles[-4:])
            return round(recent_low - (0.15 * atr), 8)
        else:
            recent_high = max(c.high for c in candles[-4:])
            return round(recent_high + (0.15 * atr), 8)

    def calculate_tp(self, signal, candles, atr, sr_zones=None):
        if len(candles) < 4:
            return (None, None)

        entry = signal.entry if signal.entry is not None else candles[-1].close
        sl = self.calculate_sl(signal, candles, atr)
        risk = abs(entry - sl)
        risk = max(risk, atr * 0.2)

        if signal.direction == "LONG":
            # FIX 6 (TP): Raised TP1 from 1.5 → 2.0 R, TP2 from 3.0 → 4.0 R
            tp1 = entry + (2.0 * risk)
            tp2 = entry + (4.0 * risk)

            if sr_zones:
                for zone in sr_zones:
                    # FIX 7: Consistent SR threshold 0.7 (was 0.5)
                    if zone.get('zone_type') in ('resistance', 'both') and zone.get('strength_score', 0) > 0.7:
                        z_lower = zone.get('zone_lower', zone.get('price_level', 0))
                        if entry < z_lower < tp1:
                            tp1 = min(tp1, z_lower - (0.05 * atr))
                        # FIX 4: TP2 now also compressed by SR zones (was unchecked)
                        if entry < z_lower < tp2:
                            tp2 = min(tp2, z_lower - (0.05 * atr))

            return (round(tp1, 8), round(tp2, 8))

        else:
            tp1 = entry - (2.0 * risk)
            tp2 = entry - (4.0 * risk)

            if sr_zones:
                for zone in sr_zones:
                    if zone.get('zone_type') in ('support', 'both') and zone.get('strength_score', 0) > 0.7:
                        z_upper = zone.get('zone_upper', zone.get('price_level', 0))
                        if entry > z_upper > tp1:
                            # FIX 1 (SHORT compression in calculate_tp): Same correction as scan().
                            # Pull TP up to just below the support zone, not above it.
                            tp1 = max(tp1, z_upper - (0.05 * atr))
                        # FIX 4: TP2 now also compressed by SR zones
                        if entry > z_upper > tp2:
                            tp2 = max(tp2, z_upper - (0.05 * atr))

            return (round(tp1, 8), round(tp2, 8))