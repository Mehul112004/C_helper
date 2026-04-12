import React, { useState } from 'react';
import { DownloadCloud, Loader2 } from 'lucide-react';
import { importBinanceData } from '../../../api/client';

export default function BinanceImportForm({ onSuccess }: { onSuccess: () => void }) {
  const [symbol, setSymbol] = useState('BTCUSDT');
  const [timeframe, setTimeframe] = useState('1h');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [statusMsg, setStatusMsg] = useState<{type: 'success'|'error', text: string} | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setStatusMsg(null);
    try {
      // Input datetime html5 handles local time zone, ensure we send ISO string standard format
      const startIso = new Date(startDate).toISOString();
      const endIso = new Date(endDate).toISOString();
      
      const result = await importBinanceData({
        symbol,
        timeframe,
        start_time: startIso,
        end_time: endIso
      });
      setStatusMsg({ type: 'success', text: `Imported ${result.count} candles successfully.`});
      onSuccess();
    } catch (err: any) {
      console.error(err);
      setStatusMsg({ type: 'error', text: err.response?.data?.error || err.message || 'Failed to import data.' });
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div>
        <label className="block text-xs font-semibold text-slate-400 mb-1">Symbol</label>
        <select 
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          className="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-sm text-white focus:outline-none focus:ring-1 focus:ring-emerald-500"
        >
          <option value="BTCUSDT">BTCUSDT</option>
          <option value="ETHUSDT">ETHUSDT</option>
          <option value="SOLUSDT">SOLUSDT</option>
          <option value="XRPUSDT">XRPUSDT</option>
        </select>
      </div>

      <div>
        <label className="block text-xs font-semibold text-slate-400 mb-1">Timeframe</label>
        <select 
          value={timeframe}
          onChange={(e) => setTimeframe(e.target.value)}
          className="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-sm text-white focus:outline-none focus:ring-1 focus:ring-emerald-500"
        >
          <option value="5m">5m</option>
          <option value="15m">15m</option>
          <option value="1h">1h</option>
          <option value="4h">4h</option>
          <option value="1d">1d</option>
        </select>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-semibold text-slate-400 mb-1">Start Date</label>
          <input 
            type="datetime-local" 
            required
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-emerald-500"
          />
        </div>
        <div>
          <label className="block text-xs font-semibold text-slate-400 mb-1">End Date</label>
          <input 
            type="datetime-local" 
            required
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            className="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-emerald-500"
          />
        </div>
      </div>

      {statusMsg && (
        <div className={`p-3 rounded-lg text-sm flex items-center gap-2 ${
          statusMsg.type === 'success' ? 'bg-emerald-900/40 text-emerald-400' : 'bg-red-900/40 text-red-400'
        }`}>
          {statusMsg.text}
        </div>
      )}

      <button
        type="submit"
        disabled={isLoading}
        className="w-full mt-4 flex items-center justify-center space-x-2 bg-emerald-600 hover:bg-emerald-500 text-white font-semibold py-2.5 px-4 rounded-lg transition disabled:opacity-50"
      >
        {isLoading ? (
          <Loader2 size={18} className="animate-spin" />
        ) : (
          <DownloadCloud size={18} />
        )}
        <span>{isLoading ? 'Fetching Data...' : 'Start Job'}</span>
      </button>
    </form>
  );
}
