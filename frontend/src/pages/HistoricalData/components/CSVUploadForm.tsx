import React, { useRef, useState } from 'react';
import { UploadCloud, Loader2, FileUp } from 'lucide-react';
import { importCsvData } from '../../../api/client';

export default function CSVUploadForm({ onSuccess }: { onSuccess: () => void }) {
  const [symbol, setSymbol] = useState('BTCUSDT');
  const [timeframe, setTimeframe] = useState('1h');
  const [file, setFile] = useState<File | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [statusMsg, setStatusMsg] = useState<{type: 'success'|'error', text: string} | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      setFile(e.target.files[0]);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) {
      setStatusMsg({ type: 'error', text: 'Please select a CSV file first.' });
      return;
    }
    
    setIsLoading(true);
    setStatusMsg(null);
    
    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('symbol', symbol);
      formData.append('timeframe', timeframe);
      
      const result = await importCsvData(formData);
      setStatusMsg({ type: 'success', text: `Imported ${result.count} candles successfully.`});
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = '';
      onSuccess();
    } catch (err: any) {
      console.error(err);
      setStatusMsg({ type: 'error', text: err.response?.data?.error || err.message || 'Failed to import CSV.' });
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

      <div>
        <label className="block text-xs font-semibold text-slate-400 mb-1">Upload CSV</label>
        <div 
          className="mt-1 flex justify-center px-6 pt-5 pb-6 border-2 border-slate-700 border-dashed rounded-lg hover:border-emerald-500 transition cursor-pointer"
          onClick={() => fileInputRef.current?.click()}
        >
          <div className="space-y-1 text-center">
            <UploadCloud className="mx-auto h-10 w-10 text-slate-500 mb-2" />
            <div className="flex text-sm text-slate-400 justify-center">
              <span className="relative rounded-md text-emerald-500 font-semibold focus-within:outline-none focus-within:ring-2 focus-within:ring-offset-2 focus-within:ring-emerald-500 cursor-pointer">
                {file ? file.name : "Select a file"}
                <input ref={fileInputRef} type="file" accept=".csv" className="sr-only" onChange={handleFileChange} />
              </span>
            </div>
            {!file && <p className="text-xs text-slate-500">Must be Binance export format</p>}
          </div>
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
        disabled={isLoading || !file}
        className="w-full mt-4 flex items-center justify-center space-x-2 bg-emerald-600 hover:bg-emerald-500 text-white font-semibold py-2.5 px-4 rounded-lg transition disabled:opacity-50"
      >
        {isLoading ? (
          <Loader2 size={18} className="animate-spin" />
        ) : (
          <FileUp size={18} />
        )}
        <span>{isLoading ? 'Processing...' : 'Upload Data'}</span>
      </button>
    </form>
  );
}
