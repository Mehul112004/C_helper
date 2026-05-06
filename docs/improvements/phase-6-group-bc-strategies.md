# Phase 6: Strategy Migration — Group B (ON_TOUCH) & Group C (HYBRID)

**Goal**: Migrate the 8 structural and price-action strategies to ON_TOUCH and HYBRID modes. These are the strategies that benefit most from the MTF split — their `update_context()` does the heavy zone computation once on HTF close, and `evaluate_trigger()` becomes a lightweight proximity/confirmation check.

**Risk**: Medium — each strategy migrated independently.  
**Depends on**: Phase 1, 2, 3

## Files Changed

### Group B — ON_TOUCH (Zone Snipers)

| File | context_tf | execution_tf |
|------|-----------|-------------|
| `order_block_retest.py` | 4h | 5m |
| `fvg_mitigation.py` | 1h | 5m |
| `fibonacci_retracement.py` | 4h | 15m |

### Group C — HYBRID (Price Action Confirmation)

| File | context_tf | execution_tf |
|------|-----------|-------------|
| `smc_liquidity_sweep.py` | 1h | 5m |
| `smc_structure_shift.py` | 4h | 15m |
| `sr_rejection.py` | 4h | 15m |
| `sr_breakout.py` | 4h | 15m |
| `trend_pullback_confluence.py` | 4h | 15m |

---

## Group B Migration Pattern

These fire instantly on price touch. The key difference from Group A: `evaluate_trigger()` receives raw `current_price` (no LTF candles needed for ON_TOUCH).

### Order Block Retest

**`update_context()`** — runs on 4H close:
- Scan 4H candles for valid OBs (reuse existing `_evaluate_ob_candidate` logic)
- For each valid OB, create `ActiveZone(zone_type="order_block", direction=dir, top=ob_high, bottom=ob_low)`
- Store in `self._context_state.active_zones`
- Determine regime from HTF SMA-20 baseline (existing logic)

**`evaluate_trigger()`** — runs on every tick near a zone:
- Iterate cached `active_zones`
- If `current_price` is inside an OB zone → check defense line, wick rejection
- Since we're on tick data (no candle), use the last available 5m candle for wick validation
- Fire `SetupSignal` with existing confidence scoring

### FVG Mitigation

**`update_context()`** — runs on 1H close:
- Scan for unfilled FVGs on 1H (existing `c3.low > c1.high` logic)
- Check OB confluence (existing `_has_adjacent_bullish_ob`)
- Cache each valid FVG as `ActiveZone(zone_type="fvg", top=fvg_top, bottom=fvg_bottom, metadata={"ob": ob_dict})`

**`evaluate_trigger()`** — runs on tick near FVG:
- If price enters FVG zone → check rejection pattern on latest 5m candle
- Fire with OB confluence confidence boost

### Fibonacci Retracement

**`update_context()`** — runs on 4H close:
- Build swing map, find last swing high/low
- Compute fib grid (0.382, 0.5, 0.618, 0.786)
- Cache each level as `ActiveZone(zone_type="fib_level", metadata={"ratio": 0.618, "swing_high": ..., "swing_low": ...})`
- Validate impulse size (≥ 3× ATR) and regime filter

**`evaluate_trigger()`** — runs on tick near fib level:
- Determine which fib zone price is in (golden pocket vs 382 vs 786)
- Check confluence requirements per zone
- Check rejection candle on latest 15m candle
- Compute structural SL/TP from fib levels

---

## Group C Migration Pattern

These require zone interaction + LTF candle close confirmation. `evaluate_trigger()` runs on LTF candle close (not tick), gated by `zone_manager.is_price_near_zone()`.

### SMC Liquidity Sweep

**`update_context()`** — runs on 1H close:
- Map fractal highs/lows on 1H as liquidity pools
- For each unbroken fractal extreme, create `ActiveZone(zone_type="liquidity_pool")`

**`evaluate_trigger()`** — runs on 5m close near a pool:
- Check if 5m candle wick pierced the pool level AND closed back inside
- Validate wick rejection ratio (≥1.2× body)
- Volume climax gate (≥1.2× volume MA)
- 50% wick sniper entry calculation

### SMC Structure Shift

**`update_context()`** — runs on 4H close:
- Build swing map on 4H, determine trend
- Cache most recent swing high and swing low as `ActiveZone(zone_type="swing_point")`

**`evaluate_trigger()`** — runs on 15m close:
- Check if 15m body closed through a cached swing level
- Reject wick-only piercings
- Classify as BOS (with-trend) or ChoCh (counter-trend)

### S/R Rejection

**`update_context()`** — runs on 4H close:
- Cache S/R zones from DB as `ActiveZone(zone_type="sr")`
- Filter by minimum strength threshold

**`evaluate_trigger()`** — runs on 15m close near S/R zone:
- Check for pin bar / hammer / shooting star rejection pattern
- Wick must penetrate zone but body closes outside
- Existing confidence scoring (zone strength, volume, RSI)

### S/R Breakout

**`update_context()`** — runs on 4H close:
- Same as SR Rejection: cache S/R zones

**`evaluate_trigger()`** — runs on 15m close:
- Check for decisive body close beyond the zone level
- Previous candle must have been on the other side (actual breakout, not drift)
- Volume confirmation

### Trend Pullback Confluence

**`update_context()`** — runs on 4H close:
- Determine 4H trend direction from EMA structure
- Cache minor pullback zones (recent swing lows in uptrend, swing highs in downtrend)

**`evaluate_trigger()`** — runs on 15m close:
- Check for momentum shift back into HTF trend direction
- Require multiple confluence (EMA, volume, structure)

---

## Migration Order

Migrate one strategy at a time within each group. Suggested order (simplest first):

1. `sr_rejection.py` (HYBRID) — simplest zone caching
2. `sr_breakout.py` (HYBRID) — shares zone cache pattern with sr_rejection
3. `smc_structure_shift.py` (HYBRID) — straightforward swing point caching
4. `smc_liquidity_sweep.py` (HYBRID) — fractal pool caching
5. `trend_pullback_confluence.py` (HYBRID) — trend zone caching
6. `fvg_mitigation.py` (ON_TOUCH) — first ON_TOUCH migration
7. `order_block_retest.py` (ON_TOUCH) — most complex zone logic
8. `fibonacci_retracement.py` (ON_TOUCH) — multi-level zone caching

## Verification

For each migrated strategy:
- [ ] `strategy.execution_mode` is correct (ON_TOUCH or HYBRID)
- [ ] `update_context()` populates `active_zones` with correct zone coordinates
- [ ] `evaluate_trigger()` returns signals only when price interacts with cached zones
- [ ] Zone proximity check works (no signals when price is far from all zones)
- [ ] Legacy `scan()` still works identically
- [ ] Signals include `htf_context_summary` and `ltf_trigger_summary`
- [ ] ON_TOUCH strategies fire from `_on_price_update()` path
- [ ] HYBRID strategies fire from `_on_candle_close()` path only
