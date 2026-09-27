import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  FileText, Briefcase, Activity, AlertTriangle,
  DollarSign, Clock, ArrowUpRight, RefreshCw, Bot
} from 'lucide-react';
import { dashboardAPI, invoicesAPI, casesAPI } from '../api/endpoints';
import { useAuth } from '../context/AuthContext';

interface Summary {
  invoices_count: number;
  overdue_invoices_count: number;
  total_outstanding: string;
  active_cases_count: number;
}

interface RecoverySummary {
  cases: { total: number; active: number; resolved: number };
  financial: { total_recovered: string; total_overdue: string };
  promises: { pending: number; broken: number };
  activity: { actions_count: number; last_7_days: number };
}

interface Activity {
  id: string;
  action: string;
  entity_type: string;
  timestamp: string;
}

interface Invoice {
  id: string;
  invoice_number: string;
  total_amount: string;
  outstanding_amount: string;
  due_date: string;
  status: string;
  customer_name?: string;
}

interface Case {
  id: string;
  case_number: string;
  title: string;
  status: string;
  priority: string;
  customer_name?: string;
}

function fmt(amount: number, currency = 'INR') {
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency, maximumFractionDigits: 0 }).format(amount);
}

function money(value: string | number | undefined) {
  return fmt(Number(value ?? 0));
}

function statusBadge(status: string) {
  const map: Record<string, string> = {
    PAID: 'badge-green', PENDING: 'badge-yellow', OVERDUE: 'badge-red',
    PARTIALLY_PAID: 'badge-blue', DISPUTED: 'badge-purple', CANCELLED: 'badge-gray',
    OPEN: 'badge-blue', IN_PROGRESS: 'badge-yellow', RESOLVED: 'badge-green', CLOSED: 'badge-gray',
  };
  return map[status] ?? 'badge-gray';
}

function priorityBadge(p: string) {
  return p === 'HIGH' ? 'badge-red' : p === 'MEDIUM' ? 'badge-yellow' : 'badge-gray';
}

