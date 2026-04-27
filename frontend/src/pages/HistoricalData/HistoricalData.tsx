import React, { useState } from "react";
import BinanceImportForm from "./components/BinanceImportForm";
import CSVUploadForm from "./components/CSVUploadForm";
import DatasetTable from "./components/DatasetTable";

const HistoricalData: React.FC = () => {
  const [activeTab, setActiveTab] = useState<"binance" | "csv">("binance");
  const [refreshTrigger, setRefreshTrigger] = useState(0);

  const handleImportSuccess = () => {
    setRefreshTrigger((prev) => prev + 1);
  };

  return (
    <div className="h-full w-full overflow-y-auto">
      <div className="space-y-6 mx-auto p-8 max-w-6xl">
        <header className="mb-8">
          <h1 className="mb-2 font-bold text-3xl text-white">
            Historical Data Hub
          </h1>
          <p className="text-slate-400 text-sm">
            Import and manage OHLCV candle data for backtesting and analysis.
          </p>
        </header>

        <div className="gap-8 grid grid-cols-1 lg:grid-cols-3">
          <div className="lg:col-span-1 bg-slate-800 shadow-lg border border-slate-700 rounded-xl h-fit overflow-hidden">
            <div className="flex border-slate-700 border-b">
              <button
                onClick={() => setActiveTab("binance")}
                className={`flex-1 py-3 text-sm font-semibold transition ${
                  activeTab === "binance"
                    ? "bg-slate-700 text-emerald-400 border-b-2 border-emerald-400"
                    : "text-slate-400 hover:text-white hover:bg-slate-700/50"
                }`}
              >
                Binance Fetch
              </button>
              <button
                onClick={() => setActiveTab("csv")}
                className={`flex-1 py-3 text-sm font-semibold transition ${
                  activeTab === "csv"
                    ? "bg-slate-700 text-emerald-400 border-b-2 border-emerald-400"
                    : "text-slate-400 hover:text-white hover:bg-slate-700/50"
                }`}
              >
                CSV Upload
              </button>
            </div>

            <div className="p-6">
              {activeTab === "binance" ? (
                <BinanceImportForm onSuccess={handleImportSuccess} />
              ) : (
                <CSVUploadForm onSuccess={handleImportSuccess} />
              )}
            </div>
          </div>

          <div className="space-y-4 lg:col-span-2">
            <h2 className="font-semibold text-slate-200 text-xl">
              Local Datasets
            </h2>
            <DatasetTable refreshTrigger={refreshTrigger} />
          </div>
        </div>
      </div>
    </div>
  );
};

export default HistoricalData;
