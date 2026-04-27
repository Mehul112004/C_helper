import { useEffect, useRef, useState, useCallback, forwardRef, useImperativeHandle } from "react";
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  ColorType,
  type CandlestickData,
  type UTCTimestamp,
  type HistogramData,
  type LineData,
} from "lightweight-charts";
import type {
  CandleData,
  SRZone,
  IndicatorSeriesPoint,
} from "../../api/client";
import type { LiveCandleEvent } from "../../types/signals";

/* ─── colour constants ─── */
const ZONE_COLORS: Record<string, { line: string; bg: string }> = {
  support: { line: "#10b981", bg: "rgba(16, 185, 129, 0.06)" },
  resistance: { line: "#ef4444", bg: "rgba(239, 68, 68, 0.06)" },
  both: { line: "#f59e0b", bg: "rgba(245, 158, 11, 0.06)" },
};

const EMA_COLORS: Record<string, string> = {
  ema_9: "#f59e0b",
  ema_21: "#3b82f6",
  ema_50: "#8b5cf6",
  ema_200: "#ef4444",
};

/* ─── helpers ─── */
function toUTC(iso: string): UTCTimestamp {
  return Math.floor(new Date(iso).getTime() / 1000) as UTCTimestamp;
}

function msToUTC(ms: number): UTCTimestamp {
  return Math.floor(ms / 1000) as UTCTimestamp;
}

/* ─── props ─── */
interface CandleChartProps {
  candles: CandleData[];
  srZones: SRZone[];
  showSRZones: boolean;
  emaLines: {
    ema_9: IndicatorSeriesPoint[];
    ema_21: IndicatorSeriesPoint[];
    ema_50: IndicatorSeriesPoint[];
    ema_200: IndicatorSeriesPoint[];
  };
  showEMA: boolean;
  emaVisible: Record<string, boolean>;
  loading: boolean;
  error: string | null;
  symbol: string;
  timeframe: string;
  liveTick: LiveCandleEvent | null;
  closeTime: number | null;
}

export interface CandleChartRef {
  resetView: () => void;
}

