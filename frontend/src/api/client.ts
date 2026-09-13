import axios from "axios";

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:5283/api";

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
});

apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem("token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Tokens last 12 hours and the API answers 401 on every route once one has
// expired. Nothing used to watch for that, so a stale session read as a
// broken app: the page still looked logged in and every call failed.
let onUnauthorized: (() => void) | null = null;

export function setUnauthorizedHandler(handler: () => void) {
  onUnauthorized = handler;
}

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    // /auth/* answers 401 for bad credentials too; that is the login form's
    // to report, not an expired session.
    const isAuthCall = error.config?.url?.startsWith("/auth") ?? false;
    if (axios.isAxiosError(error) && error.response?.status === 401 && !isAuthCall) {
      onUnauthorized?.();
    }
    return Promise.reject(error);
  }
);
