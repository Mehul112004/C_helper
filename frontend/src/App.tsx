import { BrowserRouter as Router, Routes, Route, Link, useLocation } from 'react-router-dom';
import HistoricalData from './pages/HistoricalData/HistoricalData';
import SignalFeed from './pages/SignalFeed/SignalFeed';
import { LineChart, LayoutDashboard, History } from 'lucide-react';

function NavLink({ to, icon: Icon, label }: { to: string; icon: React.ElementType; label: string }) {
  const location = useLocation();
  const isActive = location.pathname === to;

  return (
    <Link
      to={to}
      className={`flex items-center space-x-3 p-2 rounded-lg transition ${
        isActive
          ? 'text-emerald-400 bg-slate-700/50 border border-slate-600'
          : 'text-slate-300 hover:text-white hover:bg-slate-700'
      }`}
    >
      <Icon size={20} />
      <span>{label}</span>
    </Link>
  );
}

function AppLayout() {
  return (
    <div className="flex h-screen bg-slate-900 text-white">
      {/* Sidebar */}
      <aside className="w-64 bg-slate-800 border-r border-slate-700 flex flex-col">
        <div className="p-4 text-xl font-bold border-b border-slate-700 text-emerald-400">
          Crypto Signals
        </div>
        <nav className="flex-1 p-4 space-y-2">
          <NavLink to="/signal-feed" icon={LayoutDashboard} label="Signal Feed" />
          <NavLink to="/backtest" icon={LineChart} label="Backtest Engine" />
          <NavLink to="/" icon={History} label="Historical Data" />
        </nav>
      </aside>

      {/* Main Content */}
      <main className="flex-1 overflow-auto bg-slate-900">
        <Routes>
          <Route path="/" element={<HistoricalData />} />
          <Route path="/signal-feed" element={<SignalFeed />} />
          <Route path="/backtest" element={<div className="p-8">Backtest (WIP)</div>} />
        </Routes>
      </main>
    </div>
  );
}

function App() {
  return (
    <Router>
      <AppLayout />
    </Router>
  );
}

export default App;
