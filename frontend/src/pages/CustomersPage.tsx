import React, { useEffect, useState, useCallback } from 'react';
import { Plus, Search, Pencil, Trash2, X, AlertCircle, Users } from 'lucide-react';
import { customersAPI } from '../api/endpoints';

interface Customer {
  id: string;
  name: string;
  email?: string;
  phone?: string;
  tax_id?: string;
  address?: string;
}

interface FormState {
  name: string; email: string; phone: string; tax_id: string; address: string;
}

const EMPTY_FORM: FormState = { name: '', email: '', phone: '', tax_id: '', address: '' };

export default function CustomersPage() {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loading, setLoading]     = useState(true);
  const [search, setSearch]       = useState('');
  const [error, setError]         = useState('');

  // Modal state
  const [showModal, setShowModal]   = useState(false);
  const [editing, setEditing]       = useState<Customer | null>(null);
  const [form, setForm]             = useState<FormState>(EMPTY_FORM);
  const [saving, setSaving]         = useState(false);
  const [formError, setFormError]   = useState('');
  const [deleteId, setDeleteId]     = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await customersAPI.list(search || undefined);
      setCustomers(res.data?.items ?? res.data ?? []);
    } catch { setError('Failed to load customers.'); }
    finally { setLoading(false); }
  }, [search]);

  useEffect(() => { load(); }, [load]);

  function openCreate() { setEditing(null); setForm(EMPTY_FORM); setFormError(''); setShowModal(true); }
  function openEdit(c: Customer) {
    setEditing(c);
    setForm({ name: c.name, email: c.email ?? '', phone: c.phone ?? '', tax_id: c.tax_id ?? '', address: c.address ?? '' });
    setFormError('');
    setShowModal(true);
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setFormError('');
    if (!form.name.trim()) { setFormError('Customer name is required.'); return; }
    setSaving(true);
    try {
      const payload = {
        name: form.name, email: form.email || undefined, phone: form.phone || undefined,
        tax_id: form.tax_id || undefined, address: form.address || undefined,
      };
      if (editing) { await customersAPI.update(editing.id, payload); }
      else { await customersAPI.create(payload); }
      setShowModal(false);
      load();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Save failed.';
      setFormError(msg);
    } finally { setSaving(false); }
  }

  async function handleDelete(id: string) {
    try { await customersAPI.delete(id); load(); } catch { setError('Delete failed.'); }
    setDeleteId(null);
  }

  const fields: { id: string; label: string; field: keyof FormState; type?: string; required?: boolean }[] = [
    { id: 'cust-name',    label: 'Company / Contact Name', field: 'name',    required: true },
    { id: 'cust-email',   label: 'Email',                  field: 'email',   type: 'email' },
    { id: 'cust-phone',   label: 'Phone',                  field: 'phone',   type: 'tel' },
    { id: 'cust-taxid',   label: 'Tax ID / GSTIN',         field: 'tax_id' },
    { id: 'cust-address', label: 'Address',                field: 'address' },
  ];

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-surface-50">Customers</h1>
          <p className="text-surface-400 text-sm">{customers.length} buyer{customers.length !== 1 ? 's' : ''} on record</p>
        </div>
        <button id="create-customer-btn" onClick={openCreate} className="btn-primary">
          <Plus size={15} /> Add Customer
        </button>
      </div>

      {/* Search */}
      <div className="relative max-w-xs">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-surface-400" />
        <input
          id="customer-search"
          className="input pl-9"
          placeholder="Search customers…"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
      </div>

      {error && <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">{error}</div>}

      {/* Table */}
      <div className="card !p-0 overflow-hidden">
        {loading ? (
          <div className="flex items-center justify-center h-40">
            <div className="w-7 h-7 border-2 border-brand-500 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : customers.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-surface-500">
            <Users size={36} className="mb-3 opacity-30" />
            <p className="font-medium">No customers yet</p>
            <p className="text-sm mt-1">Add your first customer to get started</p>
          </div>
        ) : (
          <table className="table-base">
            <thead>
              <tr>
                <th>Name</th><th>Email</th><th>Phone</th><th>Tax ID</th><th className="text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {customers.map(c => (
                <tr key={c.id}>
                  <td className="font-medium text-surface-100">{c.name}</td>
                  <td className="text-surface-300">{c.email || '—'}</td>
                  <td className="text-surface-300">{c.phone || '—'}</td>
                  <td className="font-mono text-xs text-surface-400">{c.tax_id || '—'}</td>
                  <td className="text-right">
                    <div className="flex items-center justify-end gap-2">
                      <button
                        onClick={() => openEdit(c)}
                        className="p-1.5 rounded-lg hover:bg-surface-700 text-surface-400 hover:text-surface-100 transition-colors"
                        aria-label="Edit customer"
                      >
                        <Pencil size={13} />
                      </button>
                      <button
                        onClick={() => setDeleteId(c.id)}
                        className="p-1.5 rounded-lg hover:bg-red-500/10 text-surface-400 hover:text-red-400 transition-colors"
                        aria-label="Delete customer"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Create/Edit Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={() => setShowModal(false)} />
          <div className="relative bg-surface-800 border border-surface-700 rounded-2xl w-full max-w-md shadow-2xl animate-slide-up">
            <div className="flex items-center justify-between p-6 border-b border-surface-700">
              <h2 className="font-semibold text-surface-100">{editing ? 'Edit Customer' : 'Add Customer'}</h2>
              <button onClick={() => setShowModal(false)} className="text-surface-400 hover:text-surface-100 transition-colors">
                <X size={18} />
              </button>
            </div>
            <form onSubmit={handleSave} className="p-6 space-y-4">
              {formError && (
                <div className="flex items-center gap-2 p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
                  <AlertCircle size={14} /> {formError}
                </div>
              )}
              {fields.map(f => (
                <div key={f.id}>
                  <label htmlFor={f.id} className="label">
                    {f.label}{f.required && <span className="text-red-400 ml-0.5">*</span>}
                  </label>
                  <input
                    id={f.id}
                    type={f.type ?? 'text'}
                    required={f.required}
                    value={form[f.field]}
                    onChange={e => setForm(p => ({ ...p, [f.field]: e.target.value }))}
                    className="input"
                  />
                </div>
              ))}
              <div className="flex gap-3 pt-2">
                <button type="button" onClick={() => setShowModal(false)} className="btn-secondary flex-1 justify-center">Cancel</button>
                <button id="save-customer-btn" type="submit" disabled={saving} className="btn-primary flex-1 justify-center">
                  {saving ? 'Saving…' : editing ? 'Update' : 'Create'}
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
            <h2 className="font-semibold text-surface-100 mb-2">Delete Customer?</h2>
            <p className="text-surface-400 text-sm mb-5">This will permanently remove the customer and all associated records.</p>
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
