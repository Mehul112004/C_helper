import type { BacktestMetrics } from '../../types/backtest';

interface Props {
  metrics: BacktestMetrics;
}

interface MetricCard {
  label: string;
  value: string;
  subValue?: string;
  color: 'green' | 'red' | 'blue' | 'amber' | 'slate';
  icon: string;
}

function formatDuration(mins: number): string {
  if (mins < 60) return `${Math.round(mins)}m`;
  if (mins < 1440) return `${(mins / 60).toFixed(1)}h`;
  return `${(mins / 1440).toFixed(1)}d`;
}

export default function MetricsSummary({ metrics }: Props) {
  const cards: MetricCard[] = [
    {
      label: 'Total Trades',
      value: metrics.total_trades.toString(),
      color: 'blue',
      icon: '📋',
    },
    {
      label: 'Win Rate',
      value: `${metrics.win_rate.toFixed(1)}%`,
      color: metrics.win_rate >= 50 ? 'green' : 'red',
      icon: '🎯',
    },
    {
      label: 'Total PnL',
      value: `$${metrics.total_pnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
      subValue: `${metrics.total_pnl_pct >= 0 ? '+' : ''}${metrics.total_pnl_pct.toFixed(2)}%`,
      color: metrics.total_pnl >= 0 ? 'green' : 'red',
      icon: '💰',
    },
    {
      label: 'Sharpe Ratio',
      value: metrics.sharpe_ratio.toFixed(2),
      color: metrics.sharpe_ratio >= 1 ? 'green' : metrics.sharpe_ratio >= 0 ? 'amber' : 'red',
      icon: '📈',
    },
    {
      label: 'Sortino Ratio',
      value: metrics.sortino_ratio.toFixed(2),
      color: metrics.sortino_ratio >= 1 ? 'green' : metrics.sortino_ratio >= 0 ? 'amber' : 'red',
      icon: '📉',
    },
    {
      label: 'Max Drawdown',
      value: `$${metrics.max_drawdown.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
      subValue: `${metrics.max_drawdown_pct.toFixed(2)}%`,
      color: metrics.max_drawdown_pct <= 10 ? 'green' : metrics.max_drawdown_pct <= 25 ? 'amber' : 'red',
      icon: '📊',
    },
    {
      label: 'Avg R/R',
      value: metrics.avg_rr.toFixed(2),
      color: metrics.avg_rr >= 1.5 ? 'green' : metrics.avg_rr >= 1 ? 'amber' : 'red',
      icon: '⚖️',
    },
    {
      label: 'Profit Factor',
      value: metrics.profit_factor >= 999 ? '∞' : metrics.profit_factor.toFixed(2),
      color: metrics.profit_factor >= 1.5 ? 'green' : metrics.profit_factor >= 1 ? 'amber' : 'red',
      icon: '🏆',
    },
    {
      label: 'Avg Duration',
      value: formatDuration(metrics.avg_trade_duration_mins),
      color: 'slate',
      icon: '⏱️',
    },
    {
      label: 'Best / Worst',
      value: `$${metrics.best_trade_pnl.toFixed(0)}`,
      subValue: `$${metrics.worst_trade_pnl.toFixed(0)}`,
      color: 'blue',
      icon: '🔄',
    },
  ];

  const colorMap = {
    green: {
      bg: 'bg-emerald-500/10',
      border: 'border-emerald-500/20',
      text: 'text-emerald-400',
      sub: 'text-emerald-500/70',
    },
    red: {
      bg: 'bg-red-500/10',
      border: 'border-red-500/20',
      text: 'text-red-400',
      sub: 'text-red-500/70',
    },
    blue: {
      bg: 'bg-blue-500/10',
      border: 'border-blue-500/20',
      text: 'text-blue-400',
      sub: 'text-blue-500/70',
    },
    amber: {
      bg: 'bg-amber-500/10',
      border: 'border-amber-500/20',
      text: 'text-amber-400',
      sub: 'text-amber-500/70',
    },
    slate: {
      bg: 'bg-slate-500/10',
      border: 'border-slate-500/20',
      text: 'text-slate-300',
      sub: 'text-slate-500',
    },
  };

  return (
    <div className="grid grid-cols-2 lg:grid-cols-5 gap-3" id="metrics-summary">
      {cards.map(card => {
        const colors = colorMap[card.color];
        return (
          <div
            key={card.label}
            className={`${colors.bg} border ${colors.border} rounded-xl p-4 transition-transform hover:scale-[1.02]`}
          >
            <div className="flex items-center gap-2 mb-2">
              <span className="text-base">{card.icon}</span>
              <span className="text-xs text-slate-400 font-medium">{card.label}</span>
            </div>
            <div className={`text-xl font-bold ${colors.text}`}>
              {card.value}
            </div>
            {card.subValue && (
              <div className={`text-xs mt-0.5 ${colors.sub}`}>
                {card.subValue}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
