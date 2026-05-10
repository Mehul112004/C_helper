# Platform Backlog

Deferred features and enhancements to revisit in future iterations.

---

## S/R Zone Detection

- [ ] **High-Volume Node Detection** — Identify S/R zones based on volume profile / market profile analysis (areas where price has spent significant time). Requires building a volume-at-price histogram and detecting high-volume nodes. Deferred from Phase 2 due to computational complexity; swing points, round numbers, and previous H/L provide sufficient zone coverage for initial release.
  - *Original reference:* README § 9 — S/R Zone Detection Engine → "High-volume node detection (where price has spent significant time)"
  - *Deferred during:* Phase 2 planning


Here is the exact playbook of what else you can map into this architecture, categorized by state, and how they combine into institutional-grade confluences.

1. Spatial States (Zones & Levels)

Contract: active, upper, lower, created_at

Beyond FVGs and Order Blocks, here is what you should map into app/core/market_structure.py and app/core/sr_engine.py:

Liquidity Pools (Equal Highs/Lows): Areas where retail stop-losses accumulate. You extract these by finding fractal swings that cluster at the same price level within a tight ATR threshold.

Breaker Blocks: An Order Block that failed (was mitigated completely) and price is now retesting it from the other side. (This is brilliant in this architecture: when ob_active flips False, a new breaker_active zone is born).

High Timeframe (HTF) Anchors: Daily Open, Weekly Open, Previous Day High/Low. These are the absolute strongest spatial zones in crypto.

Volume Profile POC (Point of Control): The price level with the highest traded volume over a rolling window. (Extremely hard to vectorize efficiently in pure pandas, but a massive edge if you implement it via numpy).

2. Temporal States (Spikes & Events)

Contract: event_occurred (bool), event_recent (rolling memory)

Events are your triggers. You never trade a zone blindly; you wait for an event inside the zone.

Liquidity Sweeps (Turtle Soup): A specific temporal event where price wicks through a Spatial Zone (like a Liquidity Pool or Previous Day Low) but the candle body closes back inside.

Momentum Divergence: Price makes a Lower Low, but RSI makes a Higher Low. This happens on a specific candle. It is a highly reliable reversal event.

Volume Anomalies (Climax / Stopping Volume): A candle whose volume is > 3x the 20-period Volume MA, but its spread (high-low) is small. This signals institutional absorption.

Volatility Squeeze Breakout: The exact candle where Bollinger Bands expand outside of Keltner Channels after a period of compression.

3. Continuous States (Regimes & Filters)

Contract: float64 series

These are your regime filters. They answer: "Are we allowed to look for longs right now?"

Trend Regimes: EMA 20 / EMA 50 / EMA 200 cascades.

Volatility (ATR): The absolute value of the ATR. Used dynamically in your scoring matrix to ignore setups when the market is completely dead.

Momentum Baselines: RSI values (is it currently < 30?), MACD Histogram slope.

The Confluence Playbook: How to Combine Them

With this architecture, your generate_signals() function simply measures overlaps. Here are three production-grade setups you can now build trivially:

Setup A: The Liquidity Sweep Reversal (Mean Reversion)

This setup hunts for trapped retail traders.

Spatial: Price is currently interacting with htf_prev_day_low OR a liquidity_pool_lower.

Temporal: event_liquidity_sweep_bullish_recent == True. (Price wicked the zone but closed above).

Continuous: rsi < 35 (Oversold).

Temporal (Trigger): event_choch_bullish_recent == True.

Scoring: Base requirement is the Sweep + HTF Zone. Add +0.20 confidence if Divergence is present. Add +0.20 if ChoCh confirms.

Setup B: The High-Probability Trend Continuation

This is your bread and butter. Trading pullbacks in a macro trend.

Continuous: close > ema_200 AND ema_20 > ema_50 (Macro Bullish).

Spatial: ob_active == True AND fvg_active == True AND ob_upper overlaps with fvg_lower. (This is an extremely strong setup: an Order Block backed by an FVG).

Temporal: event_volume_climax_recent == True (Institution stepped in on the pullback).

Scoring: Base requirement is the Overlapping Zones + Trend. Add +0.30 if Volume Climax confirms the tap.

Setup C: The Failed Structure (Breaker) Trade

Spatial: breaker_block_active == True.

Temporal: event_bos_bearish_recent == True (Trend just broke down).

Continuous: MACD Histogram is sloping downward.

Scoring: Base requirement is price tapping the Breaker Block with a recent BOS.

A Quant's Warning on "Confluence"

Do not fall into the Multicollinearity Trap.

Adding RSI, Stochastic, and MACD into your scoring matrix does not give you "3x the confluence." They are mathematically derived from the exact same thing (closing prices) and will all fire at the exact same time. That is false confidence.

True confluence comes from combining Orthogonal (independent) variables.
A valid scoring matrix takes one from each column:

Price Structure: FVG / OB / Sweep.

Momentum: RSI Divergence / MACD cross.

Effort: Volume Climax / Volume Profile.

If your scoring matrix requires one Spatial Zone, one Momentum Continuous state, and one Volume Temporal event to reach a 0.80 confidence score, you will have a highly robust, professional-grade signal engine.

Are you ready to move to Phase 1, Week 2: Extracting the Temporal Events (ChoCh, BOS, Sweeps) so we can complete the triggers for these zones?