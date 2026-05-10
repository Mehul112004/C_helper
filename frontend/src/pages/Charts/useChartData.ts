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

const EMPTY_EMA: ChartDataState['emaLines'] = { ema_9: [], ema_21: [], ema_50: [], ema_200: [] };

const TF_MS: Record<string, number> = {
  '1s': 1_000,
  '1m': 60_000,
  '3m': 180_000,
  '5m': 300_000,
  '15m': 900_000,
  '30m': 1_800_000,
  '1h': 3_600_000,
  '2h': 7_200_000,
  '4h': 14_400_000,
  '6h': 21_600_000,
  '8h': 28_800_000,
  '12h': 43_200_000,
  '1d': 86_400_000,
  '3d': 259_200_000,
  '1w': 604_800_000,
};

function computeCloseTime(candles: CandleData[], timeframe: string): number | null {
  const tfMs = TF_MS[timeframe];
  if (!tfMs || candles.length === 0) return null;
  const lastOpen = new Date(candles[candles.length - 1].open_time).getTime();
  return lastOpen + tfMs;
}

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

      // Reset live tick on fresh load, but compute closeTime from candle data
      setLiveTick(null);
      setCloseTime(computeCloseTime(candleResult.candles, timeframe));
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
          close_time: new Date(last.open_time).getTime() + (TF_MS[timeframe] || 3600_000),
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
    [timeframe],
  );

  return { ...state, reload: load, applyLiveCandle, updateLastCandle, liveTick, closeTime };
}
