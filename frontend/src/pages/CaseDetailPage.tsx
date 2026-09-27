import { useEffect, useState, type FormEvent } from 'react';
import { ArrowLeft, CalendarClock, CircleAlert, MessageSquare, Plus, Send, ShieldAlert } from 'lucide-react';
import { Link, useParams } from 'react-router-dom';
import { casesAPI, copilotAPI, promisesAPI, recoveryActionsAPI, riskAPI } from '../api/endpoints';

interface CaseRecord { id: string; case_number: string; title: string; status: string; priority: string; summary?: string; amount_in_recovery?: string; expected_payment_date?: string; last_contact_date?: string; next_follow_up_date?: string; invoice?: { invoice_number: string; total_amount: string; paid_amount: string; outstanding_amount: string; status: string }; customer?: { name: string; email?: string }; }
interface Action { id: string; action_type: string; action_date: string; notes?: string; next_follow_up_date?: string; }
interface PromiseRecord { id: string; promise_date: string; promised_amount: string; status: string; notes?: string; }
interface TimelineItem { id: string; action: string; entity_type: string; timestamp: string; details?: Record<string, unknown>; }

const actionTypes = ['CUSTOMER_CONTACTED', 'EMAIL_SENT', 'REMINDER_SENT', 'FOLLOW_UP_SCHEDULED', 'PAYMENT_DISCUSSED', 'PROMISE_REQUESTED', 'EVIDENCE_COLLECTED', 'NOTE_ADDED', 'STATUS_REVIEWED'];
const badge = (value: string) => value === 'HIGH' || value === 'BROKEN' ? 'badge-red' : value === 'RESOLVED' || value === 'FULFILLED' ? 'badge-green' : value === 'MEDIUM' || value === 'PENDING' ? 'badge-yellow' : 'badge-blue';

