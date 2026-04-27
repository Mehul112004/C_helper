import { useEffect, useRef } from 'react';
import { createChart, type IChartApi, type ISeriesApi, ColorType, LineType, AreaSeries } from 'lightweight-charts';
import type { EquityCurvePoint } from '../../types/backtest';

interface Props {
  data: EquityCurvePoint[];
}

export default function EquityCurve({ data }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const areaSeriesRef = useRef<ISeriesApi<'Area'> | null>(null);

  useEffect(() => {
    if (!containerRef.current || data.length === 0) return;

    // Cleanup previous chart
    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    const chart = createChart(containerRef.current, {
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
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight,
    });

    chartRef.current = chart;

    // Area series for equity curve
    const areaSeries = chart.addSeries(AreaSeries, {
      topColor: 'rgba(16, 185, 129, 0.35)',
      bottomColor: 'rgba(16, 185, 129, 0.02)',
      lineColor: '#10b981',
      lineWidth: 2,
      lineType: LineType.Curved,
      crosshairMarkerBackgroundColor: '#10b981',
      priceFormat: {
        type: 'custom',
        formatter: (price: number) => `$${price.toLocaleString(undefined, { maximumFractionDigits: 0 })}`,
      },
    });

    areaSeriesRef.current = areaSeries;

    // Transform data for Lightweight Charts
    // Each point needs {time, value} where time is YYYY-MM-DD or unix timestamp
    const chartData = data.map(point => {
      const dt = new Date(point.time);
      return {
        time: (dt.getTime() / 1000) as unknown as import('lightweight-charts').UTCTimestamp,
        value: point.value,
      };
    });

    // Sort by time and deduplicate
    chartData.sort((a, b) => (a.time as unknown as number) - (b.time as unknown as number));
    const dedupedData: typeof chartData = [];
    for (const point of chartData) {
      if (dedupedData.length === 0 || (point.time as unknown as number) > (dedupedData[dedupedData.length - 1].time as unknown as number)) {
        dedupedData.push(point);
      }
    }

    areaSeries.setData(dedupedData);
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
    observer.observe(containerRef.current);

    return () => {
      observer.disconnect();
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [data]);

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-96 text-slate-500">
        No equity curve data available
      </div>
    );
  }

  // Summary stats
  const startValue = data[0]?.value ?? 0;
  const endValue = data[data.length - 1]?.value ?? 0;
  const totalReturn = endValue - startValue;
  const totalReturnPct = startValue > 0 ? ((totalReturn / startValue) * 100) : 0;

  return (
    <div id="equity-curve">
      {/* Mini stats bar */}
      <div className="flex gap-6 mb-4 text-sm">
        <div>
          <span className="text-slate-500">Start: </span>
          <span className="text-white font-medium">${startValue.toLocaleString()}</span>
        </div>
        <div>
          <span className="text-slate-500">End: </span>
          <span className="text-white font-medium">${endValue.toLocaleString()}</span>
        </div>
        <div>
          <span className="text-slate-500">Return: </span>
          <span className={`font-medium ${totalReturn >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
            {totalReturn >= 0 ? '+' : ''}${totalReturn.toLocaleString(undefined, { maximumFractionDigits: 2 })}
            {' '}({totalReturnPct >= 0 ? '+' : ''}{totalReturnPct.toFixed(2)}%)
          </span>
        </div>
      </div>

      {/* Chart container */}
      <div
        ref={containerRef}
        className="w-full h-[500px] rounded-xl border border-slate-700 bg-slate-800/30 overflow-hidden"
      />
    </div>
  );
}