export default function DashboardPage() {
  const { activeOrg } = useAuth();
  const [summary, setSummary]   = useState<Summary | null>(null);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [cases, setCases]       = useState<Case[]>([]);
  const [recovery, setRecovery] = useState<RecoverySummary | null>(null);
  const [activity, setActivity] = useState<Activity[]>([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState('');

  useEffect(() => { load(); }, [activeOrg]);

  async function load() {
    setLoading(true);
    setError('');
    try {
      const [sumRes, invRes, caseRes, recoveryRes, activityRes] = await Promise.all([
        dashboardAPI.summary(),
        invoicesAPI.list({ is_overdue: true }),
        casesAPI.list({ status: 'OPEN' }),
        dashboardAPI.recovery(),
        dashboardAPI.activity(),
      ]);
      setSummary(sumRes.data);
      setInvoices((invRes.data?.items ?? invRes.data ?? []).slice(0, 5));
      setCases((caseRes.data?.items ?? caseRes.data ?? []).slice(0, 5));
      setRecovery(recoveryRes.data);
      setActivity(activityRes.data.slice(0, 6));
    } catch {
      setError('Failed to load dashboard data.');
    } finally {
      setLoading(false);
    }
  }

  const metrics = summary ? [
    { label: 'Total Invoices',    value: summary.invoices_count,  icon: FileText,       color: 'text-blue-400',    bg: 'bg-blue-500/10' },
    { label: 'Overdue Invoices',  value: summary.overdue_invoices_count, icon: AlertTriangle,  color: 'text-rose-700',     bg: 'bg-rose-50' },
    { label: 'Outstanding',       value: money(summary.total_outstanding), icon: DollarSign, color: 'text-amber-700', bg: 'bg-amber-50', isText: true },
    { label: 'Open Cases',        value: summary.active_cases_count,       icon: Briefcase,      color: 'text-brand-700',   bg: 'bg-brand-50' },
  ] : [];

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="w-8 h-8 border-2 border-brand-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.14em] text-brand-600 mb-2">Recovery command center</div>
          <h1 className="text-2xl font-bold text-surface-50">Good morning, {activeOrg?.name}</h1>
          <p className="text-surface-400 text-sm mt-1">
            A focused view of invoices, cases, and recovery momentum.
          </p>
        </div>
        <button onClick={load} className="btn-secondary gap-2">
          <RefreshCw size={14} />
          Refresh
        </button>
      </div>

      {error && (
        <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
          {error}
        </div>
      )}

      {/* Financial and workflow metrics */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        {metrics.map(m => (
          <div key={m.label} className="metric-card">
            <div className="flex items-start justify-between">
              <div className={`w-10 h-10 rounded-xl ${m.bg} flex items-center justify-center flex-shrink-0`}>
                <m.icon size={18} className={m.color} />
              </div>
              <Activity size={14} className="text-brand-500 opacity-70" />
            </div>
            <div className={`text-2xl font-bold mt-3 ${m.color}`}>
              {m.isText ? m.value : m.value.toLocaleString()}
            </div>
            <div className="text-sm text-surface-300">{m.label}</div>
          </div>
        ))}
      </div>

      {recovery && (
        <div className="card border-brand-100 bg-brand-50/45 !p-5">
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <div className="flex items-center gap-2 text-sm font-semibold text-surface-100"><Activity size={16} className="text-brand-600" /> Recovery pulse</div>
              <p className="text-sm text-surface-400 mt-1">Your team recorded {recovery.activity.last_7_days.toLocaleString()} recovery actions in the last 7 days.</p>
            </div>
            <Link to="/copilot" className="btn-primary"><Bot size={15} /> Open Copilot</Link>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mt-5 pt-4 border-t border-brand-100">
            <div><div className="text-lg font-bold text-emerald-700">{money(recovery.financial.total_recovered)}</div><div className="text-xs text-surface-400 mt-1">Recovered to date</div></div>
            <div><div className="text-lg font-bold text-amber-700">{recovery.promises.pending.toLocaleString()}</div><div className="text-xs text-surface-400 mt-1">Promises pending</div></div>
            <div><div className="text-lg font-bold text-coral-700">{recovery.promises.broken.toLocaleString()}</div><div className="text-xs text-surface-400 mt-1">Broken promises</div></div>
          </div>
        </div>
      )}

      {/* Operational worklists */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        {/* Overdue Invoices */}
        <div className="card">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold text-surface-100 flex items-center gap-2">
              <Clock size={15} className="text-rose-700" /> Overdue Invoices
            </h2>
            <Link to="/invoices" className="text-xs text-brand-700 hover:text-brand-800 flex items-center gap-1 transition-colors">
              View all <ArrowUpRight size={12} />
            </Link>
          </div>
          {invoices.length === 0 ? (
            <p className="text-surface-500 text-sm py-6 text-center">🎉 No overdue invoices</p>
          ) : (
            <table className="table-base">
              <thead>
                <tr>
                  <th>Invoice #</th>
                  <th>Due Date</th>
                  <th>Outstanding</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {invoices.map(inv => (
                  <tr key={inv.id}>
                    <td className="font-mono text-xs text-surface-100">{inv.invoice_number}</td>
                    <td>{inv.due_date}</td>
                    <td className="font-semibold text-amber-700">{money(inv.outstanding_amount)}</td>
                    <td><span className={statusBadge(inv.status)}>{inv.status}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Open Cases */}
        <div className="card">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold text-surface-100 flex items-center gap-2">
              <Briefcase size={15} className="text-brand-700" /> Open Cases
            </h2>
            <Link to="/cases" className="text-xs text-brand-700 hover:text-brand-800 flex items-center gap-1 transition-colors">
              View all <ArrowUpRight size={12} />
            </Link>
          </div>
          {cases.length === 0 ? (
            <p className="text-surface-500 text-sm py-6 text-center">No open cases</p>
          ) : (
            <table className="table-base">
              <thead>
                <tr>
                  <th>Case #</th>
                  <th>Title</th>
                  <th>Priority</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {cases.map(c => (
                  <tr key={c.id}>
                    <td className="font-mono text-xs text-surface-100">{c.case_number}</td>
                    <td className="max-w-[140px] truncate">{c.title}</td>
                    <td><span className={priorityBadge(c.priority)}>{c.priority}</span></td>
                    <td><span className={statusBadge(c.status)}>{c.status}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {activity.length > 0 && (
        <div className="card">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold text-surface-100">Recent recovery activity</h2>
            <span className="text-xs text-surface-500">{recovery?.activity.actions_count ?? activity.length} total events</span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {activity.map(item => (
              <div key={item.id} className="flex items-center gap-3 p-3 rounded-lg bg-surface-900/60 border border-surface-700/70">
                <div className="w-2 h-2 rounded-full bg-brand-400" />
                <div className="min-w-0">
                  <div className="text-sm text-surface-200 truncate">{item.action.replaceAll('_', ' ')}</div>
                  <div className="text-xs text-surface-500">{item.entity_type} · {new Date(item.timestamp).toLocaleDateString()}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
