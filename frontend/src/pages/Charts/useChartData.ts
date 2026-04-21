import { useState, useEffect, useCallback, useRef } from 'react';
import type { CandleData, SRZone, IndicatorSeriesPoint } from '../../api/client';
import { fetchCandles, fetchSRZones, fetchIndicators } from '../../api/client';

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

  // Update candle with live price
  const updateLastCandle = useCallback(
    (price: number, timestamp: string) => {
      setState(prev => {
        if (prev.candles.length === 0) return prev;
        const updated = [...prev.candles];
        const last = { ...updated[updated.length - 1] };

        // Update close, and high/low if price extends
        last.close = price;
        if (price > last.high) last.high = price;
        if (price < last.low) last.low = price;

        updated[updated.length - 1] = last;
        return { ...prev, candles: updated };
      });
    },
    [],
  );

  return { ...state, reload: load, updateLastCandle };
}
