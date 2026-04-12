import { BrowserRouter as Router, Routes, Route, Link } from 'react-router-dom';
import HistoricalData from './pages/HistoricalData/HistoricalData';
import { LineChart, LayoutDashboard, History } from 'lucide-react';

function App() {
  return (
    <Router>
      <div className="flex h-screen bg-slate-900 text-white">
        {/* Sidebar */}
        <aside className="w-64 bg-slate-800 border-r border-slate-700 flex flex-col">
          <div className="p-4 text-xl font-bold border-b border-slate-700 text-emerald-400">
            Crypto Signals
          </div>
          <nav className="flex-1 p-4 space-y-2">
            <Link to="/signal-feed" className="flex items-center space-x-3 text-slate-300 hover:text-white p-2 rounded-lg hover:bg-slate-700 transition">
              <LayoutDashboard size={20} />
              <span>Signal Feed</span>
            </Link>
            <Link to="/backtest" className="flex items-center space-x-3 text-slate-300 hover:text-white p-2 rounded-lg hover:bg-slate-700 transition">
              <LineChart size={20} />
              <span>Backtest Engine</span>
            </Link>
            <Link to="/" className="flex items-center space-x-3 text-emerald-400 p-2 rounded-lg bg-slate-700/50 transition border border-slate-600">
              <History size={20} />
              <span>Historical Data</span>
            </Link>
          </nav>
        </aside>

        {/* Main Content */}
        <main className="flex-1 overflow-auto bg-slate-900">
          <Routes>
            <Route path="/" element={<HistoricalData />} />
            {/* Future Routes */}
            <Route path="/signal-feed" element={<div className="p-8">Signal Feed (WIP)</div>} />
            <Route path="/backtest" element={<div className="p-8">Backtest (WIP)</div>} />
          </Routes>
        </main>
      </div>
    </Router>
  );
}

export default App;
