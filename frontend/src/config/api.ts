/** Same-origin API by default; set VITE_API_BASE_URL only when frontend and API are on different hosts. */
export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
export const HAS_BACKEND = true;

export const ENDPOINTS = {
  login: "/api/auth/login", register: "/api/auth/register", me: "/api/auth/me", logout: "/api/auth/logout",
  changePassword: "/api/auth/change-password", summary: "/api/summary", invoicesOpen: "/api/invoices/open",
  paymentsHistory: "/api/payments/history", predictions: "/api/predictions", priority: "/api/f3/priority",
  forecast: "/api/forecast", candidates: "/api/reminders/candidates", drafts: "/api/reminders/drafts",
  tasks: "/api/tasks", team: "/api/team", users: "/api/admin/users", customers: "/api/admin/customers",
  audit: "/api/admin/audit",
  // No AI endpoint or manual obligations endpoint exists in the current backend.
  aiDraft: "/api/ai/draft", aiSummary: "/api/ai/summary", aiHealth: "/api/ai/health",
} as const;

export const apiUrl = (path: string) => API_BASE_URL + path;
