import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Mail, Lock, User, Building2, Eye, EyeOff, AlertCircle, CheckCircle } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import PayResolveLogo from '../components/PayResolveLogo';

function PasswordStrength({ password }: { password: string }) {
  const checks = [
    { label: '8+ characters', ok: password.length >= 8 },
    { label: 'Uppercase letter', ok: /[A-Z]/.test(password) },
    { label: 'Number or symbol', ok: /[\d\W]/.test(password) },
  ];
  const score = checks.filter(c => c.ok).length;
  const colors = ['bg-red-500', 'bg-amber-500', 'bg-emerald-500'];
  const labels = ['Weak', 'Fair', 'Strong'];

  if (!password) return null;

  return (
    <div className="mt-2 space-y-1.5 animate-fade-in">
      <div className="flex gap-1">
        {[0, 1, 2].map(i => (
          <div key={i} className={`h-1 flex-1 rounded-full transition-all duration-300 ${i < score ? colors[score - 1] : 'bg-surface-700'}`} />
        ))}
      </div>
      <div className="flex items-center gap-1 text-[11px] text-surface-400">
        <span className={score > 0 ? colors[score - 1].replace('bg-', 'text-') : 'text-surface-500'}>
          {score > 0 ? labels[score - 1] : ''}
        </span>
        {checks.map(c => (
          <span key={c.label} className={`ml-2 ${c.ok ? 'text-emerald-400' : 'text-surface-600'}`}>
            {c.ok ? '✓' : '○'} {c.label}
          </span>
        ))}
      </div>
    </div>
  );
}

export default function RegisterPage() {
  const { register, isAuthenticated } = useAuth();
  const navigate = useNavigate();

  const [form, setForm] = useState({ email: '', password: '', fullName: '', orgName: '' });
  const [showPw, setShowPw]   = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState('');

  if (isAuthenticated) {
    navigate('/', { replace: true });
    return null;
  }

  function update(field: keyof typeof form) {
    return (e: React.ChangeEvent<HTMLInputElement>) => setForm(f => ({ ...f, [field]: e.target.value }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    if (!form.orgName.trim()) { setError('Organization name is required.'); return; }
    setLoading(true);
    try {
      await register(form.email, form.password, form.fullName, form.orgName);
      navigate('/', { replace: true });
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail ?? 'Registration failed. Please try again.';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  const fields = [
    { id: 'reg-name',  label: 'Full name',          icon: User,      field: 'fullName' as const, type: 'text',     placeholder: 'Jane Smith',         autoComplete: 'name' },
    { id: 'reg-org',   label: 'Organization name',   icon: Building2, field: 'orgName'  as const, type: 'text',     placeholder: 'Acme Pvt Ltd',       autoComplete: 'organization' },
    { id: 'reg-email', label: 'Work email',           icon: Mail,      field: 'email'    as const, type: 'email',    placeholder: 'you@company.com',    autoComplete: 'email' },
  ];

  return (
    <div className="min-h-screen app-gradient flex items-center justify-center p-4 page-grid">

      <div className="w-full max-w-md relative z-10 animate-fade-in">
        {/* Logo */}
        <div className="flex flex-col items-center mb-8"><PayResolveLogo /><h1 className="text-2xl font-bold text-surface-50 mt-5">Get started free</h1><p className="text-surface-400 text-sm mt-1">Create your PayResolve workspace</p></div>

        <div className="bg-white border border-surface-700 rounded-2xl p-8 shadow-[0_20px_60px_rgba(32,58,94,0.1)]">
          <h2 className="text-lg font-semibold text-surface-100 mb-6">Create your account</h2>

          {error && (
            <div className="flex items-start gap-3 p-3 mb-5 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm animate-slide-up">
              <AlertCircle size={15} className="flex-shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            {fields.map(({ id, label, icon: Icon, field, type, placeholder, autoComplete }) => (
              <div key={id}>
                <label htmlFor={id} className="label">{label}</label>
                <div className="relative">
                  <Icon size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-surface-400" />
                  <input
                    id={id}
                    type={type}
                    autoComplete={autoComplete}
                    required
                    value={form[field]}
                    onChange={update(field)}
                    placeholder={placeholder}
                    className="input pl-9"
                  />
                  {form[field] && field !== 'email' && (
                    <CheckCircle size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-emerald-400 animate-fade-in" />
                  )}
                </div>
              </div>
            ))}

            {/* Password */}
            <div>
              <label htmlFor="reg-password" className="label">Password</label>
              <div className="relative">
                <Lock size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-surface-400" />
                <input
                  id="reg-password"
                  type={showPw ? 'text' : 'password'}
                  autoComplete="new-password"
                  required
                  minLength={6}
                  value={form.password}
                  onChange={update('password')}
                  placeholder="Create a strong password"
                  className="input pl-9 pr-10"
                />
                <button
                  type="button"
                  onClick={() => setShowPw(p => !p)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-surface-400 hover:text-surface-200 transition-colors"
                  aria-label={showPw ? 'Hide password' : 'Show password'}
                >
                  {showPw ? <EyeOff size={15} /> : <Eye size={15} />}
                </button>
              </div>
              <PasswordStrength password={form.password} />
            </div>

            <button
              id="register-submit-btn"
              type="submit"
              disabled={loading}
              className="btn-primary w-full justify-center py-2.5 mt-2"
            >
              {loading ? (
                <span className="flex items-center gap-2">
                  <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Creating workspace…
                </span>
              ) : 'Create Account'}
            </button>
          </form>

          <p className="text-center text-sm text-surface-400 mt-6">
            Already have an account?{' '}
            <Link to="/login" className="text-brand-400 hover:text-brand-300 font-medium transition-colors">
              Sign in
            </Link>
          </p>
        </div>

        <p className="text-center text-[11px] text-surface-500 mt-5 px-4">
          PayResolve AI is a document intelligence assistant, not legal counsel.
        </p>
      </div>
    </div>
  );
}
