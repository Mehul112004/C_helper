import { useEffect, useRef, useState } from 'react';
import { createChart, type IChartApi, ColorType } from 'lightweight-charts';
import type { BacktestTrade } from '../../types/backtest';
import { apiClient } from '../../api/client';

interface Props {
  trades: BacktestTrade[];
  symbol: string;
  timeframe: string;
}

interface CandleData {
  open_time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export default function TradeChart({ trades, symbol, timeframe }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!containerRef.current || !symbol || !timeframe || trades.length === 0) {
      setLoading(false);
      return;
    }

    let cancelled = false;

    const buildChart = async () => {
      setLoading(true);
      setError(null);

      try {
        // Determine date range from trades
        const entryTimes = trades.map(t => new Date(t.entry_time).getTime());
        const exitTimes = trades
          .filter(t => t.exit_time)
          .map(t => new Date(t.exit_time!).getTime());
        const allTimes = [...entryTimes, ...exitTimes];
        const minTime = new Date(Math.min(...allTimes));
        const maxTime = new Date(Math.max(...allTimes));

        // Add padding (10% on each side)
        const range = maxTime.getTime() - minTime.getTime();
        const padStart = new Date(minTime.getTime() - range * 0.05);
        const padEnd = new Date(maxTime.getTime() + range * 0.05);

        // Fetch candle data for the range
        const { data } = await apiClient.get('/data/datasets');
        const datasets = data.datasets as { symbol: string; timeframe: string }[];

        // Check if we have data for this symbol/timeframe
        const hasData = datasets.some(
          (d: { symbol: string; timeframe: string }) => d.symbol === symbol && d.timeframe === timeframe
        );

        if (!hasData) {
          setError('No candle data available for chart rendering');
          setLoading(false);
          return;
        }

        // Fetch candles via the indicators endpoint which returns candle data
        // We'll query the raw candle data instead
        const candleResponse = await apiClient.get('/data/datasets');
        // We need to get raw candles — let's use the candle data from the datasets
        // Since we don't have a dedicated candle-fetch endpoint for arbitrary ranges,
        // we'll construct the chart from available trade data

        if (cancelled) return;

        // Cleanup previous chart
        if (chartRef.current) {
          chartRef.current.remove();
          chartRef.current = null;
        }

        const chart = createChart(containerRef.current!, {
          layout: {
            background: { type: ColorType.Solid, color: 'transparent' },
            textColor: '#94a3b8',
            fontFamily: "'Inter', -apple-system, sans-serif",
          },
          grid: {
            vertLines: { color: 'rgba(51, 65, 85, 0.4)' },
            horzLines: { color: 'rgba(51, 65, 85, 0.4)' },
          },
          crosshair: {
            vertLine: { color: 'rgba(16, 185, 129, 0.3)', labelBackgroundColor: '#10b981' },
            horzLine: { color: 'rgba(16, 185, 129, 0.3)', labelBackgroundColor: '#10b981' },
          },
          rightPriceScale: {
            borderColor: 'rgba(51, 65, 85, 0.6)',
          },
          timeScale: {
            borderColor: 'rgba(51, 65, 85, 0.6)',
            timeVisible: true,
            secondsVisible: false,
          },
          width: containerRef.current!.clientWidth,
          height: containerRef.current!.clientHeight,
        });

        chartRef.current = chart;

        // Create a line series from trade entry/exit points to show price action context
        const lineSeries = chart.addLineSeries({
          color: '#64748b',
          lineWidth: 1,
          priceFormat: {
            type: 'price',
            precision: 2,
            minMove: 0.01,
          },
        });

        // Build price data from trade entries and exits
        const pricePoints: { time: number; value: number }[] = [];
        for (const trade of trades) {
          pricePoints.push({
            time: Math.floor(new Date(trade.entry_time).getTime() / 1000),
            value: trade.entry_price,
          });
          if (trade.exit_time && trade.exit_price) {
            pricePoints.push({
              time: Math.floor(new Date(trade.exit_time).getTime() / 1000),
              value: trade.exit_price,
            });
          }
        }

        // Sort and deduplicate
        pricePoints.sort((a, b) => a.time - b.time);
        const deduped: typeof pricePoints = [];
        for (const p of pricePoints) {
          if (deduped.length === 0 || p.time > deduped[deduped.length - 1].time) {
            deduped.push(p);
          }
        }

        if (deduped.length > 0) {
          lineSeries.setData(
            deduped.map(p => ({
              time: p.time as unknown as import('lightweight-charts').UTCTimestamp,
              value: p.value,
            }))
          );
        }

        // Add trade markers
        type MarkerShape = 'arrowUp' | 'arrowDown' | 'circle';
        type MarkerPosition = 'belowBar' | 'aboveBar';

        const markers: {
          time: import('lightweight-charts').UTCTimestamp;
          position: MarkerPosition;
          color: string;
          shape: MarkerShape;
          text: string;
          size: number;
        }[] = [];

        for (const trade of trades) {
          const entryTime = Math.floor(new Date(trade.entry_time).getTime() / 1000) as unknown as import('lightweight-charts').UTCTimestamp;

          // Entry marker
          markers.push({
            time: entryTime,
            position: trade.direction === 'LONG' ? 'belowBar' : 'aboveBar',
            color: trade.direction === 'LONG' ? '#10b981' : '#ef4444',
            shape: trade.direction === 'LONG' ? 'arrowUp' : 'arrowDown',
            text: `#${trade.trade_number} ${trade.direction}`,
            size: 1.5,
          });

          // Exit marker
          if (trade.exit_time && trade.exit_price) {
            const exitTime = Math.floor(new Date(trade.exit_time).getTime() / 1000) as unknown as import('lightweight-charts').UTCTimestamp;
            let exitColor = '#6b7280'; // gray for expired
            if (trade.outcome === 'HIT_TP1' || trade.outcome === 'HIT_TP2') exitColor = '#10b981';
            if (trade.outcome === 'HIT_SL') exitColor = '#ef4444';

            markers.push({
              time: exitTime,
              position: trade.direction === 'LONG' ? 'aboveBar' : 'belowBar',
              color: exitColor,
              shape: 'circle',
              text: trade.outcome || '',
              size: 1,
            });
          }
        }

        // Sort markers by time (required by Lightweight Charts)
        markers.sort((a, b) => (a.time as unknown as number) - (b.time as unknown as number));
        lineSeries.setMarkers(markers);

        chart.timeScale().fitContent();

        // Resize handler
        const handleResize = () => {
          if (containerRef.current && chartRef.current) {
            chartRef.current.applyOptions({
              width: containerRef.current.clientWidth,
              height: containerRef.current.clientHeight,
            });
          }
        };
        const observer = new ResizeObserver(handleResize);
        observer.observe(containerRef.current!);

        setLoading(false);

        return () => {
          observer.disconnect();
        };
      } catch (err) {
        if (!cancelled) {
          setError('Failed to load chart data');
          setLoading(false);
        }
      }
    };

