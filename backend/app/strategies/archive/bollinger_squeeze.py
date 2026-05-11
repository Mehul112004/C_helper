"""
Bollinger Band Squeeze Strategy (v2.2)
Reactive strategy on 15m, 1h, 4h.

v2.2 Changes (1H win-rate focused):
  - Timeframe-aware config: stricter thresholds for 1H
  - Volume gate raised to 1.5× on 1H (was 1.2×, too much noise)
  - EMA 50 promoted to HARD GATE on 1H (was soft confidence boost)
  - MACD curl requires 2 consecutive bars agreement on 1H (was 1-bar)
  - MIN_SQUEEZE_BARS raised to 5 on 1H (was 3, coil needs more time)
  - HTF bias required (not optional) on 1H when data is available
  - Retest path now validates squeeze history exists before firing
  - Exhaustion trap wick filter tightened to 0.3 on 1H (was 0.4)
  - Added RSI overbought/oversold guard (soft gate, -0.10 confidence)
"""

from app.core.base_strategy import BaseStrategy, Candle, Indicators, SetupSignal


class BollingerSqueezeStrategy(BaseStrategy):
    name = "Bollinger Band Squeeze"
    description = "TTM Squeeze breakout with Keltner Channel validation and split entry"
    timeframes = ["15m", "1h", "4h"]
    version = "2.2"

    # ── Base Configuration (applies to all timeframes) ─────────────
    MIN_BB_HISTORY = 10
    MIN_SQUEEZE_BARS = 3
    FAKEOUT_LOOKBACK = 5
    RETEST_LOOKBACK_MIN = 3
    RETEST_LOOKBACK_MAX = 8

    # ── Per-Timeframe Overrides ────────────────────────────────────
    # FIX #1: 1H has more noise per candle than 15m.
    # Raise every threshold to demand stronger confirmation before firing.
    TF_CONFIG = {
        "15m": {
            "volume_gate": 1.2,       # 1.2× volume MA — original
            "min_squeeze_bars": 3,    # 3 bars minimum coil
            "wick_filter": 0.4,       # Exhaustion wick ratio ceiling
            "macd_curl_bars": 1,      # Single-bar MACD curl sufficient
            "ema_hard_gate": False,   # EMA 50 is only a soft boost
            "htf_required": False,    # HTF bias helpful but not required
        },
        "1h": {
            "volume_gate": 1.5,       # FIX: 1.5× — filters out ordinary spikes
            "min_squeeze_bars": 5,    # FIX: 5 bars — coil must be well-formed
            "wick_filter": 0.3,       # FIX: Tighter wick filter (0.3 vs 0.4)
            "macd_curl_bars": 2,      # FIX: Require 2 consecutive bars curling
            "ema_hard_gate": True,    # FIX: EMA 50 is now a hard gate
            "htf_required": True,     # FIX: HTF bias required when available
        },
        "4h": {
            "volume_gate": 1.3,       # 4H candles: slight bump over 15m default
            "min_squeeze_bars": 4,    # 4H needs a bit more coil time
            "wick_filter": 0.4,
            "macd_curl_bars": 1,
            "ema_hard_gate": False,
            "htf_required": False,
        },
    }

    def _get_tf_config(self, timeframe: str) -> dict:
        """Return the config block for the given timeframe, defaulting to 15m."""
        return self.TF_CONFIG.get(timeframe, self.TF_CONFIG["15m"])

    # ── Step 1: Volatility Compression (TTM Squeeze) ───────────────

    def _is_squeeze(self, indicators: Indicators) -> bool:
        """
        Detect if a TTM Squeeze was active on the previous bar.
        Squeeze = Bollinger Bands fitting completely inside Keltner Channels.

        Falls back to bb_width < mean heuristic if KC data is unavailable.
        """
        if (indicators.prev_bb_upper is not None and
                indicators.prev_bb_lower is not None and
                indicators.prev_kc_upper is not None and
                indicators.prev_kc_lower is not None):
            return (indicators.prev_bb_upper < indicators.prev_kc_upper and
                    indicators.prev_bb_lower > indicators.prev_kc_lower)

        history = indicators.bb_width_history
        if len(history) < self.MIN_BB_HISTORY:
            return False
        if indicators.prev_bb_width is None:
            return False
        avg_width = sum(history) / len(history)
        return indicators.prev_bb_width < avg_width * 0.8

    def _squeeze_duration(self, indicators: Indicators) -> int:
        """
        Count consecutive squeeze bars from bb_width_history.
        Returns 0 if insufficient data.
        """
        history = indicators.bb_width_history
        if len(history) < self.MIN_BB_HISTORY:
            return 0

        avg_width = sum(history) / len(history)
        count = 0
        for val in reversed(history):
            if val < avg_width:
                count += 1
            else:
                break
        return count

    # ── Step 2: Directional Bias (HTF + Momentum) ──────────────────

    def _directional_bias(self, indicators: Indicators, htf_candles, close: float):
        """
        Determine directional bias using MACD momentum + HTF trend.

        Returns "BULL", "BEAR", or None (no clear bias).
        """
        macd_bias = None
        htf_bias = None

        hist = indicators.macd_hist_history
        if len(hist) >= 3:
            if hist[-1] > hist[-2]:
                macd_bias = "BULL"
            elif hist[-1] < hist[-2]:
                macd_bias = "BEAR"

        if htf_candles and len(htf_candles) >= 10:
            htf_high = max(c.high for c in htf_candles[-10:])
            htf_low = min(c.low for c in htf_candles[-10:])
            htf_mid = (htf_high + htf_low) / 2
            htf_close = htf_candles[-1].close
            htf_bias = "BULL" if htf_close > htf_mid else "BEAR"

        if macd_bias and htf_bias:
            return macd_bias if macd_bias == htf_bias else None

        return macd_bias or htf_bias

    # ── FIX #2: MACD curl strength check ──────────────────────────
    def _macd_curl_confirmed(self, indicators: Indicators, direction: str, required_bars: int) -> bool:
        """
        FIX: On 1H, a single histogram tick is too noisy. Require `required_bars`
        consecutive bars of the histogram moving in the same direction.

        For 15m/4h, required_bars=1 preserves original behaviour.
        For 1H, required_bars=2 filters out one-bar false curls.
        """
        hist = indicators.macd_hist_history
        if len(hist) < required_bars + 1:
            return False

        # Check the last `required_bars` deltas all point the same way
        deltas = [hist[-(i + 1)] - hist[-(i + 2)] for i in range(required_bars)]
        if direction == "LONG":
            return all(d > 0 for d in deltas)
        else:
            return all(d < 0 for d in deltas)

    # ── Step 3: Fake-Out / Liquidity Sweep Detection ───────────────

    def _detect_fakeout_precursor(self, candles, indicators: Indicators):
        """
        Look back N bars for a recent opposite-band breach that snapped back.
        Returns "BULL", "BEAR", or None.
        """
        if len(candles) < self.FAKEOUT_LOOKBACK + 1:
            return None
        if indicators.bb_upper is None or indicators.bb_lower is None:
            return None

        lookback = candles[-(self.FAKEOUT_LOOKBACK + 1):-1]
        bearish_fakeout = False
        bullish_fakeout = False

        for candle in lookback:
            if candle.low < indicators.bb_lower and candle.close > indicators.bb_lower:
                bearish_fakeout = True
            if candle.high > indicators.bb_upper and candle.close < indicators.bb_upper:
                bullish_fakeout = True

        if bearish_fakeout and not bullish_fakeout:
            return "BULL"
        if bullish_fakeout and not bearish_fakeout:
            return "BEAR"
        return None

    # ── FIX #3: RSI guard ─────────────────────────────────────────
    def _rsi_penalty(self, indicators: Indicators, direction: str) -> float:
        """
        FIX: Penalise entries into overextended conditions.
        On 1H, chasing breakouts when RSI is already at extremes dramatically
        lowers win rate — price is statistically more likely to revert than extend.

        Returns a confidence penalty (negative float, 0.0 if RSI is healthy).
        """
        rsi = getattr(indicators, "rsi_14", None)
        if rsi is None:
            return 0.0
        if direction == "LONG" and rsi > 72:
            return -0.10   # Overbought long — likely exhausted
        if direction == "SHORT" and rsi < 28:
            return -0.10   # Oversold short — likely exhausted
        return 0.0

    # ── Step 5: Retest Detection ───────────────────────────────────

    def _detect_retest(self, candles, indicators: Indicators, timeframe: str):
        """
        Detect a pullback/retest after a recent breakout.

        FIX: Now requires that a squeeze was active in recent history before
        the retest fires. This prevents the retest path from triggering on
        ordinary mean-reversion moves that have nothing to do with a squeeze.
        """
        if len(candles) < self.RETEST_LOOKBACK_MAX + 1:
            return None
        if indicators.bb_middle is None or indicators.atr_14 is None:
            return None

        # FIX: Validate squeeze history before accepting a retest
        # Without this, the retest path was firing on non-squeeze setups entirely.
        if not self._is_squeeze(indicators):
            squeeze_found_in_history = False
            history = indicators.bb_width_history
            if len(history) >= self.MIN_BB_HISTORY:
                avg_width = sum(history) / len(history)
                # Check if any of the last RETEST_LOOKBACK_MAX bars were in squeeze
                for val in list(reversed(history))[:self.RETEST_LOOKBACK_MAX]:
                    if val < avg_width * 0.8:
                        squeeze_found_in_history = True
                        break
            if not squeeze_found_in_history:
                return None

        current = candles[-1]
        close = current.close
        atr = indicators.atr_14

        distance_to_middle = abs(close - indicators.bb_middle)
        if distance_to_middle > 0.4 * atr:
            return None

        lookback = candles[-(self.RETEST_LOOKBACK_MAX + 1):-self.RETEST_LOOKBACK_MIN]

        for candle in lookback:
            if (indicators.bb_upper is not None and
                    candle.close > indicators.bb_upper and candle.is_bullish):
                if close >= indicators.bb_middle:
                    wick_ratio = current.lower_wick / current.range_size if current.range_size > 0 else 0
                    if current.is_bullish or wick_ratio > 0.4:
                        return "LONG"

            if (indicators.bb_lower is not None and
                    candle.close < indicators.bb_lower and candle.is_bearish):
                if close <= indicators.bb_middle:
                    wick_ratio = current.upper_wick / current.range_size if current.range_size > 0 else 0
                    if current.is_bearish or wick_ratio > 0.4:
                        return "SHORT"

        return None

    # ── Main Scan ──────────────────────────────────────────────────

    def scan(self, symbol, timeframe, candles, indicators, sr_zones, htf_candles=None):
        if indicators.bb_upper is None or indicators.bb_lower is None:
            return None
        if indicators.bb_width is None or indicators.prev_bb_width is None:
            return None
        if indicators.bb_middle is None:
            return None
        if len(candles) < 10:
            return None

        close = candles[-1].close
        cfg = self._get_tf_config(timeframe)

        # ── Path A: Retest Entry (Step 5) ──────────────────────────
        # FIX: Now passes timeframe so squeeze history validation can run.
        retest_dir = self._detect_retest(candles, indicators, timeframe)
        if retest_dir is not None:
            confidence = 0.55

            # FIX: EMA hard gate on 1H applies to retest entries too.
            if cfg["ema_hard_gate"] and indicators.ema_50 is not None:
                if retest_dir == "LONG" and close < indicators.ema_50:
                    return None  # Retesting below EMA on 1H — reject
                if retest_dir == "SHORT" and close > indicators.ema_50:
                    return None

            if indicators.volume_ma_20 and candles[-1].volume > indicators.volume_ma_20:
                confidence += 0.05

            bias = self._directional_bias(indicators, htf_candles, close)

            # FIX: On 1H, if HTF data is available, bias conflict kills the retest.
            if cfg["htf_required"] and htf_candles and len(htf_candles) >= 10:
                if bias is None or bias != ("BULL" if retest_dir == "LONG" else "BEAR"):
                    return None

            if bias == ("BULL" if retest_dir == "LONG" else "BEAR"):
                confidence += 0.10

            if indicators.ema_50 is not None:
                if retest_dir == "LONG" and close > indicators.ema_50:
                    confidence += 0.05
                elif retest_dir == "SHORT" and close < indicators.ema_50:
                    confidence += 0.05

            # FIX: RSI overextension penalty
            confidence += self._rsi_penalty(indicators, retest_dir)

            confidence += 0.05  # Retest inherent entry quality bonus

            return SetupSignal(
                strategy_name=self.name,
                symbol=symbol,
                timeframe=timeframe,
                direction=retest_dir,
                confidence=min(confidence, 1.0),
                entry=close,
                notes=(
                    f"Bollinger squeeze RETEST entry on {timeframe}. "
                    f"Price pulled back to BB middle ({indicators.bb_middle:.2f}) "
                    f"and held. Entry type: retest (conservative)."
                ),
            )

        # ── Path B: Breakout Entry (Steps 1-4) ─────────────────────

        # Step 1: Was there a squeeze on the previous bar?
        if not self._is_squeeze(indicators):
            return None

        # FIX: Enforce minimum squeeze duration per timeframe
        duration = self._squeeze_duration(indicators)
        if duration < cfg["min_squeeze_bars"]:
            return None

        # Step 4a: Band must be expanding
        if indicators.bb_width <= indicators.prev_bb_width:
            return None

        # Step 4b: Breakout direction + exhaustion trap filter
        current = candles[-1]
        range_size = current.range_size if current.range_size > 0 else 1.0
        wick_limit = cfg["wick_filter"]   # FIX: 0.3 on 1H, 0.4 elsewhere

        breakout_up = (close > indicators.bb_upper and
                       (current.upper_wick / range_size < wick_limit))
        breakout_down = (close < indicators.bb_lower and
                         (current.lower_wick / range_size < wick_limit))

        if not breakout_up and not breakout_down:
            return None

        direction = "LONG" if breakout_up else "SHORT"

        # Step 4c: Volume hard gate — timeframe-aware threshold
        if not indicators.volume_ma_20:
            return None
        if candles[-1].volume < indicators.volume_ma_20 * cfg["volume_gate"]:
            return None  # FIX: 1.5× on 1H vs 1.2× elsewhere

        # FIX: EMA 50 hard gate on 1H
        if cfg["ema_hard_gate"] and indicators.ema_50 is not None:
            if direction == "LONG" and close < indicators.ema_50:
                return None  # Breaking out above upper band but below EMA — reject
            if direction == "SHORT" and close > indicators.ema_50:
                return None

        # Step 2: Directional bias check
        bias = self._directional_bias(indicators, htf_candles, close)

        # FIX: On 1H, when HTF data is available, bias must confirm.
        # Previously, None bias (unavailable data) was treated as neutral — which
        # allowed through setups that lacked any trend confirmation at all.
        if cfg["htf_required"] and htf_candles and len(htf_candles) >= 10:
            expected = "BULL" if direction == "LONG" else "BEAR"
            if bias != expected:
                return None  # No data or conflict → reject on 1H

        elif bias is not None:
            expected = "BULL" if direction == "LONG" else "BEAR"
            if bias != expected:
                return None

        # ── Confidence Scoring ─────────────────────────────────────
        confidence = 0.50

        if candles[-1].volume > indicators.volume_ma_20 * 2.0:
            confidence += 0.10
        if candles[-1].volume > indicators.volume_ma_20 * 3.0:
            confidence += 0.05

        if bias is not None:
            confidence += 0.10

        # FIX: Use multi-bar MACD confirmation on 1H
        if self._macd_curl_confirmed(indicators, direction, cfg["macd_curl_bars"]):
            confidence += 0.05

        fakeout = self._detect_fakeout_precursor(candles, indicators)
        if fakeout is not None:
            expected_fakeout = "BULL" if direction == "LONG" else "BEAR"
            if fakeout == expected_fakeout:
                confidence += 0.10

        # Duration bonus: threshold aligns with per-TF min_squeeze_bars
        if duration >= cfg["min_squeeze_bars"] + 2:
            confidence += 0.05

        if indicators.ema_50 is not None:
            if direction == "LONG" and close > indicators.ema_50:
                confidence += 0.05
            elif direction == "SHORT" and close < indicators.ema_50:
                confidence += 0.05

        # FIX: RSI overextension penalty
        confidence += self._rsi_penalty(indicators, direction)

        bb_direction = "above upper band" if breakout_up else "below lower band"
        components = []
        if bias:
            components.append(f"HTF bias: {bias}")
        if fakeout:
            components.append(f"fakeout precursor: {fakeout}")
        components.append(f"squeeze duration: {duration} bars")
        vol_ratio = candles[-1].volume / indicators.volume_ma_20
        components.append(f"vol ratio: {vol_ratio:.1f}×")
        extra = ", ".join(components)

        return SetupSignal(
            strategy_name=self.name,
            symbol=symbol,
            timeframe=timeframe,
            direction=direction,
            confidence=min(confidence, 1.0),
            entry=close,
            notes=(
                f"Bollinger squeeze BREAKOUT {bb_direction} on {timeframe}. "
                f"BB width: {indicators.prev_bb_width:.6f} → {indicators.bb_width:.6f}. "
                f"Entry type: breakout (aggressive). {extra}"
            ),
        )

    # ── Step 6: Invalidation-Aware SL ──────────────────────────────

    def calculate_sl(self, signal, candles, atr):
        """
        For breakouts, SL is placed just behind the breakout candle's extreme.
        For retests, SL is placed below/above the pullback pivot.
        """
        is_retest = "retest" in signal.notes.lower()

        if signal.direction == "LONG":
            if is_retest:
                recent_low = min(c.low for c in candles[-3:])
                return round(recent_low - (0.2 * atr), 8)
            else:
                recent_low = min(c.low for c in candles[-2:])
                return round(recent_low - (0.2 * atr), 8)
        else:
            if is_retest:
                recent_high = max(c.high for c in candles[-3:])
                return round(recent_high + (0.2 * atr), 8)
            else:
                recent_high = max(c.high for c in candles[-2:])
                return round(recent_high + (0.2 * atr), 8)

    def calculate_tp(self, signal, candles, atr, sr_zones=None):
        """Risk-based TP: 2R and 3.5R."""
        entry = signal.entry or candles[-1].close
        sl = self.calculate_sl(signal, candles, atr)
        risk = abs(entry - sl)
        risk = max(risk, atr * 0.2)
        if signal.direction == "LONG":
            return (round(entry + (2.0 * risk), 8), round(entry + (3.5 * risk), 8))
        else:
            return (round(entry - (2.0 * risk), 8), round(entry - (3.5 * risk), 8))