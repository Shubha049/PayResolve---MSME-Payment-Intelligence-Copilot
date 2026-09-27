import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard, FileText, Users, Briefcase, Files,
  Shield, Bot
} from 'lucide-react';
import PayResolveLogo from './PayResolveLogo';

const navItems = [
  { to: '/',          icon: LayoutDashboard, label: 'Dashboard'  },
  { to: '/documents', icon: Files,           label: 'Documents'  },
  { to: '/invoices',  icon: FileText,        label: 'Invoices'   },
  { to: '/customers', icon: Users,           label: 'Customers'  },
  { to: '/cases',     icon: Briefcase,       label: 'Cases'      },
  { to: '/copilot',   icon: Bot,             label: 'Copilot'    },
];

export default function Sidebar() {
  return (
    <aside className="w-full md:w-60 flex-shrink-0 bg-white border-b md:border-b-0 md:border-r border-surface-700 flex flex-col md:h-full">
      {/* Logo */}
      <div className="flex items-center px-5 py-5 border-b border-surface-700"><PayResolveLogo /></div>

      {/* Navigation */}
      <nav className="flex-1 p-2 md:p-3 flex md:block gap-1 overflow-x-auto md:space-y-0.5">
        <div className="hidden md:block px-3 py-2 text-[10px] font-semibold text-surface-500 uppercase tracking-widest mb-1">
          Workspace
        </div>
        {navItems.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              `nav-item whitespace-nowrap ${isActive ? 'active' : ''}`
            }
          >
            <Icon size={16} />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>

      {/* Legal disclaimer footer */}
      <div className="hidden md:block p-4 border-t border-surface-700">
        <div className="flex items-start gap-2 p-3 rounded-lg bg-amber-500/5 border border-amber-500/20">
          <Shield size={12} className="text-amber-400 flex-shrink-0 mt-0.5" />
          <p className="text-[10px] text-surface-400 leading-relaxed">
            PayResolve AI is a document intelligence assistant, not legal counsel.
          </p>
        </div>
      </div>
    </aside>
  );
}
