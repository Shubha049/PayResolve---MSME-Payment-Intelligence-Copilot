import apiClient from './client';

// --- Auth ---
export const authAPI = {
  register: (data: { email: string; password: string; full_name: string; organization_name: string }) =>
    apiClient.post('/auth/register', data),
  login: (data: { email: string; password: string }) =>
    apiClient.post('/auth/login', data),
  me: () => apiClient.get('/auth/me'),
};

// --- Organizations ---
export const orgsAPI = {
  list: () => apiClient.get('/organizations/'),
  create: (data: { name: string }) => apiClient.post('/organizations/', data),
  listMembers: () => apiClient.get('/organizations/members'),
};

// --- Dashboard ---
export const dashboardAPI = {
  summary: () => apiClient.get('/dashboard/summary'),
  recovery: () => apiClient.get('/recovery/dashboard'),
  activity: () => apiClient.get('/recovery/dashboard/activity'),
};

// --- Customers ---
export const customersAPI = {
  list: (search?: string) =>
    apiClient.get('/customers/', { params: search ? { search } : {} }),
  create: (data: { name: string; email?: string; phone?: string; tax_id?: string; address?: string }) =>
    apiClient.post('/customers/', data),
  get: (id: string) => apiClient.get(`/customers/${id}`),
  update: (id: string, data: Partial<{ name: string; email: string; phone: string; tax_id: string; address: string }>) =>
    apiClient.patch(`/customers/${id}`, data),
  delete: (id: string) => apiClient.delete(`/customers/${id}`),
};

// --- Invoices ---
export const invoicesAPI = {
  list: (params?: { status?: string; customer_id?: string; is_overdue?: boolean; search?: string }) =>
    apiClient.get('/invoices/', { params }),
  create: (data: {
    customer_id: string; invoice_number: string; issue_date: string;
    due_date: string; total_amount: string; paid_amount?: string;
    currency?: string; notes?: string;
  }) => apiClient.post('/invoices/', data),
  get: (id: string) => apiClient.get(`/invoices/${id}`),
  update: (id: string, data: Record<string, unknown>) => apiClient.patch(`/invoices/${id}`, data),
  delete: (id: string) => apiClient.delete(`/invoices/${id}`),
};

// --- Payments ---
export const paymentsAPI = {
  list: (params?: { invoice_id?: string; from_date?: string; to_date?: string; skip?: number; limit?: number }) =>
    apiClient.get('/payments/', { params }),
  create: (data: { invoice_id: string; amount: string; payment_date: string; reference?: string }) =>
    apiClient.post('/payments/', data),
  get: (id: string) => apiClient.get(`/payments/${id}`),
};

// --- Cases ---
export const casesAPI = {
  list: (params?: { status?: string; priority?: string; customer_id?: string }) =>
    apiClient.get('/cases/', { params }),
  create: (data: {
    customer_id: string; case_number: string; title: string;
    invoice_id?: string; status?: string; priority?: string; summary?: string;
  }) => apiClient.post('/cases/', data),
  get: (id: string) => apiClient.get(`/cases/${id}`),
  update: (id: string, data: Record<string, unknown>) => apiClient.patch(`/cases/${id}`, data),
  delete: (id: string) => apiClient.delete(`/cases/${id}`),
};

// --- Documents ---
export const documentsAPI = {
  upload: (formData: FormData, params?: { invoice_id?: string; case_id?: string }) =>
    apiClient.post('/documents/upload', formData, {
      params,
      headers: { 'Content-Type': 'multipart/form-data' },
    }),
  list: (params?: { doc_type?: string; status?: string; limit?: number; offset?: number }) =>
    apiClient.get('/documents/', { params }),
  get: (id: string) => apiClient.get(`/documents/${id}`),
  delete: (id: string) => apiClient.delete(`/documents/${id}`),
  getChunks: (id: string, params?: { limit?: number; offset?: number }) =>
    apiClient.get(`/documents/${id}/chunks`, { params }),
};

// --- Risk ---
export const riskAPI = {
  getInvoiceRisk: (invoiceId: string) => apiClient.get(`/risk/invoice/${invoiceId}`),
  getCustomerRisk: (customerId: string) => apiClient.get(`/risk/customer/${customerId}`),
  rescoreInvoice: (invoiceId: string) => apiClient.post(`/risk/invoice/${invoiceId}/rescore`),
  getInvoiceRiskHistory: (invoiceId: string) => apiClient.get(`/risk/invoice/${invoiceId}/history`),
};

// --- Recovery workflow ---
export const recoveryActionsAPI = {
  list: (caseId: string, params?: { limit?: number; offset?: number }) =>
    apiClient.get(`/cases/${caseId}/actions`, { params }),
  create: (caseId: string, data: { action_type: string; action_date: string; notes?: string; next_follow_up_date?: string }) =>
    apiClient.post(`/cases/${caseId}/actions`, data),
  timeline: (caseId: string) => apiClient.get(`/cases/${caseId}/timeline`),
};

export const promisesAPI = {
  list: (caseId: string) => apiClient.get(`/cases/${caseId}/promises/`),
  create: (caseId: string, data: { promise_date: string; promised_amount: string; notes?: string }) =>
    apiClient.post(`/cases/${caseId}/promises/`, data),
  get: (id: string) => apiClient.get(`/promises/${id}/`),
  update: (id: string, data: Record<string, unknown>) => apiClient.patch(`/promises/${id}/`, data),
};

// --- Copilot ---
export const copilotAPI = {
  query: (data: { query: string; doc_type?: string; invoice_id?: string; case_id?: string; conversation_id?: string }) =>
    apiClient.post('/copilot/query', data),
  recoveryQuery: (data: { query: string; case_id?: string; conversation_id?: string }) =>
    apiClient.post('/copilot/recovery-query', data),
  search: (data: { query: string; limit?: number; doc_type?: string; invoice_id?: string; case_id?: string }) =>
    apiClient.post('/copilot/search', data),
};
