import { useState, useMemo } from 'react';
import type { BacktestTrade } from '../../types/backtest';
import { getBacktestExportUrl } from '../../api/client';

interface Props {
  trades: BacktestTrade[];
  runId: string;
}

type SortKey = keyof BacktestTrade;
type SortDir = 'asc' | 'desc';

const OUTCOME_BADGES: Record<string, { label: string; cls: string }> = {
  HIT_TP1: { label: 'TP1', cls: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' },
  HIT_TP2: { label: 'TP2', cls: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' },
  HIT_SL: { label: 'SL', cls: 'bg-red-500/20 text-red-400 border-red-500/30' },
  EXPIRED: { label: 'EXP', cls: 'bg-slate-500/20 text-slate-400 border-slate-500/30' },
};

function formatDate(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

function formatPrice(val: number | null | undefined): string {
  if (val === null || val === undefined) return '—';
  if (val >= 1000) return val.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (val >= 1) return val.toFixed(4);
  return val.toFixed(6);
}

function formatDuration(mins: number | null): string {
  if (mins === null || mins === undefined) return '—';
  if (mins < 60) return `${Math.round(mins)}m`;
  if (mins < 1440) return `${(mins / 60).toFixed(1)}h`;
  return `${(mins / 1440).toFixed(1)}d`;
}

export default function TradeLog({ trades, runId }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>('trade_number');
  const [sortDir, setSortDir] = useState<SortDir>('asc');

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(d => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('asc');
    }
  };

  const sortedTrades = useMemo(() => {
    return [...trades].sort((a, b) => {
      const aVal = a[sortKey];
      const bVal = b[sortKey];
      if (aVal === null || aVal === undefined) return 1;
      if (bVal === null || bVal === undefined) return -1;
      if (typeof aVal === 'string' && typeof bVal === 'string') {
        return sortDir === 'asc' ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
      }
      if (typeof aVal === 'number' && typeof bVal === 'number') {
        return sortDir === 'asc' ? aVal - bVal : bVal - aVal;
      }
      return 0;
    });
  }, [trades, sortKey, sortDir]);

  const handleExportCsv = () => {
    // Client-side CSV generation as fallback
    const headers = [
      '#', 'Date', 'Symbol', 'TF', 'Direction', 'Strategy',
      'Entry', 'SL', 'TP1', 'TP2', 'Exit', 'Outcome',
      'PnL ($)', 'PnL (%)', 'R/R', 'Duration',
    ];
    const rows = sortedTrades.map(t => [
      t.trade_number,
      t.entry_time,
      t.symbol,
      t.timeframe,
      t.direction,
      t.strategy_name,
      t.entry_price,
      t.sl_price,
      t.tp1_price,
      t.tp2_price,
      t.exit_price ?? '',
      t.outcome ?? '',
      t.pnl ?? '',
      t.pnl_pct ?? '',
      t.rr_ratio ?? '',
      t.duration_mins ?? '',
    ]);

    const csvContent = [
      headers.join(','),
      ...rows.map(r => r.map(v => `"${v}"`).join(',')),
    ].join('\n');

    const blob = new Blob([csvContent], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `backtest_trades_${runId.slice(0, 8)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const columns: { key: SortKey; label: string; className?: string }[] = [
    { key: 'trade_number', label: '#', className: 'w-12' },
    { key: 'entry_time', label: 'Date', className: 'w-36' },
    { key: 'direction', label: 'Dir', className: 'w-16' },
    { key: 'strategy_name', label: 'Strategy', className: 'w-32' },
    { key: 'entry_price', label: 'Entry' },
    { key: 'sl_price', label: 'SL' },
    { key: 'tp1_price', label: 'TP1' },
    { key: 'tp2_price', label: 'TP2' },
    { key: 'exit_price', label: 'Exit' },
    { key: 'outcome', label: 'Result', className: 'w-16' },
    { key: 'pnl', label: 'PnL' },
    { key: 'rr_ratio', label: 'R/R', className: 'w-14' },
    { key: 'duration_mins', label: 'Dur', className: 'w-16' },
  ];

  return (
    <div id="trade-log">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="text-sm text-slate-400">
          {trades.length} trades
        </div>
        <div className="flex gap-2">
          <a
            href={getBacktestExportUrl(runId)}
            target="_blank"
            rel="noopener noreferrer"
            className="px-3 py-1.5 text-xs font-medium bg-slate-700 text-slate-300 rounded-lg hover:bg-slate-600 transition-colors border border-slate-600"
          >
            ⬇ Server CSV
          </a>
          <button
            onClick={handleExportCsv}
            className="px-3 py-1.5 text-xs font-medium bg-emerald-600/20 text-emerald-400 rounded-lg hover:bg-emerald-600/30 transition-colors border border-emerald-500/30"
            id="export-csv-btn"
          >
            📄 Export CSV
          </button>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto rounded-xl border border-slate-700">
        <table className="w-full text-sm" id="trade-log-table">
          <thead>
            <tr className="bg-slate-800/80">
              {columns.map(col => (
                <th
                  key={col.key}
                  onClick={() => handleSort(col.key)}
                  className={`px-3 py-2.5 text-left text-xs font-medium text-slate-400 cursor-pointer hover:text-white transition-colors select-none ${col.className || ''}`}
                >
                  <span className="flex items-center gap-1">
                    {col.label}
                    {sortKey === col.key && (
                      <span className="text-emerald-400">
                        {sortDir === 'asc' ? '↑' : '↓'}
                      </span>
                    )}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sortedTrades.map((trade, idx) => {
              const badge = OUTCOME_BADGES[trade.outcome || ''];
              return (
                <tr
                  key={trade.trade_number}
                  className={`border-t border-slate-700/50 transition-colors hover:bg-slate-700/20 ${
                    idx % 2 === 0 ? 'bg-transparent' : 'bg-slate-800/20'
                  }`}
                >
                  <td className="px-3 py-2 text-slate-500 font-mono text-xs">
                    {trade.trade_number}
                  </td>
                  <td className="px-3 py-2 text-slate-300 text-xs">
                    {formatDate(trade.entry_time)}
                  </td>
                  <td className="px-3 py-2">
                    <span className={`text-xs font-bold ${
                      trade.direction === 'LONG' ? 'text-emerald-400' : 'text-red-400'
                    }`}>
                      {trade.direction === 'LONG' ? '▲' : '▼'} {trade.direction}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-slate-300 text-xs truncate max-w-[120px]">
                    {trade.strategy_name}
                  </td>
                  <td className="px-3 py-2 text-white font-mono text-xs">
                    {formatPrice(trade.entry_price)}
                  </td>
                  <td className="px-3 py-2 text-red-400/70 font-mono text-xs">
                    {formatPrice(trade.sl_price)}
                  </td>
                  <td className="px-3 py-2 text-emerald-400/70 font-mono text-xs">
                    {formatPrice(trade.tp1_price)}
                  </td>
                  <td className="px-3 py-2 text-emerald-400/50 font-mono text-xs">
                    {formatPrice(trade.tp2_price)}
                  </td>
                  <td className="px-3 py-2 text-white font-mono text-xs">
                    {formatPrice(trade.exit_price)}
                  </td>
                  <td className="px-3 py-2">
                    {badge ? (
                      <span className={`inline-block px-1.5 py-0.5 text-[10px] font-bold rounded border ${badge.cls}`}>
                        {badge.label}
                      </span>
                    ) : (
                      <span className="text-slate-500 text-xs">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <span className={`font-mono text-xs font-medium ${
                      (trade.pnl ?? 0) >= 0 ? 'text-emerald-400' : 'text-red-400'
                    }`}>
                      {trade.pnl !== null ? `$${trade.pnl.toFixed(2)}` : '—'}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-slate-300 font-mono text-xs">
                    {trade.rr_ratio !== null ? trade.rr_ratio.toFixed(1) : '—'}
                  </td>
                  <td className="px-3 py-2 text-slate-400 text-xs">
                    {formatDuration(trade.duration_mins)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {trades.length === 0 && (
        <div className="text-center py-12 text-slate-500">
          No trades generated
        </div>
      )}
    </div>
  );
}
