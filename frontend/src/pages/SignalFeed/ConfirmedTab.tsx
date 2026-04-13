import { CheckCircle } from 'lucide-react';

/**
 * Confirmed tab — placeholder for Phase 5 (Signal Confirmation).
 */
export default function ConfirmedTab() {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-slate-500">
      <CheckCircle size={40} className="mb-3 opacity-30" />
      <p className="text-sm font-medium">Confirmed Signals</p>
      <p className="text-xs mt-1 text-slate-600">
        Coming in Phase 5 — confirmed setups with full entry/exit details will appear here
      </p>
    </div>
  );
}
