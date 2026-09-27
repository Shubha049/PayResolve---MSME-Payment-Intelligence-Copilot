import React, { useEffect, useState, useCallback } from 'react';
import { Plus, Filter, Trash2, Pencil, X, AlertCircle, Briefcase } from 'lucide-react';
import { Link } from 'react-router-dom';
import { casesAPI, invoicesAPI, customersAPI } from '../api/endpoints';
import RiskBadge from '../components/RiskBadge';

interface Customer { id: string; name: string; }
interface Invoice  { id: string; invoice_number: string; }
interface Case {
  id: string; case_number: string; title: string; status: string;
  priority: string; customer_name?: string; summary?: string;
  invoice_id?: string; // Added to support risk badge
}

const STATUSES  = ['OPEN', 'IN_PROGRESS', 'PENDING_INFO', 'RESOLVED', 'CLOSED'];
const PRIORITIES = ['LOW', 'MEDIUM', 'HIGH'];

function badge(value: string) {
  const map: Record<string, string> = {
    OPEN: 'badge-blue', IN_PROGRESS: 'badge-yellow', PENDING_INFO: 'badge-purple',
    RESOLVED: 'badge-green', CLOSED: 'badge-gray',
    LOW: 'badge-gray', MEDIUM: 'badge-yellow', HIGH: 'badge-red',
  };
  return map[value] ?? 'badge-gray';
}

