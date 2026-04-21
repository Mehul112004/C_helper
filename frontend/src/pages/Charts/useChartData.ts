import { useState, useEffect, useCallback, useRef } from 'react';
import type { CandleData, SRZone, IndicatorSeriesPoint } from '../../api/client';
import { fetchCandles, fetchSRZones, fetchIndicators } from '../../api/client';
import type { LiveCandleEvent } from '../../types/signals';

export interface ChartDataState {
  candles: CandleData[];
  srZones: SRZone[];
  emaLines: {
    ema_9: IndicatorSeriesPoint[];
    ema_21: IndicatorSeriesPoint[];
    ema_50: IndicatorSeriesPoint[];
    ema_200: IndicatorSeriesPoint[];
  };
  loading: boolean;
  error: string | null;
}

const EMPTY_EMA = { ema_9: [], ema_21: [], ema_50: [], ema_200: [] };

/**
 * Custom hook for fetching all chart data: candles, S/R zones, and EMA series.
 * Refetches automatically when inputs change, with debounce.
 */
export function useChartData(
  symbol: string,
  timeframe: string,
  limit: number,
  showSRZones: boolean,
  minStrength: number,
  showEMA: boolean,
) {
  const [state, setState] = useState<ChartDataState>({
    candles: [],
    srZones: [],
    emaLines: EMPTY_EMA,
    loading: false,
    error: null,
  });

  // Live tick stored separately — never triggers setData(), only .update()
  const [liveTick, setLiveTick] = useState<LiveCandleEvent | null>(null);
  const [closeTime, setCloseTime] = useState<number | null>(null);

  const abortRef = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    if (!symbol || !timeframe) return;

    // Cancel any previous in-flight request
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setState(prev => ({ ...prev, loading: true, error: null }));

    try {
      // Build parallel fetch promises
      const promises: [
        ReturnType<typeof fetchCandles>,
        ReturnType<typeof fetchSRZones> | Promise<null>,
        ReturnType<typeof fetchIndicators> | Promise<null>,
      ] = [
        fetchCandles(symbol, timeframe, limit),
        showSRZones ? fetchSRZones(symbol, timeframe, minStrength) : Promise.resolve(null),
        showEMA ? fetchIndicators(symbol, timeframe, true) : Promise.resolve(null),
      ];

      const [candleResult, srResult, indicatorResult] = await Promise.all(promises);

      if (controller.signal.aborted) return;

      // Extract EMA series from indicator response
      let emaLines = EMPTY_EMA;
      if (indicatorResult && indicatorResult.series) {
        emaLines = {
          ema_9: indicatorResult.series['ema_9'] || [],
          ema_21: indicatorResult.series['ema_21'] || [],
          ema_50: indicatorResult.series['ema_50'] || [],
          ema_200: indicatorResult.series['ema_200'] || [],
        };
      }

      setState({
        candles: candleResult.candles,
        srZones: srResult?.zones || [],
        emaLines,
        loading: false,
        error: null,
      });

      // Reset live tick on fresh load
      setLiveTick(null);
      setCloseTime(null);
    } catch (err) {
      if (controller.signal.aborted) return;
      setState(prev => ({
        ...prev,
        loading: false,
        error: err instanceof Error ? err.message : 'Failed to load chart data',
      }));
    }
  }, [symbol, timeframe, limit, showSRZones, minStrength, showEMA]);

  // Debounced refetch when inputs change
  useEffect(() => {
    const timer = setTimeout(load, 150);
    return () => clearTimeout(timer);
  }, [load]);

  /**
   * Apply a live candle tick from SSE.
   * Compares open_time against the last candle to decide append vs update.
   * Also updates closeTime for the countdown timer.
   */
  const applyLiveCandle = useCallback(
    (evt: LiveCandleEvent) => {
      setCloseTime(evt.close_time);

      setState(prev => {
        if (prev.candles.length === 0) return prev;

        const lastCandle = prev.candles[prev.candles.length - 1];
        const lastOpenMs = new Date(lastCandle.open_time).getTime();
        const incomingOpenMs = evt.open_time;

        if (incomingOpenMs === lastOpenMs) {
          // Same candle period — update in place
          const updated = [...prev.candles];
          updated[updated.length - 1] = {
            ...lastCandle,
            open: evt.open,
            high: evt.high,
            low: evt.low,
            close: evt.close,
            volume: evt.volume,
          };
          return { ...prev, candles: updated };
        } else if (incomingOpenMs > lastOpenMs) {
          // New candle period — append
          const isoTime = new Date(incomingOpenMs).toISOString();
          const newCandle: CandleData = {
            open_time: isoTime,
            open: evt.open,
            high: evt.high,
            low: evt.low,
            close: evt.close,
            volume: evt.volume,
          };
          return { ...prev, candles: [...prev.candles, newCandle] };
        }

        // Stale tick (older than current) — ignore
        return prev;
      });

      // Store tick for efficient .update() in chart component
      setLiveTick(evt);
    },
    [],
  );

  /**
   * Fallback: update last candle's close price from a price_update SSE event.
   * Used when no live_candle stream matches the viewed timeframe.
   */
  const updateLastCandle = useCallback(
    (price: number) => {
      setState(prev => {
        if (prev.candles.length === 0) return prev;
        const updated = [...prev.candles];
        const last = { ...updated[updated.length - 1] };

        last.close = price;
        if (price > last.high) last.high = price;
        if (price < last.low) last.low = price;

        updated[updated.length - 1] = last;

        // Push synthetic liveTick for .update() path in chart
        setLiveTick({
          session_id: '',
          symbol: '',
          timeframe: '',
          open_time: new Date(last.open_time).getTime(),
          close_time: 0,
          open: last.open,
          high: last.high,
          low: last.low,
          close: last.close,
          volume: last.volume,
          is_closed: false,
        });

        return { ...prev, candles: updated };
      });
    },
    [],
  );

  return { ...state, reload: load, applyLiveCandle, updateLastCandle, liveTick, closeTime };
}