export default function CaseDetailPage() {
  const { caseId = '' } = useParams();
  const [record, setRecord] = useState<CaseRecord | null>(null);
  const [actions, setActions] = useState<Action[]>([]);
  const [promises, setPromises] = useState<PromiseRecord[]>([]);
  const [timeline, setTimeline] = useState<TimelineItem[]>([]);
  const [risk, setRisk] = useState<{ risk_score: number; risk_category: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showAction, setShowAction] = useState(false);
  const [actionForm, setActionForm] = useState({ action_type: 'NOTE_ADDED', action_date: new Date().toISOString().split('T')[0], notes: '', next_follow_up_date: '' });
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState('');
  const [asking, setAsking] = useState(false);

  async function load() {
    setLoading(true); setError('');
    try {
      const [caseRes, actionRes, promiseRes, timelineRes] = await Promise.all([
        casesAPI.get(caseId), recoveryActionsAPI.list(caseId), promisesAPI.list(caseId), recoveryActionsAPI.timeline(caseId),
      ]);
      setRecord(caseRes.data); setActions(actionRes.data.actions ?? []); setPromises(promiseRes.data.promises ?? []); setTimeline(timelineRes.data ?? []);
      if (caseRes.data.invoice_id) {
        try { const riskRes = await riskAPI.getInvoiceRisk(caseRes.data.invoice_id); setRisk(riskRes.data); } catch { setRisk(null); }
      }
    } catch { setError('This case could not be loaded. It may not be available in the active organization.'); }
    finally { setLoading(false); }
  }

  useEffect(() => { if (caseId) load(); }, [caseId]);

  async function saveAction(event: FormEvent) {
    event.preventDefault();
    try {
      await recoveryActionsAPI.create(caseId, { ...actionForm, next_follow_up_date: actionForm.next_follow_up_date || undefined });
      setShowAction(false); setActionForm(current => ({ ...current, notes: '', next_follow_up_date: '' })); load();
    } catch { setError('Recovery action could not be saved.'); }
  }

  async function askCopilot(event: FormEvent) {
    event.preventDefault(); if (!question.trim()) return;
    setAsking(true); setAnswer('');
    try { const response = await copilotAPI.query({ query: question, case_id: caseId }); setAnswer(response.data.answer); }
    catch { setAnswer('Copilot is unavailable right now.'); }
    finally { setAsking(false); }
  }

  if (loading) return <div className="flex items-center justify-center h-64"><div className="w-8 h-8 border-2 border-brand-500 border-t-transparent rounded-full animate-spin" /></div>;
  if (!record) return <div className="space-y-4"><Link to="/cases" className="text-brand-400 text-sm flex items-center gap-2"><ArrowLeft size={14} /> Back to cases</Link><div className="card text-red-400">{error || 'Case not found.'}</div></div>;

  return (
    <div className="space-y-5 animate-fade-in">
      <Link to="/cases" className="text-surface-400 hover:text-surface-100 text-sm flex items-center gap-2"><ArrowLeft size={14} /> Back to cases</Link>
      {error && <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">{error}</div>}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div><div className="text-xs text-brand-400 font-mono mb-1">{record.case_number}</div><h1 className="text-2xl font-bold text-surface-50">{record.title}</h1><p className="text-surface-400 text-sm mt-1">{record.customer?.name ?? 'Customer unavailable'} {record.customer?.email ? `· ${record.customer.email}` : ''}</p></div>
        <div className="flex items-center gap-2"><span className={badge(record.priority)}>{record.priority}</span><span className={badge(record.status)}>{record.status}</span><button onClick={() => setShowAction(true)} className="btn-primary"><Plus size={15} /> Log action</button></div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <div className="lg:col-span-2 space-y-5">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[['In recovery', record.amount_in_recovery ?? '0'], ['Outstanding', record.invoice?.outstanding_amount ?? '0'], ['Next follow-up', record.next_follow_up_date ?? 'Not set'], ['Last contact', record.last_contact_date ?? 'Not recorded']].map(([label, value]) => <div key={label} className="card !p-4"><div className="text-xs text-surface-500">{label}</div><div className="text-sm font-semibold text-surface-100 mt-2 truncate">{value}</div></div>)}
          </div>
          <div className="card"><div className="flex items-center justify-between mb-4"><h2 className="font-semibold text-surface-100 flex items-center gap-2"><CalendarClock size={16} className="text-brand-400" /> Timeline</h2></div>{timeline.length === 0 ? <p className="text-sm text-surface-500">No activity recorded yet.</p> : <div className="space-y-4">{timeline.map(item => <div key={item.id} className="flex gap-3"><div className="mt-1 w-2 h-2 rounded-full bg-brand-400 shrink-0" /><div><div className="text-sm text-surface-200">{item.action.replaceAll('_', ' ')}</div><div className="text-xs text-surface-500">{item.entity_type} · {new Date(item.timestamp).toLocaleString()}</div></div></div>)}</div>}</div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            <div className="card"><h2 className="font-semibold text-surface-100 mb-4">Recovery actions</h2>{actions.length === 0 ? <p className="text-sm text-surface-500">No actions logged.</p> : <div className="space-y-3">{actions.map(action => <div key={action.id} className="border-b border-surface-700/60 pb-3 last:border-0"><div className="flex justify-between gap-2"><span className="text-xs font-semibold text-brand-400">{action.action_type.replaceAll('_', ' ')}</span><span className="text-xs text-surface-500">{action.action_date}</span></div>{action.notes && <p className="text-sm text-surface-300 mt-1">{action.notes}</p>}</div>)}</div>}</div>
            <div className="card"><h2 className="font-semibold text-surface-100 mb-4">Promises to pay</h2>{promises.length === 0 ? <p className="text-sm text-surface-500">No promises recorded.</p> : <div className="space-y-3">{promises.map(promise => <div key={promise.id} className="flex items-center justify-between border-b border-surface-700/60 pb-3 last:border-0"><div><div className="text-sm text-surface-200">{promise.promised_amount}</div><div className="text-xs text-surface-500">Due {promise.promise_date}</div></div><span className={badge(promise.status)}>{promise.status}</span></div>)}</div>}</div>
          </div>
        </div>
        <div className="space-y-5">
          <div className="card"><h2 className="font-semibold text-surface-100 mb-4 flex items-center gap-2"><ShieldAlert size={16} className="text-amber-400" /> Risk</h2>{risk ? <><div className="text-3xl font-bold text-amber-400">{risk.risk_score.toFixed(0)}</div><div className="text-sm text-surface-400 mt-1">{risk.risk_category}</div></> : <p className="text-sm text-surface-500">No risk assessment available.</p>}</div>
          <div className="card"><h2 className="font-semibold text-surface-100 mb-4 flex items-center gap-2"><MessageSquare size={16} className="text-brand-400" /> Ask about this case</h2><form onSubmit={askCopilot} className="space-y-3"><textarea value={question} onChange={event => setQuestion(event.target.value)} maxLength={2000} rows={3} className="input resize-none" placeholder="What should I follow up on?" /><button disabled={asking || !question.trim()} className="btn-primary w-full justify-center"><Send size={14} /> {asking ? 'Reviewing…' : 'Ask Copilot'}</button></form>{answer && <div className="mt-4 p-3 rounded-lg bg-surface-900 border border-surface-700 text-sm text-surface-300 whitespace-pre-wrap">{answer}</div>}</div>
          <div className="card"><h2 className="font-semibold text-surface-100 mb-3">Case summary</h2><p className="text-sm text-surface-400 leading-6">{record.summary || 'No summary added.'}</p>{record.invoice && <div className="mt-4 pt-4 border-t border-surface-700 text-xs text-surface-500 flex items-center gap-2"><CircleAlert size={13} /> Invoice {record.invoice.invoice_number} · {record.invoice.status}</div>}</div>
        </div>
      </div>

      {showAction && <div className="fixed inset-0 z-50 flex items-center justify-center p-4"><div className="absolute inset-0 bg-black/60" onClick={() => setShowAction(false)} /><form onSubmit={saveAction} className="relative card w-full max-w-md shadow-2xl"><h2 className="font-semibold text-surface-100 mb-4">Log recovery action</h2><div className="space-y-4"><div><label className="label" htmlFor="action-type">Action type</label><select id="action-type" value={actionForm.action_type} onChange={event => setActionForm(current => ({ ...current, action_type: event.target.value }))} className="input">{actionTypes.map(type => <option key={type}>{type}</option>)}</select></div><div><label className="label" htmlFor="action-date">Date</label><input id="action-date" type="date" required value={actionForm.action_date} onChange={event => setActionForm(current => ({ ...current, action_date: event.target.value }))} className="input" /></div><div><label className="label" htmlFor="action-notes">Notes</label><textarea id="action-notes" maxLength={5000} value={actionForm.notes} onChange={event => setActionForm(current => ({ ...current, notes: event.target.value }))} className="input resize-none" rows={3} /></div><div><label className="label" htmlFor="follow-up">Next follow-up</label><input id="follow-up" type="date" value={actionForm.next_follow_up_date} onChange={event => setActionForm(current => ({ ...current, next_follow_up_date: event.target.value }))} className="input" /></div></div><div className="flex gap-3 mt-5"><button type="button" onClick={() => setShowAction(false)} className="btn-secondary flex-1 justify-center">Cancel</button><button type="submit" className="btn-primary flex-1 justify-center">Save action</button></div></form></div>}
    </div>
  );
}