const CandleChart = forwardRef<CandleChartRef, CandleChartProps>(({
  candles,
  srZones,
  showSRZones,
  emaLines,
  showEMA,
  emaVisible,
  loading,
  error,
  symbol,
  timeframe,
  liveTick,
  closeTime,
}, ref) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const emaSeriesRef = useRef<Record<string, ISeriesApi<"Line">>>({});
  const srPriceLinesRef = useRef<
    ReturnType<ISeriesApi<"Candlestick">["createPriceLine"]>[]>([]);
  const legendRef = useRef<HTMLDivElement>(null);
  const chartInitialized = useRef(false);
  const lastChartConfig = useRef<string>("");

  /* ─── countdown timer (isolated state — no chart redraws) ─── */
  const [countdown, setCountdown] = useState<string | null>(null);

  useEffect(() => {
    if (closeTime == null) {
      setCountdown(null);
      return;
    }

    const tick = () => {
      const diff = closeTime - Date.now();
      if (diff <= 0) {
        setCountdown("00:00");
        return;
      }
      const totalSec = Math.floor(diff / 1000);
      const h = Math.floor(totalSec / 3600);
      const m = Math.floor((totalSec % 3600) / 60);
      const s = totalSec % 60;
      if (h > 0) {
        setCountdown(
          `${h}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`
        );
      } else {
        setCountdown(
          `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`
        );
      }
    };

    tick(); // immediate first tick
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [closeTime]);

  /* ───────────────────── expose imperative handle ───────────────────── */
  useImperativeHandle(ref, () => ({
    resetView: () => {
      if (chartRef.current) {
        chartRef.current.timeScale().scrollToRealTime();
        chartRef.current.priceScale("right").applyOptions({
          autoScale: true,
        });
      }
    },
  }));

  /* ───────────────────── create chart instance ───────────────────── */
  const ensureChart = useCallback(() => {
    if (chartInitialized.current && chartRef.current) return; // already created
    if (!containerRef.current) return;

    // Cleanup if somehow stale
    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      emaSeriesRef.current = {};
      srPriceLinesRef.current = [];
    }

    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#94a3b8",
        fontFamily: "'Inter', -apple-system, sans-serif",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "rgba(51, 65, 85, 0.3)" },
        horzLines: { color: "rgba(51, 65, 85, 0.3)" },
      },
      crosshair: {
        vertLine: {
          color: "rgba(16, 185, 129, 0.25)",
          labelBackgroundColor: "#10b981",
        },
        horzLine: {
          color: "rgba(16, 185, 129, 0.25)",
          labelBackgroundColor: "#10b981",
        },
      },
      rightPriceScale: {
        borderColor: "rgba(51, 65, 85, 0.5)",
        scaleMargins: { top: 0.08, bottom: 0.16 },
      },
      timeScale: {
        borderColor: "rgba(51, 65, 85, 0.5)",
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 5,
        barSpacing: 8,
      },
    });

    chartRef.current = chart;

    // Candlestick series
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#10b981",
      downColor: "#ef4444",
      borderDownColor: "#ef4444",
      borderUpColor: "#10b981",
      wickDownColor: "#ef4444",
      wickUpColor: "#10b981",
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
    });
    candleSeriesRef.current = candleSeries;

    // Volume histogram (overlaid at bottom)
    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    });
    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.85, bottom: 0 },
    });
    volumeSeriesRef.current = volumeSeries;

    // OHLCV crosshair legend
    chart.subscribeCrosshairMove((param) => {
      if (!legendRef.current) return;

      if (
        !param.time ||
        !param.seriesData ||
        !param.seriesData.has(candleSeries)
      ) {
        legendRef.current.innerHTML = "";
        return;
      }

      const d = param.seriesData.get(candleSeries) as CandlestickData;
      if (!d) return;

      const change = d.close - d.open;
      const changePct = d.open !== 0 ? (change / d.open) * 100 : 0;
      const color = change >= 0 ? "#10b981" : "#ef4444";

      legendRef.current.innerHTML = `
        <span style="color:#94a3b8;margin-right:8px">O</span><span style="color:${color}">${d.open.toFixed(2)}</span>
        <span style="color:#94a3b8;margin-left:10px;margin-right:8px">H</span><span style="color:${color}">${d.high.toFixed(2)}</span>
        <span style="color:#94a3b8;margin-left:10px;margin-right:8px">L</span><span style="color:${color}">${d.low.toFixed(2)}</span>
        <span style="color:#94a3b8;margin-left:10px;margin-right:8px">C</span><span style="color:${color}">${d.close.toFixed(2)}</span>
        <span style="margin-left:14px;color:${color};font-weight:600">${change >= 0 ? "+" : ""}${changePct.toFixed(2)}%</span>
      `;
    });

    chartInitialized.current = true;
  }, []);

  /* ───────────────────── cleanup on unmount ───────────────────── */
  useEffect(() => {
    return () => {
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
        candleSeriesRef.current = null;
        volumeSeriesRef.current = null;
        emaSeriesRef.current = {};
        srPriceLinesRef.current = [];
        chartInitialized.current = false;
      }
    };
  }, []);

  /* ───────────────────── update candle + volume data (full setData) ───────────────────── */
  useEffect(() => {
    if (candles.length === 0) return;

    // Lazily initialize chart the first time we have data + a real DOM node
    ensureChart();

    if (!candleSeriesRef.current || !volumeSeriesRef.current) return;

    const candleData: CandlestickData[] = candles.map((c) => ({
      time: toUTC(c.open_time),
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }));

    const volumeData: HistogramData[] = candles.map((c) => ({
      time: toUTC(c.open_time),
      value: c.volume,
      color:
        c.close >= c.open
          ? "rgba(16, 185, 129, 0.18)"
          : "rgba(239, 68, 68, 0.18)",
    }));

    candleSeriesRef.current.setData(candleData);
    volumeSeriesRef.current.setData(volumeData);
    
    const configKey = `${symbol}-${timeframe}`;
    if (lastChartConfig.current !== configKey) {
      chartRef.current?.timeScale().fitContent();
      lastChartConfig.current = configKey;
    }
  }, [candles, symbol, timeframe, ensureChart]);

  /* ───────────────────── live tick via .update() ───────────────────── */
  useEffect(() => {
    if (!liveTick) return;
    if (!candleSeriesRef.current || !volumeSeriesRef.current) return;

    const ts = msToUTC(liveTick.open_time);

    try {
      candleSeriesRef.current.update({
        time: ts,
        open: liveTick.open,
        high: liveTick.high,
        low: liveTick.low,
        close: liveTick.close,
      });

      volumeSeriesRef.current.update({
        time: ts,
        value: liveTick.volume,
        color:
          liveTick.close >= liveTick.open
            ? "rgba(16, 185, 129, 0.18)"
            : "rgba(239, 68, 68, 0.18)",
      });
    } catch {
      // Stale tick from previous timeframe — ignore during transition
    }
  }, [liveTick]);

  /* ───────────────────── S/R zone price lines ───────────────────── */
  useEffect(() => {
    if (!candleSeriesRef.current) return;
    const series = candleSeriesRef.current;

    // Remove old price lines
    srPriceLinesRef.current.forEach((line) => {
      try {
        series.removePriceLine(line);
      } catch {
        /* already removed */
      }
    });
    srPriceLinesRef.current = [];

    if (!showSRZones || srZones.length === 0) return;

    // Add zone price lines
    for (const zone of srZones) {
      const colors = ZONE_COLORS[zone.zone_type] || ZONE_COLORS.both;

      // Center line
      const centerLine = series.createPriceLine({
        price: zone.price_level,
        color: colors.line,
        lineWidth: zone.strength_score > 0.7 ? 2 : 1,
        lineStyle: 2, // dashed
        axisLabelVisible: true,
        title: `${zone.zone_type === "support" ? "S" : zone.zone_type === "resistance" ? "R" : "SR"} ${zone.price_level.toFixed(0)} (${(zone.strength_score * 100).toFixed(0)}%)`,
        lineVisible: true,
      });
      srPriceLinesRef.current.push(centerLine);

      // Upper bound (thin, more transparent)
      const upperLine = series.createPriceLine({
        price: zone.zone_upper,
        color: colors.line + "40",
        lineWidth: 1,
        lineStyle: 3, // dotted
        axisLabelVisible: false,
        title: "",
        lineVisible: true,
      });
      srPriceLinesRef.current.push(upperLine);

      // Lower bound
      const lowerLine = series.createPriceLine({
        price: zone.zone_lower,
        color: colors.line + "40",
        lineWidth: 1,
        lineStyle: 3,
        axisLabelVisible: false,
        title: "",
        lineVisible: true,
      });
      srPriceLinesRef.current.push(lowerLine);
    }
  }, [showSRZones, srZones]);

  /* ───────────────────── EMA line overlays ───────────────────── */
  useEffect(() => {
    if (!chartRef.current) return;

    // Remove old EMA series
    Object.values(emaSeriesRef.current).forEach((s) => {
      try {
        chartRef.current?.removeSeries(s);
      } catch {
        /* ok */
      }
    });
    emaSeriesRef.current = {};

    if (!showEMA) return;

    const emaKeys = ["ema_9", "ema_21", "ema_50", "ema_200"] as const;

    for (const key of emaKeys) {
      if (!emaVisible[key]) continue;

      const points = emaLines[key];
      if (!points || points.length === 0) continue;

      const series = chartRef.current.addSeries(LineSeries, {
        color: EMA_COLORS[key],
        lineWidth: key === "ema_200" ? 2 : 1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });

      const data: LineData[] = points.map((p) => ({
        time: toUTC(p.time),
        value: p.value,
      }));

      series.setData(data);
      emaSeriesRef.current[key] = series;
    }
  }, [showEMA, emaVisible, emaLines]);

  /* ─── derived values ─── */
  const hasCandles = candles.length > 0;
  const lastCandle = hasCandles ? candles[candles.length - 1] : null;
  const prevCandle = candles.length > 1 ? candles[candles.length - 2] : null;
  const priceChange =
    prevCandle && lastCandle ? lastCandle.close - prevCandle.close : 0;
  const priceChangePct =
    prevCandle && prevCandle.close !== 0
      ? (priceChange / prevCandle.close) * 100
      : 0;

  /* ───────────────────── RENDER ───────────────────── */
  return (
    <div className="relative flex flex-col flex-1 min-h-0" id="candle-chart">
      {/* Loading overlay */}
      {loading && !hasCandles && (
        <div
          className="z-20 absolute inset-0 flex justify-center items-center bg-slate-900/80 backdrop-blur-sm"
          id="chart-loading"
        >
          <div className="text-center">
            <div className="mx-auto mb-4 border-4 border-emerald-500/30 border-t-emerald-500 rounded-full w-10 h-10 animate-spin" />
            <p className="text-slate-400 text-sm">Loading chart data…</p>
            <p className="mt-1 text-slate-600 text-xs">
              {symbol} · {timeframe}
            </p>
          </div>
        </div>
      )}

      {/* Error overlay */}
      {error && !hasCandles && (
        <div
          className="z-20 absolute inset-0 flex justify-center items-center bg-slate-900/80"
          id="chart-error"
        >
          <div className="bg-red-500/10 px-6 py-4 border border-red-500/30 rounded-xl max-w-md text-center">
            <p className="font-medium text-red-400">Chart Error</p>
            <p className="mt-1 text-red-300/70 text-sm">{error}</p>
          </div>
        </div>
      )}

      {/* Empty overlay */}
      {!hasCandles && !loading && !error && (
        <div
          className="z-20 absolute inset-0 flex justify-center items-center bg-slate-900/80"
          id="chart-empty"
        >
          <div className="text-center text-slate-500">
            <div className="opacity-30 mb-4 text-5xl">📊</div>
            <p className="font-medium text-lg">No candle data</p>
            <p className="mt-1 text-sm">
              Select a symbol/timeframe with imported data
            </p>
          </div>
        </div>
      )}

      {/* Live price header */}
      {lastCandle && (
        <div
          className="top-3 left-4 z-10 absolute flex items-baseline gap-3 pointer-events-none"
          id="price-header"
        >
          <span className="font-bold text-2xl text-white tracking-tight">
            {lastCandle.close.toLocaleString(undefined, {
              minimumFractionDigits: 2,
              maximumFractionDigits: 2,
            })}
          </span>
          <span
            className={`text-sm font-semibold ${priceChange >= 0 ? "text-emerald-400" : "text-red-400"}`}
          >
            {priceChange >= 0 ? "+" : ""}
            {priceChangePct.toFixed(2)}%
          </span>
          {loading && (
            <div className="border-2 border-emerald-500/40 border-t-emerald-500 rounded-full w-3 h-3 animate-spin" />
          )}
        </div>
      )}

      {/* OHLCV crosshair legend */}
      <div
        ref={legendRef}
        className="top-11 left-4 z-10 absolute font-mono text-xs pointer-events-none"
        id="ohlcv-legend"
      />

      {/* Candle countdown timer */}
      {countdown && (
        <div
          className="top-3 right-4 z-20 absolute pointer-events-none flex items-center gap-1.5"
          id="candle-countdown"
        >
          <div
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-md border font-mono text-xs font-semibold tabular-nums"
            style={{
              background: "rgba(15, 23, 42, 0.85)",
              borderColor: "rgba(16, 185, 129, 0.3)",
              color: countdown === "00:00" ? "#f59e0b" : "#10b981",
              backdropFilter: "blur(4px)",
            }}
          >
            <svg width="10" height="10" viewBox="0 0 10 10" fill="none" style={{ flexShrink: 0 }}>
              <circle cx="5" cy="5" r="4" stroke="currentColor" strokeWidth="1.2" opacity="0.5" />
              <path d="M5 2.5V5L6.5 6.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
            </svg>
            {countdown}
          </div>
        </div>
      )}

      {/* Overlay info badges — shifted down when countdown visible */}
      {showSRZones && srZones.length > 0 && (
        <div
          className="z-10 absolute pointer-events-none"
          style={{
            top: countdown ? "2.5rem" : "0.75rem",
            right: "1rem",
          }}
        >
          <span className="bg-slate-800/80 px-2 py-1 border border-slate-600/40 rounded text-[10px] text-slate-400">
            {srZones.length} S/R zone{srZones.length !== 1 ? "s" : ""}
          </span>
        </div>
      )}

      {/* EMA legend */}
      {showEMA && (
        <div
          className="z-10 absolute flex gap-2 pointer-events-none"
          style={{
            top: countdown
              ? showSRZones && srZones.length > 0
                ? "4rem"
                : "2.5rem"
              : showSRZones && srZones.length > 0
                ? "2.5rem"
                : "0.75rem",
            right: "1rem",
          }}
        >
          {Object.entries(EMA_COLORS).map(([key, color]) =>
            emaVisible[key] ? (
              <span
                key={key}
                className="font-bold text-[10px]"
                style={{ color }}
              >
                {key.replace("ema_", "EMA ")}
              </span>
            ) : null,
          )}
        </div>
      )}

      {/* Chart container — ALWAYS rendered so containerRef is never null */}
      <div
        ref={containerRef}
        className="flex-1 w-full min-h-0"
        style={{ minHeight: "400px" }}
      />
    </div>
  );
});

export default CandleChart;
