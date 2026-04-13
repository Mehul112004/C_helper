import { Eye } from 'lucide-react';
import WatchingCard from '../../components/WatchingCard/WatchingCard';
import type { WatchingSetup } from '../../types/signals';

interface WatchingTabProps {
  setups: WatchingSetup[];
}

/**
 * Watching tab — displays all active watching cards in a responsive grid.
 */
export default function WatchingTab({ setups }: WatchingTabProps) {
  const activeSetups = setups.filter((s) => s.status === 'WATCHING');

  if (activeSetups.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-slate-500">
        <Eye size={40} className="mb-3 opacity-30" />
        <p className="text-sm font-medium">No setups being watched</p>
        <p className="text-xs mt-1 text-slate-600">
          Start an analysis session and setups will appear here when strategies detect signals
        </p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
      {activeSetups.map((setup) => (
        <WatchingCard key={setup.id} setup={setup} />
      ))}
    </div>
  );
}
