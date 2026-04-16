import React, { useEffect, useState } from 'react';
import { Bot, CheckCircle, XCircle, AlertTriangle, ChevronRight, MessageSquareCode } from 'lucide-react';
import { fetchLLMLogs, type LLMPromptLog } from '../../api/client';

const getVerdictIcon = (verdict: string) => {
  switch (verdict?.toUpperCase()) {
    case 'CONFIRM':
    case 'MODIFY':
      return <CheckCircle className="text-emerald-400" size={16} />;
    case 'REJECT':
      return <XCircle className="text-rose-400" size={16} />;
    case 'ERROR':
      return <AlertTriangle className="text-rose-600" size={16} />;
    default:
      return <AlertTriangle className="text-amber-400" size={16} />;
  }
};

const getVerdictColor = (verdict: string) => {
  switch (verdict?.toUpperCase()) {
    case 'CONFIRM':
    case 'MODIFY':
      return 'text-emerald-400';
    case 'REJECT':
      return 'text-rose-400';
    case 'ERROR':
      return 'text-rose-600';
    default:
      return 'text-amber-400';
  }
};

const LLMPrompts: React.FC = () => {
  const [logs, setLogs] = useState<LLMPromptLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  const [selectedLog, setSelectedLog] = useState<LLMPromptLog | null>(null);
  
  // Pagination
  const [page, setPage] = useState(0);
  const [totalLogs, setTotalLogs] = useState(0);
  const pageSize = 50;

  const loadLogs = async (currentPage: number) => {
    setLoading(true);
    try {
      const data = await fetchLLMLogs(pageSize, currentPage * pageSize);
      setLogs(data.logs);
      setTotalLogs(data.total);
      if (data.logs.length > 0 && !selectedLog) {
        setSelectedLog(data.logs[0]);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to fetch LLM logs');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadLogs(page);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page]);

  const totalPages = Math.ceil(totalLogs / pageSize);

  return (
    <div className="flex flex-col h-full bg-slate-900 border-l border-slate-800">
      <div className="flex items-center justify-between p-4 border-b border-slate-700 bg-slate-800/50">
        <div className="flex items-center space-x-2">
          <Bot className="text-blue-400" size={24} />
          <h1 className="text-xl font-bold text-white">LLM Logs & Prompts</h1>
        </div>
        
        <div className="text-sm border border-slate-700 bg-slate-800 px-3 py-1 rounded-full text-slate-300">
          Showing {page * pageSize + 1}-{Math.min((page + 1) * pageSize, totalLogs)} of {totalLogs}
        </div>
      </div>

      {loading && logs.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-slate-400">Loading DB records...</div>
      ) : error ? (
        <div className="flex-1 flex items-center justify-center text-rose-400 p-8 text-center">{error}</div>
      ) : logs.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-slate-500">No prompt logs found.</div>
      ) : (
        <div className="flex flex-1 overflow-hidden">
          {/* Master List (Sidebar) */}
          <div className="w-1/3 border-r border-slate-700 bg-slate-800/30 flex flex-col overflow-hidden">
            <div className="flex-1 overflow-y-auto p-4 space-y-2">
              {logs.map((log) => (
                <button
                  key={log.id}
                  onClick={() => setSelectedLog(log)}
                  className={`w-full flex items-center p-3 rounded-lg border text-left transition-colors ${
                    selectedLog?.id === log.id 
                      ? 'bg-slate-700 border-blue-500' 
                      : 'bg-slate-800 border-slate-700 hover:border-slate-500 hover:bg-slate-700/50'
                  }`}
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-bold text-white truncate">{log.symbol}</span>
                      <span className="text-xs text-slate-400 whitespace-nowrap">
                        {new Date(log.created_at).toLocaleTimeString()}
                      </span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-slate-400 truncate pr-2 max-w-[60%]">
                        {log.strategy_name}
                      </span>
                      <div className="flex items-center space-x-1 whitespace-nowrap">
                        {getVerdictIcon(log.parsed_verdict)}
                        <span className={`text-xs font-medium ${getVerdictColor(log.parsed_verdict)}`}>
                          {log.parsed_verdict}
                        </span>
                      </div>
                    </div>
                  </div>
                  <ChevronRight size={16} className="ml-2 text-slate-500 flex-shrink-0" />
                </button>
              ))}
            </div>
            
            {/* Pagination Controls */}
            <div className="p-4 border-t border-slate-700 bg-slate-800 flex items-center justify-between">
              <button 
                onClick={() => setPage(Math.max(0, page - 1))}
                disabled={page === 0}
                className="px-3 py-1 bg-slate-700 text-white rounded disabled:opacity-50 hover:bg-slate-600 transition text-sm"
              >
                Previous
              </button>
              <span className="text-sm text-slate-400">
                Page {page + 1} of {Math.max(1, totalPages)}
              </span>
              <button 
                onClick={() => setPage(Math.min(totalPages - 1, page + 1))}
                disabled={page >= totalPages - 1}
                className="px-3 py-1 bg-slate-700 text-white rounded disabled:opacity-50 hover:bg-slate-600 transition text-sm"
              >
                Next
              </button>
            </div>
          </div>

          {/* Detail View (Main Area) */}
          <div className="flex-1 bg-slate-900 overflow-y-auto">
            {selectedLog ? (
              <div className="p-6 space-y-6">
                
                {/* Meta Header */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 bg-slate-800/50 p-4 rounded-xl border border-slate-700">
                  <div>
                    <div className="text-xs text-slate-400 mb-1">Time</div>
                    <div className="text-sm text-white font-medium">
                      {new Date(selectedLog.created_at).toLocaleString()}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-slate-400 mb-1">Strategy</div>
                    <div className="text-sm text-white font-medium truncate" title={selectedLog.strategy_name}>
                      {selectedLog.strategy_name}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-slate-400 mb-1">Model</div>
                    <div className="text-sm text-white font-medium truncate" title={selectedLog.model_name}>
                      {selectedLog.model_name || 'Unknown'}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-slate-400 mb-1">Final Verdict</div>
                    <div className={`text-sm font-bold flex items-center ${getVerdictColor(selectedLog.parsed_verdict)}`}>
                      <span className="mr-2">{selectedLog.parsed_verdict}</span>
                      {getVerdictIcon(selectedLog.parsed_verdict)}
                    </div>
                  </div>
                </div>

                <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
                  {/* Prompt Text */}
                  <div className="flex flex-col border border-slate-700 rounded-xl overflow-hidden bg-slate-950 max-h-[800px]">
                    <div className="flex items-center px-4 py-3 border-b border-slate-800 bg-slate-900 shadow-sm">
                      <MessageSquareCode className="text-blue-400 mr-2" size={16} />
                      <h3 className="text-sm font-semibold text-white">System Prompt & Context</h3>
                    </div>
                    {/* Using pre allows us to maintain whitespace the LLM sees */}
                    <div className="overflow-auto bg-slate-950 p-4">
                      <pre className="text-xs font-mono text-slate-300 whitespace-pre-wrap leading-relaxed">
                        {selectedLog.prompt_text}
                      </pre>
                    </div>
                  </div>

                  {/* Response Text */}
                  <div className="flex flex-col border border-slate-700 rounded-xl overflow-hidden bg-slate-900 max-h-[800px]">
                    <div className="flex items-center px-4 py-3 border-b border-slate-800 bg-slate-900 shadow-sm">
                      <Bot className="text-emerald-400 mr-2" size={16} />
                      <h3 className="text-sm font-semibold text-white">Raw Model Response</h3>
                    </div>
                    <div className="overflow-auto bg-[#0d1117] p-4">
                      <pre className="text-xs font-mono text-slate-300 whitespace-pre-wrap leading-relaxed">
                        {selectedLog.response_text || 'No response recorded (Call failed)'}
                      </pre>
                    </div>
                  </div>
                </div>

              </div>
            ) : (
              <div className="h-full flex flex-col items-center justify-center text-slate-500">
                <Bot size={48} className="mb-4 opacity-50" />
                <p>Select a log to view prompt & response traces.</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default LLMPrompts;
