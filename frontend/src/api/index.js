/* Centralised, typed-by-convention API surface. Every call returns response.data.
   The frontend FETCHES / DISPLAYS / SENDS — it never calculates financial values. */
import client from './client';

export { default as client, apiError } from './client';

const get = (url, params) => client.get(url, { params }).then((r) => r.data);
const post = (url, body) => client.post(url, body).then((r) => r.data);
const put = (url, body) => client.put(url, body).then((r) => r.data);
const del = (url) => client.delete(url).then((r) => r.data);

/* ---- Financial Digital Twin (Phase 3) ---- */
export const twinApi = {
  state: (asOf) => get('/twin/state', asOf ? { as_of: asOf } : undefined),
};

/* ---- Affordability (Phase 4) ---- */
export const affordabilityApi = {
  check: (payload) => post('/affordability/check', payload),
};

/* ---- What-If simulation (Phase 5) ---- */
export const simulationApi = {
  whatIf: (payload) => post('/simulation/what-if', payload),
};

/* ---- Cash-flow forecast (Phase 6) ---- */
export const forecastApi = {
  get: ({ asOf, horizonDays } = {}) =>
    get('/forecast', {
      ...(asOf ? { as_of: asOf } : {}),
      ...(horizonDays ? { horizon_days: horizonDays } : {}),
    }),
};

/* ---- Anomalies / Insights (Phase 7) ---- */
export const anomaliesApi = {
  get: ({ asOf, historyDays } = {}) =>
    get('/anomalies', {
      ...(asOf ? { as_of: asOf } : {}),
      ...(historyDays ? { history_days: historyDays } : {}),
    }),
};

/* ---- Transactions ---- */
export const transactionsApi = {
  list: () => get('/transactions'),
  create: (payload) => post('/transactions', payload),
  updateCategory: (id, categoryId) => put(`/transactions/${id}`, { category_id: categoryId }),
  remove: (id) => del(`/transactions/${id}`),
};

/* ---- Account ---- */
export const accountApi = {
  get: () => get('/account'),
  update: (payload) => put('/account', payload),
};

/* ---- Budgets ---- */
export const budgetsApi = {
  list: (month) => get('/budgets', month ? { month } : undefined),
  upsert: (payload) => post('/budgets/', payload),
  remove: (id) => del(`/budgets/${id}`),
};

/* ---- Categories ---- */
export const categoriesApi = {
  list: () => get('/categories/'),
  create: (payload) => post('/categories/', payload),
  update: (id, payload) => put(`/categories/${id}`, payload),
  remove: (id) => del(`/categories/${id}`),
};

/* ---- Recurring transactions ---- */
export const recurringApi = {
  list: (includeInactive) =>
    get('/recurring', includeInactive ? { include_inactive: 1 } : undefined),
  create: (payload) => post('/recurring', payload),
  update: (id, payload) => put(`/recurring/${id}`, payload),
  remove: (id) => del(`/recurring/${id}`),
};

/* ---- Dashboard summary (legacy convenience) ---- */
export const dashboardApi = {
  summary: () => get('/dashboard/summary'),
};

/* ---- Local AI infrastructure (Phase 8) — explanation layer only ---- */
export const aiApi = {
  health: () => client.get('/ai/health').then((r) => r.data).catch((e) => e.response?.data || { available: false, provider: 'ollama' }),
  generate: (prompt) => post('/ai/generate', { prompt }),
};

/* ---- Herman, the Financial Orchestrator Agent (Phase 9) ---- */
export const agentApi = {
  chat: (message, conversationId) =>
    post('/agent/chat', { message, ...(conversationId ? { conversation_id: conversationId } : {}) }),
};

/* ---- Savings goals (Phase 13) — the API surface only; goal progress,
   goal impact and recovery numbers are all computed by the backend. React
   only renders what the agent / these endpoints return. ---- */
export const goalsApi = {
  list: (status) => get('/goals', status ? { status } : undefined),
  get: (id) => get(`/goals/${id}`),
  create: (payload) => post('/goals', payload),
  update: (id, payload) => put(`/goals/${id}`, payload),
  remove: (id) => del(`/goals/${id}`),
  archive: (id) => del(`/goals/${id}?archive=1`),
};

/* ---- Portable Financial Profile export ----
   The backend builds a user-scoped, deterministic snapshot (JSON / Markdown /
   PDF). The frontend only chooses the period + format and saves the file —
   it never assembles or calculates report figures. */
export const reportsApi = {
  // returns { blob, filename } for a chosen format
  financialProfile: async ({ period = '3m', from, to, format = 'json' } = {}) => {
    const params = { period, format };
    if (period === 'custom') { params.from = from; params.to = to; }
    const res = await client.get('/reports/financial-profile', { params, responseType: 'blob' });
    const cd = res.headers['content-disposition'] || '';
    const m = /filename="?([^"]+)"?/.exec(cd);
    return { blob: res.data, filename: m ? m[1] : `financial-profile.${format === 'markdown' ? 'md' : format}` };
  },
};

/* ---- Bank SMS connection + review (Phase 15, review-only) ----
   The backend verifies the sender, extracts the transaction deterministically,
   and only creates a `needs_confirmation` event. Nothing enters the Financial
   Twin until the user confirms here. Raw SMS text is never stored or returned. */
export const bankApi = {
  connections: () => get('/bank/connections'),
  createConnection: (payload) => post('/bank/connections', payload),
  updateConnection: (id, payload) => put(`/bank/connections/${id}`, payload),
  rotateToken: (id) => post(`/bank/connections/${id}/rotate-token`),
  removeConnection: (id) => del(`/bank/connections/${id}`),
  events: (status) => get('/bank/sms-events', status ? { status } : undefined),
  // demo affordance: what a companion app / automation would POST automatically
  ingest: (sender, body) => post('/bank/sms-events', { sender, body }),
  editEvent: (id, payload) => client.patch(`/bank/sms-events/${id}`, payload).then((r) => r.data),
  confirmEvent: (id, payload) => post(`/bank/sms-events/${id}/confirm`, payload || {}),
  ignoreEvent: (id) => post(`/bank/sms-events/${id}/ignore`, {}),
};
