import { useState } from 'react';
import { Bell, ChevronDown, Building2, LogOut, Check, Search } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export default function Navbar() {
  const { user, organizations, activeOrg, switchOrg, logout } = useAuth();
  const [orgMenuOpen, setOrgMenuOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [quickNavOpen, setQuickNavOpen] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);

  const initials = user?.full_name
    ?.split(' ')
    .map(n => n[0])
    .join('')
    .toUpperCase()
    .slice(0, 2) ?? '?';

  return (
    <header className="h-16 flex-shrink-0 bg-white border-b border-surface-700 px-4 sm:px-6 flex items-center justify-between z-20">
      {/* Page title placeholder — pages set this via document.title */}
      <div className="flex items-center gap-3 min-w-0">
        <div className="hidden sm:block text-xs font-semibold uppercase tracking-[0.12em] text-surface-400">Workspace</div>
        <div className="relative hidden lg:block">
          <button onClick={() => setQuickNavOpen(open => !open)} className="flex items-center gap-2 w-72 rounded-lg border border-surface-700 bg-surface-900 px-3 py-2 text-sm text-surface-400 hover:border-brand-200 transition-colors" aria-label="Open quick navigation">
            <Search size={15} /><span>Search workspace</span><kbd className="ml-auto text-[10px] border border-surface-600 rounded px-1.5 py-0.5">Ctrl K</kbd>
          </button>
          {quickNavOpen && <div className="absolute top-full left-0 mt-2 w-72 rounded-xl border border-surface-700 bg-white p-2 shadow-xl shadow-slate-900/10 z-50"><div className="px-2 py-1.5 text-[10px] uppercase tracking-widest font-semibold text-surface-400">Jump to</div>{[['/', 'Dashboard'], ['/cases', 'Cases'], ['/invoices', 'Invoices & payments'], ['/documents', 'Documents'], ['/copilot', 'Copilot']].map(([to, label]) => <Link key={to} to={to} onClick={() => setQuickNavOpen(false)} className="block rounded-lg px-3 py-2 text-sm text-surface-200 hover:bg-brand-50 hover:text-brand-700">{label}</Link>)}</div>}
        </div>
      </div>

      <div className="flex items-center gap-3">
        {/* Org Switcher */}
        {organizations.length > 0 && (
          <div className="relative">
            <button
              id="org-switcher-btn"
              onClick={() => { setOrgMenuOpen(p => !p); setUserMenuOpen(false); }}
              className="flex items-center gap-2 px-3 py-2 rounded-lg bg-surface-900 border border-surface-700 text-sm text-surface-200 hover:border-brand-200 transition-colors"
            >
              <Building2 size={14} className="text-brand-400" />
              <span className="max-w-[120px] truncate">{activeOrg?.name}</span>
              <ChevronDown size={13} className="text-surface-400" />
            </button>
            {orgMenuOpen && (
              <div className="absolute right-0 top-full mt-2 w-56 bg-white border border-surface-700 rounded-xl shadow-xl shadow-slate-900/10 z-50 overflow-hidden animate-slide-up">
                <div className="px-3 py-2 text-[10px] font-semibold text-surface-500 uppercase tracking-widest border-b border-surface-700">
                  Switch Organization
                </div>
                {organizations.map(org => (
                  <button
                    key={org.id}
                    onClick={() => { switchOrg(org); setOrgMenuOpen(false); }}
                    className="w-full flex items-center gap-3 px-3 py-2.5 text-sm text-surface-200 hover:bg-surface-900 transition-colors text-left"
                  >
                    <div className="w-6 h-6 rounded bg-brand-500/20 flex items-center justify-center flex-shrink-0">
                      <span className="text-[10px] font-bold text-brand-400">{org.name[0]}</span>
                    </div>
                    <span className="flex-1 truncate">{org.name}</span>
                    {org.id === activeOrg?.id && <Check size={13} className="text-brand-400" />}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Notification bell — placeholder */}
        <div className="relative">
        <button onClick={() => setNotificationsOpen(open => !open)} className="relative icon-button" aria-label="Notifications" title="Notifications">
          <Bell size={14} className="text-surface-300" />
        </button>
        {notificationsOpen && <div className="absolute right-0 top-full mt-2 w-64 rounded-xl border border-surface-700 bg-white p-4 shadow-xl shadow-slate-900/10 z-50"><div className="text-sm font-semibold text-surface-100">Notifications</div><p className="text-xs text-surface-400 mt-2">You’re all caught up. New recovery activity will appear here.</p></div>}
        </div>

        {/* User Menu */}
        <div className="relative">
          <button
            id="user-menu-btn"
            onClick={() => { setUserMenuOpen(p => !p); setOrgMenuOpen(false); }}
            className="flex items-center gap-2 hover:opacity-80 transition-opacity"
          >
            <div className="w-8 h-8 rounded-lg bg-brand-600 flex items-center justify-center text-xs font-bold text-white shadow-sm">
              {initials}
            </div>
            <ChevronDown size={13} className="text-surface-400" />
          </button>
          {userMenuOpen && (
            <div className="absolute right-0 top-full mt-2 w-52 bg-white border border-surface-700 rounded-xl shadow-xl shadow-slate-900/10 z-50 overflow-hidden animate-slide-up">
              <div className="px-3 py-3 border-b border-surface-700">
                <div className="text-sm font-medium text-surface-100">{user?.full_name}</div>
                <div className="text-xs text-surface-400 truncate">{user?.email}</div>
              </div>
              <button
                onClick={logout}
                className="w-full flex items-center gap-3 px-3 py-2.5 text-sm text-red-400 hover:bg-red-500/10 transition-colors"
              >
                <LogOut size={14} />
                Sign Out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
