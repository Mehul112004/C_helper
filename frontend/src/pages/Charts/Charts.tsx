import { useState, useCallback } from 'react';
import { useSSE } from '../../hooks/useSSE';
import type { SSEEventType } from '../../types/signals';
import ChartControls from './ChartControls';
import CandleChart from './CandleChart';
import { useChartData } from './useChartData';
import { Wifi, WifiOff } from 'lucide-react';

export default function Charts() {
  /* ─── control state ─── */
  const [symbol, setSymbol] = useState('BTCUSDT');
  const [timeframe, setTimeframe] = useState('4h');
  const [limit, setLimit] = useState(500);
  const [showSRZones, setShowSRZones] = useState(true);
  const [minStrength, setMinStrength] = useState(0.2);
  const [showEMA, setShowEMA] = useState(true);
  const [emaVisible, setEmaVisible] = useState<Record<string, boolean>>({
    ema_9: true,
    ema_21: true,
    ema_50: false,
    ema_200: true,
  });

  /* ─── data hook ─── */
  const {
    candles,
    srZones,
    emaLines,
    loading,
    error,
    updateLastCandle,
  } = useChartData(symbol, timeframe, limit, showSRZones, minStrength, showEMA);

  /* ─── SSE live price updates ─── */
  const handleSSEEvent = useCallback(
    (eventType: SSEEventType, data: Record<string, unknown>) => {
      if (eventType === 'price_update') {
        const evtSymbol = data.symbol as string;
        const price = data.price as number;
        const timestamp = data.timestamp as string;

        if (evtSymbol === symbol && price) {
          updateLastCandle(price, timestamp);
        }
      }
    },
    [symbol, updateLastCandle],
  );

  const { connected, reconnecting } = useSSE(handleSSEEvent);

  /* ─── toggle handlers ─── */
  const toggleEMALine = useCallback((key: string) => {
    setEmaVisible(prev => ({ ...prev, [key]: !prev[key] }));
  }, []);

  return (
    <div className="h-full flex flex-col" id="charts-page">
      {/* Header */}
      <div className="px-5 py-3 border-b border-slate-700/80 flex items-center justify-between bg-slate-800/40">
        <div>
          <h1 className="text-xl font-bold text-white tracking-tight">Charts</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Candlestick · S/R Zones · EMA Overlays
          </p>
        </div>

        {/* Connection status */}
        <div className="flex items-center gap-2">
          {candles.length > 0 && (
            <span className="text-xs text-slate-500">
              {candles.length.toLocaleString()} candles
            </span>
          )}
          <div
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-medium border transition-all ${
              connected
                ? 'text-emerald-400 border-emerald-500/30 bg-emerald-500/10'
                : reconnecting
                  ? 'text-amber-400 border-amber-500/30 bg-amber-500/10 animate-pulse'
                  : 'text-slate-500 border-slate-600/40 bg-slate-700/30'
            }`}
            id="sse-status"
          >
            {connected ? <Wifi size={10} /> : <WifiOff size={10} />}
            {connected ? 'LIVE' : reconnecting ? 'RECONNECTING' : 'OFFLINE'}
          </div>
        </div>
      </div>

      {/* Controls */}
      <ChartControls
        symbol={symbol}
        timeframe={timeframe}
        limit={limit}
        showSRZones={showSRZones}
        minStrength={minStrength}
        showEMA={showEMA}
        emaVisible={emaVisible}
        onSymbolChange={setSymbol}
        onTimeframeChange={setTimeframe}
        onLimitChange={setLimit}
        onToggleSRZones={() => setShowSRZones(p => !p)}
        onMinStrengthChange={setMinStrength}
        onToggleEMA={() => setShowEMA(p => !p)}
        onToggleEMALine={toggleEMALine}
      />

      {/* Chart */}
      <CandleChart
        candles={candles}
        srZones={srZones}
        showSRZones={showSRZones}
        emaLines={emaLines}
        showEMA={showEMA}
        emaVisible={emaVisible}
        loading={loading}
        error={error}
        symbol={symbol}
        timeframe={timeframe}
      />
    </div>
  );
}
