import axios from 'axios';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const apiClient = axios.create({
  baseURL: `${API_BASE}/api/v1`,
  headers: { 'Content-Type': 'application/json' },
});

const session = window.sessionStorage;

// Attach JWT + active org on every request
apiClient.interceptors.request.use((config) => {
  const token = session.getItem('access_token');
  const orgId = session.getItem('active_org_id');
  if (token) config.headers['Authorization'] = `Bearer ${token}`;
  if (orgId) config.headers['X-Organization-Id'] = orgId;
  return config;
});

// Auto-logout on 401
apiClient.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401) {
      session.clear();
      window.location.href = '/login';
    }
    return Promise.reject(err);
  }
);

export default apiClient;
