import React, { useEffect, useState, useCallback } from 'react';
import { Plus, Filter, Trash2, Pencil, X, AlertCircle, FileText } from 'lucide-react';
import { invoicesAPI, customersAPI, paymentsAPI } from '../api/endpoints';
import RiskBadge from '../components/RiskBadge';

interface Customer { id: string; name: string; }
interface Invoice {
  id: string; invoice_number: string; customer_name: string; customer_id: string;
  issue_date: string; due_date: string; total_amount: string;
  paid_amount: string; outstanding_amount: string; status: string; currency: string;
}

type StatusFilter = '' | 'PENDING' | 'OVERDUE' | 'PAID' | 'PARTIALLY_PAID' | 'DISPUTED' | 'CANCELLED';

function statusBadge(status: string) {
  const map: Record<string, string> = {
    PAID: 'badge-green', PENDING: 'badge-yellow', OVERDUE: 'badge-red',
    PARTIALLY_PAID: 'badge-blue', DISPUTED: 'badge-purple', CANCELLED: 'badge-gray',
  };
  return map[status] ?? 'badge-gray';
}

function fmt(n: string | number) {
  return parseFloat(String(n)).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export default function InvoicesPage() {
  const [invoices, setInvoices]     = useState<Invoice[]>([]);
  const [customers, setCustomers]   = useState<Customer[]>([]);
  const [loading, setLoading]       = useState(true);
  const [error, setError]           = useState('');
  const [statusFilter, setStatus]   = useState<StatusFilter>('');
  const [overdueOnly, setOverdue]   = useState(false);

  // Modal
  const [showCreate, setShowCreate] = useState(false);
  const [showPay, setShowPay]       = useState<Invoice | null>(null);
  const [deleteId, setDeleteId]     = useState<string | null>(null);
  const [form, setForm] = useState({
    customer_id: '', invoice_number: '', issue_date: '', due_date: '',
    total_amount: '', paid_amount: '0', currency: 'INR', notes: '',
  });
  const [payAmount, setPayAmount]   = useState('');
  const [payReference, setPayReference] = useState('');
  const [saving, setSaving]         = useState(false);
  const [formError, setFormError]   = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [invRes, custRes] = await Promise.all([
        invoicesAPI.list({ status: statusFilter || undefined, is_overdue: overdueOnly || undefined }),
        customersAPI.list(),
      ]);
      setInvoices(invRes.data?.items ?? invRes.data ?? []);
      setCustomers(custRes.data?.items ?? custRes.data ?? []);
    } catch { setError('Failed to load invoices.'); }
    finally { setLoading(false); }
  }, [statusFilter, overdueOnly]);

  useEffect(() => { load(); }, [load]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault(); setFormError(''); setSaving(true);
    try {
      await invoicesAPI.create({ ...form });
      setShowCreate(false); load();
    } catch (err: unknown) {
      setFormError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Create failed.');
    } finally { setSaving(false); }
  }

  async function handlePay(e: React.FormEvent) {
    e.preventDefault(); if (!showPay) return; setSaving(true);
    try {
      await paymentsAPI.create({ invoice_id: showPay.id, amount: payAmount, payment_date: new Date().toISOString().split('T')[0], reference: payReference || undefined });
      setShowPay(null); load();
    } catch (err: unknown) {
      setFormError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Update failed.');
    } finally { setSaving(false); }
  }

  async function handleDelete(id: string) {
    try { await invoicesAPI.delete(id); load(); } catch { setError('Delete failed.'); }
    setDeleteId(null);
  }

  const today = new Date().toISOString().split('T')[0];

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-surface-50">Invoices</h1>
          <p className="text-surface-400 text-sm">{invoices.length} invoice{invoices.length !== 1 ? 's' : ''}</p>
        </div>
        <button id="create-invoice-btn" onClick={() => { setForm({ customer_id: '', invoice_number: '', issue_date: today, due_date: '', total_amount: '', paid_amount: '0', currency: 'INR', notes: '' }); setFormError(''); setShowCreate(true); }} className="btn-primary">
          <Plus size={15} /> New Invoice
        </button>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <Filter size={14} className="text-surface-400" />
        {(['', 'PENDING', 'OVERDUE', 'PARTIALLY_PAID', 'PAID', 'DISPUTED', 'CANCELLED'] as StatusFilter[]).map(s => (
          <button
            key={s}
            onClick={() => setStatus(s)}
            className={`text-xs px-3 py-1.5 rounded-full border transition-colors ${statusFilter === s ? 'bg-brand-500/20 border-brand-500/50 text-brand-400' : 'bg-surface-800 border-surface-700 text-surface-400 hover:text-surface-200'}`}
          >
            {s || 'All'}
          </button>
        ))}
        <button
          onClick={() => setOverdue(p => !p)}
          className={`text-xs px-3 py-1.5 rounded-full border transition-colors ml-auto ${overdueOnly ? 'bg-red-500/20 border-red-500/50 text-red-400' : 'bg-surface-800 border-surface-700 text-surface-400'}`}
        >
          Overdue Only
        </button>
      </div>

      {error && <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">{error}</div>}

      {/* Table */}
      <div className="card !p-0 overflow-hidden">
        {loading ? (
          <div className="flex items-center justify-center h-40">
            <div className="w-7 h-7 border-2 border-brand-500 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : invoices.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-surface-500">
            <FileText size={36} className="mb-3 opacity-30" />
            <p className="font-medium">No invoices found</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="table-base">
              <thead>
                <tr>
                  <th>Invoice #</th><th>Customer</th><th>Due Date</th>
                  <th>Total</th><th>Outstanding</th><th>Status</th><th>Risk</th><th className="text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {invoices.map(inv => (
                  <tr key={inv.id}>
                    <td className="font-mono text-xs text-surface-100">{inv.invoice_number}</td>
                    <td>{inv.customer_name || '—'}</td>
                    <td className={inv.status === 'OVERDUE' ? 'text-red-400 font-medium' : ''}>{inv.due_date}</td>
                    <td>{inv.currency} {fmt(inv.total_amount)}</td>
                    <td className="font-semibold text-amber-400">{fmt(inv.outstanding_amount)}</td>
                    <td><span className={statusBadge(inv.status)}>{inv.status}</span></td>
                    <td><RiskBadge invoiceId={inv.id} inline /></td>
                    <td className="text-right">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          onClick={() => { setPayAmount(''); setPayReference(''); setFormError(''); setShowPay(inv); }}
                          className="p-1.5 rounded-lg hover:bg-surface-700 text-surface-400 hover:text-brand-400 transition-colors"
                          title="Record payment"
                        ><Pencil size={13} /></button>
                        <button
                          onClick={() => setDeleteId(inv.id)}
                          className="p-1.5 rounded-lg hover:bg-red-500/10 text-surface-400 hover:text-red-400 transition-colors"
                        ><Trash2 size={13} /></button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Create Invoice Modal */}
      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={() => setShowCreate(false)} />
          <div className="relative bg-surface-800 border border-surface-700 rounded-2xl w-full max-w-lg shadow-2xl animate-slide-up max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between p-6 border-b border-surface-700 sticky top-0 bg-surface-800 z-10">
              <h2 className="font-semibold text-surface-100">New Invoice</h2>
              <button onClick={() => setShowCreate(false)} className="text-surface-400 hover:text-surface-100"><X size={18} /></button>
            </div>
            <form onSubmit={handleCreate} className="p-6 space-y-4">
              {formError && (
                <div className="flex items-center gap-2 p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
                  <AlertCircle size={14} /> {formError}
                </div>
              )}
              <div>
                <label htmlFor="inv-customer" className="label">Customer <span className="text-red-400">*</span></label>
                <select id="inv-customer" required value={form.customer_id} onChange={e => setForm(p => ({ ...p, customer_id: e.target.value }))} className="input">
                  <option value="">Select customer…</option>
                  {customers.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </div>
              {[
                { id: 'inv-num',   label: 'Invoice Number', field: 'invoice_number', required: true },
                { id: 'inv-issue', label: 'Issue Date',     field: 'issue_date',     type: 'date', required: true },
                { id: 'inv-due',   label: 'Due Date',       field: 'due_date',       type: 'date', required: true },
                { id: 'inv-total', label: 'Total Amount',   field: 'total_amount',   type: 'number', required: true },
                { id: 'inv-paid',  label: 'Paid Amount',    field: 'paid_amount',    type: 'number' },
                { id: 'inv-curr',  label: 'Currency',       field: 'currency' },
                { id: 'inv-notes', label: 'Notes',          field: 'notes' },
              ].map(f => (
                <div key={f.id}>
                  <label htmlFor={f.id} className="label">{f.label}{f.required && <span className="text-red-400 ml-0.5">*</span>}</label>
                  <input
                    id={f.id} type={f.type ?? 'text'} required={f.required}
                    value={form[f.field as keyof typeof form]}
                    onChange={e => setForm(p => ({ ...p, [f.field]: e.target.value }))}
                    className="input"
                  />
                </div>
              ))}
              <div className="flex gap-3 pt-2">
                <button type="button" onClick={() => setShowCreate(false)} className="btn-secondary flex-1 justify-center">Cancel</button>
                <button id="save-invoice-btn" type="submit" disabled={saving} className="btn-primary flex-1 justify-center">
                  {saving ? 'Creating…' : 'Create Invoice'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Record Payment Modal */}
      {showPay && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={() => setShowPay(null)} />
          <div className="relative bg-surface-800 border border-surface-700 rounded-2xl w-full max-w-sm p-6 shadow-2xl animate-slide-up">
            <h2 className="font-semibold text-surface-100 mb-1">Record Payment</h2>
            <p className="text-surface-400 text-sm mb-4">{showPay.invoice_number} · Total: {fmt(showPay.total_amount)}</p>
            {formError && <div className="text-red-400 text-sm mb-3">{formError}</div>}
            <form onSubmit={handlePay} className="space-y-4">
              <div>
                <label htmlFor="pay-amount" className="label">Payment amount <span className="text-red-400">*</span></label>
                <input id="pay-amount" type="number" min="0" step="0.01" required value={payAmount}
                  onChange={e => setPayAmount(e.target.value)} className="input" />
              </div>
              <div>
                <label htmlFor="pay-reference" className="label">Reference</label>
                <input id="pay-reference" maxLength={255} value={payReference} onChange={e => setPayReference(e.target.value)} className="input" placeholder="Receipt or transfer reference" />
              </div>
              <div className="flex gap-3">
                <button type="button" onClick={() => setShowPay(null)} className="btn-secondary flex-1 justify-center">Cancel</button>
                <button type="submit" disabled={saving} className="btn-primary flex-1 justify-center">
                  {saving ? 'Recording…' : 'Record payment'}
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
            <h2 className="font-semibold text-surface-100 mb-2">Delete Invoice?</h2>
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
