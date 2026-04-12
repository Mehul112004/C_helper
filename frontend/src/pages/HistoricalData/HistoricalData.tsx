import React, { useState } from 'react';
import BinanceImportForm from './components/BinanceImportForm';
import CSVUploadForm from './components/CSVUploadForm';
import DatasetTable from './components/DatasetTable';

const HistoricalData: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'binance' | 'csv'>('binance');
  const [refreshTrigger, setRefreshTrigger] = useState(0);

  const handleImportSuccess = () => {
    setRefreshTrigger(prev => prev + 1);
  };

  return (
    <div className="p-8 max-w-6xl mx-auto space-y-6">
      <header className="mb-8">
        <h1 className="text-3xl font-bold text-white mb-2">Historical Data Hub</h1>
        <p className="text-slate-400 text-sm">
          Import and manage OHLCV candle data for backtesting and analysis.
        </p>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-1 border border-slate-700 bg-slate-800 rounded-xl overflow-hidden shadow-lg h-fit">
          <div className="flex border-b border-slate-700">
            <button
              onClick={() => setActiveTab('binance')}
              className={`flex-1 py-3 text-sm font-semibold transition ${
                activeTab === 'binance' 
                  ? 'bg-slate-700 text-emerald-400 border-b-2 border-emerald-400' 
                  : 'text-slate-400 hover:text-white hover:bg-slate-700/50'
              }`}
            >
              Binance Fetch
            </button>
            <button
              onClick={() => setActiveTab('csv')}
              className={`flex-1 py-3 text-sm font-semibold transition ${
                activeTab === 'csv' 
                  ? 'bg-slate-700 text-emerald-400 border-b-2 border-emerald-400' 
                  : 'text-slate-400 hover:text-white hover:bg-slate-700/50'
              }`}
            >
              CSV Upload
            </button>
          </div>
          
          <div className="p-6">
            {activeTab === 'binance' ? (
              <BinanceImportForm onSuccess={handleImportSuccess} />
            ) : (
              <CSVUploadForm onSuccess={handleImportSuccess} />
            )}
          </div>
        </div>

        <div className="lg:col-span-2 space-y-4">
          <h2 className="text-xl font-semibold text-slate-200">Local Datasets</h2>
          <DatasetTable refreshTrigger={refreshTrigger} />
        </div>
      </div>
    </div>
  );
};

export default HistoricalData;