export default function CasesPage() {
  const [cases, setCases]           = useState<Case[]>([]);
  const [customers, setCustomers]   = useState<Customer[]>([]);
  const [invoices, setInvoices]     = useState<Invoice[]>([]);
  const [loading, setLoading]       = useState(true);
  const [error, setError]           = useState('');
  const [statusFilter, setStatus]   = useState('');
  const [priorityFilter, setPriority] = useState('');

  // Modals
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing]       = useState<Case | null>(null);
  const [deleteId, setDeleteId]     = useState<string | null>(null);
  const [form, setForm] = useState({
    customer_id: '', invoice_id: '', case_number: '', title: '',
    status: 'OPEN', priority: 'MEDIUM', summary: '',
  });
  const [saving, setSaving]   = useState(false);
  const [formError, setFormError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [caseRes, custRes, invRes] = await Promise.all([
        casesAPI.list({ status: statusFilter || undefined, priority: priorityFilter || undefined }),
        customersAPI.list(),
        invoicesAPI.list(),
      ]);
      setCases(caseRes.data?.items ?? caseRes.data ?? []);
      setCustomers(custRes.data?.items ?? custRes.data ?? []);
      setInvoices(invRes.data?.items ?? invRes.data ?? []);
    } catch { setError('Failed to load cases.'); }
    finally { setLoading(false); }
  }, [statusFilter, priorityFilter]);

  useEffect(() => { load(); }, [load]);

  function openCreate() {
    setEditing(null);
    setForm({ customer_id: '', invoice_id: '', case_number: '', title: '', status: 'OPEN', priority: 'MEDIUM', summary: '' });
    setFormError(''); setShowCreate(true);
  }
  function openEdit(c: Case) {
    setEditing(c);
    setForm({ customer_id: '', invoice_id: '', case_number: c.case_number, title: c.title, status: c.status, priority: c.priority, summary: c.summary ?? '' });
    setFormError(''); setShowCreate(true);
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault(); setFormError(''); setSaving(true);
    try {
      if (editing) {
        await casesAPI.update(editing.id, { status: form.status, priority: form.priority, summary: form.summary || undefined });
      } else {
        await casesAPI.create({
          customer_id: form.customer_id, case_number: form.case_number, title: form.title,
          invoice_id: form.invoice_id || undefined, status: form.status, priority: form.priority,
          summary: form.summary || undefined,
        });
      }
      setShowCreate(false); load();
    } catch (err: unknown) {
      setFormError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Save failed.');
    } finally { setSaving(false); }
  }

  async function handleDelete(id: string) {
    try { await casesAPI.delete(id); load(); } catch { setError('Delete failed.'); }
    setDeleteId(null);
  }

  return (
    <div className="space-y-5 animate-fade-in">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-surface-50">Cases</h1>
          <p className="text-surface-400 text-sm">{cases.length} case{cases.length !== 1 ? 's' : ''}</p>
        </div>
        <button id="create-case-btn" onClick={openCreate} className="btn-primary">
          <Plus size={15} /> New Case
        </button>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <Filter size={14} className="text-surface-400" />
        <span className="text-xs text-surface-500">Status:</span>
        {['', ...STATUSES].map(s => (
          <button key={s} onClick={() => setStatus(s)}
            className={`text-xs px-3 py-1.5 rounded-full border transition-colors ${statusFilter === s ? 'bg-brand-500/20 border-brand-500/50 text-brand-400' : 'bg-surface-800 border-surface-700 text-surface-400 hover:text-surface-200'}`}>
            {s || 'All'}
          </button>
        ))}
        <span className="text-xs text-surface-500 ml-2">Priority:</span>
        {['', ...PRIORITIES].map(p => (
          <button key={p} onClick={() => setPriority(p)}
            className={`text-xs px-3 py-1.5 rounded-full border transition-colors ${priorityFilter === p ? 'bg-brand-500/20 border-brand-500/50 text-brand-400' : 'bg-surface-800 border-surface-700 text-surface-400 hover:text-surface-200'}`}>
            {p || 'All'}
          </button>
        ))}
      </div>

      {error && <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">{error}</div>}

      <div className="card !p-0 overflow-hidden">
        {loading ? (
          <div className="flex items-center justify-center h-40">
            <div className="w-7 h-7 border-2 border-brand-500 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : cases.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-surface-500">
            <Briefcase size={36} className="mb-3 opacity-30" />
            <p className="font-medium">No cases found</p>
          </div>
        ) : (
          <table className="table-base">
            <thead>
              <tr>
                <th>Case #</th><th>Title</th><th>Customer</th><th>Priority</th><th>Status</th><th>Risk</th><th className="text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {cases.map(c => (
                <tr key={c.id}>
                    <td><Link to={`/cases/${c.id}`} className="font-mono text-xs text-brand-400 hover:text-brand-300">{c.case_number}</Link></td>
                  <td className="max-w-[200px] truncate font-medium text-surface-100">{c.title}</td>
                  <td className="text-surface-300">{c.customer_name || '—'}</td>
                  <td><span className={badge(c.priority)}>{c.priority}</span></td>
                  <td><span className={badge(c.status)}>{c.status}</span></td>
                  <td>
                    {c.invoice_id ? (
                      <RiskBadge invoiceId={c.invoice_id} inline />
                    ) : (
                      <span className="text-xs text-surface-500">—</span>
                    )}
                  </td>
                  <td className="text-right">
                    <div className="flex items-center justify-end gap-2">
                      <button onClick={() => openEdit(c)} className="p-1.5 rounded-lg hover:bg-surface-700 text-surface-400 hover:text-surface-100 transition-colors"><Pencil size={13} /></button>
                      <button onClick={() => setDeleteId(c.id)} className="p-1.5 rounded-lg hover:bg-red-500/10 text-surface-400 hover:text-red-400 transition-colors"><Trash2 size={13} /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Create/Edit Modal */}
      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={() => setShowCreate(false)} />
          <div className="relative bg-surface-800 border border-surface-700 rounded-2xl w-full max-w-lg shadow-2xl animate-slide-up max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between p-6 border-b border-surface-700 sticky top-0 bg-surface-800 z-10">
              <h2 className="font-semibold text-surface-100">{editing ? 'Update Case' : 'New Case'}</h2>
              <button onClick={() => setShowCreate(false)} className="text-surface-400 hover:text-surface-100"><X size={18} /></button>
            </div>
            <form onSubmit={handleSave} className="p-6 space-y-4">
              {formError && (
                <div className="flex items-center gap-2 p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
                  <AlertCircle size={14} /> {formError}
                </div>
              )}
              {!editing && (
                <>
                  <div>
                    <label htmlFor="case-customer" className="label">Customer <span className="text-red-400">*</span></label>
                    <select id="case-customer" required value={form.customer_id} onChange={e => setForm(p => ({ ...p, customer_id: e.target.value }))} className="input">
                      <option value="">Select customer…</option>
                      {customers.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                    </select>
                  </div>
                  <div>
                    <label htmlFor="case-invoice" className="label">Linked Invoice (optional)</label>
                    <select id="case-invoice" value={form.invoice_id} onChange={e => setForm(p => ({ ...p, invoice_id: e.target.value }))} className="input">
                      <option value="">None</option>
                      {invoices.map(i => <option key={i.id} value={i.id}>{i.invoice_number}</option>)}
                    </select>
                  </div>
                  <div>
                    <label htmlFor="case-num" className="label">Case Number <span className="text-red-400">*</span></label>
                    <input id="case-num" required value={form.case_number} onChange={e => setForm(p => ({ ...p, case_number: e.target.value }))} className="input" placeholder="CASE-001" />
                  </div>
                  <div>
                    <label htmlFor="case-title" className="label">Title <span className="text-red-400">*</span></label>
                    <input id="case-title" required value={form.title} onChange={e => setForm(p => ({ ...p, title: e.target.value }))} className="input" placeholder="Overdue payment — Invoice #INV-101" />
                  </div>
                </>
              )}
              <div>
                <label htmlFor="case-status" className="label">Status</label>
                <select id="case-status" value={form.status} onChange={e => setForm(p => ({ ...p, status: e.target.value }))} className="input">
                  {STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div>
                <label htmlFor="case-priority" className="label">Priority</label>
                <select id="case-priority" value={form.priority} onChange={e => setForm(p => ({ ...p, priority: e.target.value }))} className="input">
                  {PRIORITIES.map(p => <option key={p} value={p}>{p}</option>)}
                </select>
              </div>
              <div>
                <label htmlFor="case-summary" className="label">Summary</label>
                <textarea id="case-summary" rows={3} value={form.summary} onChange={e => setForm(p => ({ ...p, summary: e.target.value }))} className="input resize-none" placeholder="Describe the case…" />
              </div>
              <div className="flex gap-3 pt-2">
                <button type="button" onClick={() => setShowCreate(false)} className="btn-secondary flex-1 justify-center">Cancel</button>
                <button id="save-case-btn" type="submit" disabled={saving} className="btn-primary flex-1 justify-center">
                  {saving ? 'Saving…' : editing ? 'Update Case' : 'Create Case'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Delete Confirm */}
      {deleteId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={() => setDeleteId(null)} />
          <div className="relative bg-surface-800 border border-surface-700 rounded-2xl w-full max-w-sm p-6 shadow-2xl animate-slide-up">
            <h2 className="font-semibold text-surface-100 mb-2">Delete Case?</h2>
            <p className="text-surface-400 text-sm mb-5">This action cannot be undone.</p>
            <div className="flex gap-3">
              <button onClick={() => setDeleteId(null)} className="btn-secondary flex-1 justify-center">Cancel</button>
              <button onClick={() => handleDelete(deleteId)} className="btn-danger flex-1 justify-center">Delete</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
