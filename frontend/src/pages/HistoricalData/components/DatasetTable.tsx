import { useEffect, useState } from 'react';
import { Database, AlertCircle } from 'lucide-react';
import { fetchDatasets } from '../../../api/client';
import { format } from 'date-fns';

type Dataset = {
  symbol: string;
  timeframe: string;
  start_time: string;
  end_time: string;
  count: number;
  source: string;
};

export default function DatasetTable({ refreshTrigger }: { refreshTrigger: number }) {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadDatasets();
  }, [refreshTrigger]);

  const loadDatasets = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await fetchDatasets();
      setDatasets(data || []);
    } catch (err: any) {
      console.error(err);
      setError('Could not connect to backend to fetch datasets.');
    } finally {
      setIsLoading(false);
    }
  };

  if (isLoading) {
    return (
      <div className="h-64 border border-slate-700 bg-slate-800 rounded-xl flex items-center justify-center text-slate-400 space-x-2">
        <Database size={20} className="animate-pulse" />
        <span>Loading datasets...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="h-64 border border-red-900/50 bg-red-900/20 text-red-400 rounded-xl flex flex-col items-center justify-center p-6 space-y-2 text-center">
        <AlertCircle size={24} />
        <span>{error}</span>
      </div>
    );
  }

  if (datasets.length === 0) {
    return (
      <div className="h-64 border border-slate-700 border-dashed bg-slate-800/50 rounded-xl flex flex-col items-center justify-center text-slate-500 space-y-2">
        <Database size={24} className="opacity-50" />
        <span>No historical data found.</span>
        <span className="text-xs">Use the forms to import your first dataset.</span>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-700">
      <table className="w-full text-left text-sm text-slate-400">
        <thead className="text-xs text-slate-300 uppercase bg-slate-800 border-b border-slate-700">
          <tr>
            <th className="px-6 py-4 font-semibold">Symbol</th>
            <th className="px-6 py-4 font-semibold">Timeframe</th>
            <th className="px-6 py-4 font-semibold">Start Date</th>
            <th className="px-6 py-4 font-semibold">End Date</th>
            <th className="px-6 py-4 font-semibold">Candles</th>
          </tr>
        </thead>
        <tbody>
          {datasets.map((ds, idx) => (
            <tr key={idx} className="bg-slate-900 border-b border-slate-800 hover:bg-slate-800/50 transition">
              <td className="px-6 py-4 font-medium text-white">{ds.symbol}</td>
              <td className="px-6 py-4 text-emerald-400 font-medium">{ds.timeframe}</td>
              <td className="px-6 py-4">{ds.start_time ? format(new Date(ds.start_time), 'MMM dd, yyyy HH:mm') : 'N/A'}</td>
              <td className="px-6 py-4">{ds.end_time ? format(new Date(ds.end_time), 'MMM dd, yyyy HH:mm') : 'N/A'}</td>
              <td className="px-6 py-4 tabular-nums">
                <span className="bg-slate-800 border border-slate-700 px-2 py-1 rounded text-slate-300">
                  {ds.count.toLocaleString()}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