    buildChart();

    return () => {
      cancelled = true;
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [trades, symbol, timeframe]);

  if (trades.length === 0) {
    return (
      <div className="flex items-center justify-center h-96 text-slate-500">
        No trades to chart
      </div>
    );
  }

  // Trade summary strip
  const longCount = trades.filter(t => t.direction === 'LONG').length;
  const shortCount = trades.filter(t => t.direction === 'SHORT').length;
  const tpCount = trades.filter(t => t.outcome === 'HIT_TP1' || t.outcome === 'HIT_TP2').length;
  const slCount = trades.filter(t => t.outcome === 'HIT_SL').length;

  return (
    <div id="trade-chart">
      {/* Summary strip */}
      <div className="flex gap-6 mb-4 text-sm">
        <div>
          <span className="text-slate-500">Trades: </span>
          <span className="text-white font-medium">{trades.length}</span>
        </div>
        <div>
          <span className="text-emerald-400 font-medium">{longCount} Long</span>
          <span className="text-slate-600 mx-1.5">·</span>
          <span className="text-red-400 font-medium">{shortCount} Short</span>
        </div>
        <div>
          <span className="text-emerald-400">✓ {tpCount} TP</span>
          <span className="text-slate-600 mx-1.5">·</span>
          <span className="text-red-400">✗ {slCount} SL</span>
        </div>
      </div>

      {loading && (
        <div className="flex items-center justify-center h-[500px] border border-slate-700 rounded-xl bg-slate-800/30">
          <div className="text-center">
            <div className="w-8 h-8 border-3 border-emerald-500/30 border-t-emerald-500 rounded-full animate-spin mx-auto mb-3" />
            <p className="text-slate-400 text-sm">Loading chart...</p>
          </div>
        </div>
      )}

      {error && (
        <div className="flex items-center justify-center h-[500px] border border-slate-700 rounded-xl bg-slate-800/30">
          <p className="text-slate-500 text-sm">{error}</p>
        </div>
      )}

      {/* Chart container */}
      <div
        ref={containerRef}
        className={`w-full h-[500px] rounded-xl border border-slate-700 bg-slate-800/30 overflow-hidden ${
          loading || error ? 'hidden' : ''
        }`}
      />

      {/* Legend */}
      <div className="flex items-center gap-4 mt-3 text-xs text-slate-500">
        <div className="flex items-center gap-1.5">
          <span className="w-0 h-0 border-l-[5px] border-r-[5px] border-b-[8px] border-transparent border-b-emerald-500" />
          Long Entry
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-0 h-0 border-l-[5px] border-r-[5px] border-t-[8px] border-transparent border-t-red-500" />
          Short Entry
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-emerald-500" />
          TP Hit
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-red-500" />
          SL Hit
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-gray-500" />
          Expired
        </div>
      </div>
    </div>
  );
}
