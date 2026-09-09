import axios from 'axios';

/**
 * Single axios instance for the whole app.
 * - baseURL '/api' (Vite dev proxy -> Flask :5000)
 * - attaches the bearer token
 * - on 401 clears the session and bounces to /login
 * - normalises errors to a friendly message (never a stack trace)
 */
const client = axios.create({ baseURL: '/api', timeout: 90000 });

client.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) config.headers['Authorization'] = `Bearer ${token}`;
  return config;
});

client.interceptors.response.use(
  (res) => res,
  (error) => {
    if (error.response && error.response.status === 401) {
      localStorage.removeItem('token');
      localStorage.removeItem('user');
      if (window.location.pathname !== '/login') window.location.assign('/login');
    }
    return Promise.reject(error);
  }
);

/** Turn an axios error into a short user-facing string. */
export function apiError(error, fallback = 'Something went wrong. Please try again.') {
  const data = error?.response?.data;
  if (data && typeof data === 'object' && typeof data.error === 'string') return data.error;
  if (error?.code === 'ECONNABORTED') return 'The request timed out. Please try again.';
  if (!error?.response) return 'Cannot reach the server. Check your connection and try again.';
  return fallback;
}

export default client;
