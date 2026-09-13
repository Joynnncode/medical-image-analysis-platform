import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { apiClient, setUnauthorizedHandler } from "../api/client";
import type { AuthResponse } from "../api/types";

interface AuthContextValue {
  email: string | null;
  isAuthenticated: boolean;
  /** True when the last session ended on its own rather than by logging out. */
  sessionExpired: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  guestLogin: () => Promise<void>;
  /** Keeps the session the API handed back at the end of a GitHub sign-in. */
  completeGitHubLogin: (data: AuthResponse) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function clearStoredSession() {
  localStorage.removeItem("token");
  localStorage.removeItem("email");
  localStorage.removeItem("expiresAt");
}

// The stored email is what keeps the app logged in across reloads, but the
// token behind it only lasts 12 hours. Without this check a month-old token
// still looked like a session: the app rendered as signed in and every API
// call came back 401.
function readStoredEmail(): string | null {
  const email = localStorage.getItem("email");
  if (email === null) return null;

  const expiresAt = localStorage.getItem("expiresAt");
  const expiry = expiresAt === null ? NaN : Date.parse(expiresAt);
  // Sessions stored before the expiry was recorded have no date to check; the
  // 401 handler still ends those on the first call.
  if (!Number.isNaN(expiry) && expiry <= Date.now()) {
    clearStoredSession();
    return null;
  }
  return email;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  // One initializer for both, because reading the session is what discards an
  // expired one: asking twice would lose the fact that there had been a
  // session at all, and with it the notice on the login page.
  const [{ email, sessionExpired }, setSession] = useState(() => {
    const hadSession = localStorage.getItem("email") !== null;
    const email = readStoredEmail();
    return { email, sessionExpired: hadSession && email === null };
  });

  useEffect(() => {
    setUnauthorizedHandler(() => {
      clearStoredSession();
      setSession({ email: null, sessionExpired: true });
    });
  }, []);

  const persistSession = (data: AuthResponse) => {
    localStorage.setItem("token", data.token);
    localStorage.setItem("email", data.email);
    localStorage.setItem("expiresAt", data.expiresAt);
    setSession({ email: data.email, sessionExpired: false });
  };

  const login = async (emailInput: string, password: string) => {
    const { data } = await apiClient.post<AuthResponse>("/auth/login", {
      email: emailInput,
      password,
    });
    persistSession(data);
  };

  const register = async (emailInput: string, password: string) => {
    const { data } = await apiClient.post<AuthResponse>("/auth/register", {
      email: emailInput,
      password,
    });
    persistSession(data);
  };

  const guestLogin = async () => {
    const { data } = await apiClient.post<AuthResponse>("/auth/guest");
    persistSession(data);
  };

  const logout = () => {
    clearStoredSession();
    setSession({ email: null, sessionExpired: false });
  };

  const value = useMemo(
    () => ({
      email,
      isAuthenticated: email !== null,
      sessionExpired,
      login,
      register,
      guestLogin,
      completeGitHubLogin: persistSession,
      logout,
    }),
    [email, sessionExpired]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
