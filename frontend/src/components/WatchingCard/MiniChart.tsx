import { useEffect, useRef } from 'react';
import { createChart, type IChartApi, ColorType, AreaSeries } from 'lightweight-charts';

interface MiniChartProps {
  symbol: string;
  timeframe: string;
  entry?: number | null;
}

/**
 * Minimal TradingView Lightweight Charts integration.
 * Shows last ~30 candles as an area chart with entry line.
 */
export default function MiniChart({ symbol, timeframe, entry }: MiniChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: 80,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: 'rgba(255, 255, 255, 0.3)',
        fontSize: 9,
        attributionLogo: false,
      },
      grid: {
        vertLines: { visible: false },
        horzLines: { visible: false },
      },
      rightPriceScale: { visible: false },
      timeScale: { visible: false },
      crosshair: {
        vertLine: { visible: false },
        horzLine: { visible: false },
      },
      handleScroll: false,
      handleScale: false,
    });
    chartRef.current = chart;

    const areaSeries = chart.addSeries(AreaSeries, {
      lineColor: '#10b981',
      topColor: 'rgba(16, 185, 129, 0.25)',
      bottomColor: 'rgba(16, 185, 129, 0.02)',
      lineWidth: 2,
      crosshairMarkerVisible: false,
    });

    // Fetch recent candles for this mini chart
    fetch(
      `http://localhost:5001/api/data/datasets?symbol=${symbol}&timeframe=${timeframe}`
    )
      .then((res) => res.json())
      .then((json) => {
        const datasets = json.datasets || [];
        if (datasets.length === 0) return;

        const ds = datasets[0];
        // Get recent candle data from the indicators endpoint including series
        return fetch(
          `http://localhost:5001/api/indicators?symbol=${ds.symbol}&timeframe=${ds.timeframe}&include_series=true`
        );
      })
      .then((res) => res?.json())
      .then((json) => {
        if (!json?.series?.close) return;

        const closeData = json.series.close.slice(-30).map(
          (point: { time: string; value: number }) => ({
            time: point.time.split('T')[0],
            value: point.value,
          })
        );

        if (closeData.length > 0) {
          areaSeries.setData(closeData);
          chart.timeScale().fitContent();

          // Add entry line if available
          if (entry) {
            areaSeries.createPriceLine({
              price: entry,
              color: '#f59e0b',
              lineWidth: 1,
              lineStyle: 2, // Dashed
              axisLabelVisible: false,
            });
          }
        }
      })
      .catch(() => {
        // Silent fail — mini chart is non-critical
      });

    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, [symbol, timeframe, entry]);

  return <div ref={containerRef} className="w-full h-20 mt-2" />;
}
