import { createContext, useContext, useState, useEffect, type ReactNode } from 'react';
import { authAPI, orgsAPI } from '../api/endpoints';

interface Organization {
  id: string;
  name: string;
  slug: string;
}

interface User {
  id: string;
  email: string;
  full_name: string;
}

interface AuthContextType {
  user: User | null;
  organizations: Organization[];
  activeOrg: Organization | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, fullName: string, orgName: string) => Promise<void>;
  logout: () => void;
  switchOrg: (org: Organization) => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [activeOrg, setActiveOrg] = useState<Organization | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const session = window.sessionStorage;

  useEffect(() => {
    const token = session.getItem('access_token');
    if (token) {
      bootstrapSession();
    } else {
      setIsLoading(false);
    }
  }, []);

  async function bootstrapSession() {
    try {
      const [meRes, orgsRes] = await Promise.all([authAPI.me(), orgsAPI.list()]);
      setUser(meRes.data);
      const orgs: Organization[] = orgsRes.data;
      setOrganizations(orgs);
      const savedOrgId = session.getItem('active_org_id');
      const current = orgs.find(o => o.id === savedOrgId) || orgs[0] || null;
      if (current) {
        setActiveOrg(current);
        session.setItem('active_org_id', current.id);
      }
    } catch {
      session.clear();
    } finally {
      setIsLoading(false);
    }
  }

  const login = async (email: string, password: string) => {
    const res = await authAPI.login({ email, password });
    const { access_token, organization_id } = res.data;
    session.setItem('access_token', access_token);
    session.setItem('active_org_id', organization_id);
    await bootstrapSession();
  };

  const register = async (email: string, password: string, fullName: string, orgName: string) => {
    const res = await authAPI.register({ email, password, full_name: fullName, organization_name: orgName });
    const { access_token, organization_id } = res.data;
    session.setItem('access_token', access_token);
    session.setItem('active_org_id', organization_id);
    await bootstrapSession();
  };

  const logout = () => {
    session.clear();
    setUser(null);
    setOrganizations([]);
    setActiveOrg(null);
    window.location.href = '/login';
  };

  const switchOrg = (org: Organization) => {
    setActiveOrg(org);
    session.setItem('active_org_id', org.id);
    window.location.reload();
  };

  return (
    <AuthContext.Provider value={{
      user, organizations, activeOrg, isAuthenticated: !!user,
      isLoading, login, register, logout, switchOrg,
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}
