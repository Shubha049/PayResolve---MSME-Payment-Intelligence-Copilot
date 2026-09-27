import { useState, type FormEvent } from 'react';
import { Bot, Send, ShieldCheck, FileText } from 'lucide-react';
import { copilotAPI } from '../api/endpoints';

interface Message {
  role: 'user' | 'assistant';
  text: string;
  grounded?: boolean;
  sources?: { label: string; value: string }[];
}

export default function CopilotPage() {
  const [query, setQuery] = useState('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function submit(event: FormEvent) {
    event.preventDefault();
    const trimmed = query.trim();
    if (!trimmed || loading) return;
    setMessages(current => [...current, { role: 'user', text: trimmed }]);
    setQuery('');
    setError('');
    setLoading(true);
    try {
      const response = await copilotAPI.recoveryQuery({ query: trimmed });
      const sources = (response.data.sources ?? []).map((source: Record<string, string>) => ({
        label: source.type ?? source.entity_type ?? 'Recovery record',
        value: source.label ?? source.id ?? source.entity_id ?? 'Verified record',
      }));
      setMessages(current => [...current, {
        role: 'assistant',
        text: response.data.answer,
        grounded: response.data.grounded,
        sources,
      }]);
    } catch {
      setError('Copilot is unavailable right now. Your records were not changed.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="max-w-5xl mx-auto space-y-6 animate-fade-in">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-brand-400 text-xs font-semibold uppercase tracking-widest mb-2">
            <Bot size={14} /> Recovery intelligence
          </div>
          <h1 className="text-2xl font-bold text-surface-50">Recovery Copilot</h1>
          <p className="text-surface-400 text-sm mt-1">Ask about your current cases, promises, payments, and follow-ups.</p>
        </div>
        <div className="hidden sm:flex items-center gap-2 text-xs text-surface-400 border border-surface-700 rounded-lg px-3 py-2">
          <ShieldCheck size={14} className="text-brand-400" /> Organization-scoped
        </div>
      </div>

      <div className="card min-h-[480px] flex flex-col">
        <div className="flex-1 space-y-4 overflow-y-auto pr-1">
          {messages.length === 0 && (
            <div className="h-full min-h-[360px] flex flex-col items-center justify-center text-center">
              <div className="w-14 h-14 rounded-2xl bg-brand-500/10 border border-brand-500/20 flex items-center justify-center mb-4">
                <Bot size={26} className="text-brand-400" />
              </div>
              <h2 className="text-lg font-semibold text-surface-100">A grounded view of recovery</h2>
              <p className="text-sm text-surface-500 max-w-md mt-2">Try “Which promises are due this week?” or “What follow-ups need attention?” Answers only use your organization’s verified records.</p>
            </div>
          )}
          {messages.map((message, index) => (
            <div key={`${message.role}-${index}`} className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[85%] rounded-2xl px-4 py-3 ${message.role === 'user' ? 'bg-brand-500 text-white' : 'bg-surface-900 border border-surface-700 text-surface-200'}`}>
                <p className="text-sm leading-6 whitespace-pre-wrap">{message.text}</p>
                {message.role === 'assistant' && (
                  <div className="mt-3 pt-3 border-t border-surface-700/70">
                    <div className="flex items-center gap-2 text-[11px] text-surface-500">
                      <ShieldCheck size={12} className={message.grounded ? 'text-brand-400' : 'text-amber-400'} />
                      {message.grounded ? 'Grounded in verified organization records' : 'Insufficient verified evidence'}
                    </div>
                    {message.sources && message.sources.length > 0 && (
                      <div className="mt-2 space-y-1">
                        {message.sources.map(source => <div key={`${source.label}-${source.value}`} className="flex items-center gap-2 text-xs text-surface-400"><FileText size={11} /> {source.label}: {source.value}</div>)}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          ))}
          {loading && <div className="text-xs text-surface-500 flex items-center gap-2"><span className="w-2 h-2 rounded-full bg-brand-400 animate-pulse" /> Reviewing verified recovery records…</div>}
        </div>

        {error && <div className="mt-4 p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">{error}</div>}
        <form onSubmit={submit} className="mt-5 flex gap-2">
          <input value={query} onChange={event => setQuery(event.target.value)} maxLength={2000} className="input" placeholder="Ask a recovery question…" aria-label="Recovery Copilot question" />
          <button type="submit" disabled={!query.trim() || loading} className="btn-primary px-3" aria-label="Ask Copilot" title="Ask Copilot"><Send size={16} /></button>
        </form>
      </div>
    </div>
  );
}
