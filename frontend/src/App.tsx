import { Suspense, lazy } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import Layout from './components/Layout';

// Public pages
const LoginPage    = lazy(() => import('./pages/LoginPage'));
const RegisterPage = lazy(() => import('./pages/RegisterPage'));

// Protected pages
const DashboardPage  = lazy(() => import('./pages/DashboardPage'));
const InvoicesPage   = lazy(() => import('./pages/InvoicesPage'));
const CustomersPage  = lazy(() => import('./pages/CustomersPage'));
const CasesPage      = lazy(() => import('./pages/CasesPage'));
const DocumentsPage  = lazy(() => import('./pages/DocumentsPage'));
const CaseDetailPage = lazy(() => import('./pages/CaseDetailPage'));
const CopilotPage    = lazy(() => import('./pages/CopilotPage'));

function PageLoader() {
  return (
    <div className="flex items-center justify-center h-full min-h-[300px]">
      <div className="w-8 h-8 border-2 border-brand-500 border-t-transparent rounded-full animate-spin" />
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Suspense fallback={<PageLoader />}>
          <Routes>
            {/* Public */}
            <Route path="/login"    element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />

            {/* Protected — all under authenticated Layout */}
            <Route element={<Layout />}>
              <Route index              element={<DashboardPage />} />
              <Route path="invoices"    element={<InvoicesPage />} />
              <Route path="customers"   element={<CustomersPage />} />
              <Route path="cases"       element={<CasesPage />} />
              <Route path="cases/:caseId" element={<CaseDetailPage />} />
              <Route path="documents"   element={<DocumentsPage />} />
              <Route path="copilot"     element={<CopilotPage />} />
            </Route>

            {/* Catch-all */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </AuthProvider>
    </BrowserRouter>
  );
}
