import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { apiClient } from "../api/client";
import type { AuthResponse } from "../api/types";

interface AuthContextValue {
  email: string | null;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  guestLogin: () => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [email, setEmail] = useState<string | null>(() => localStorage.getItem("email"));

  const persistSession = (data: AuthResponse) => {
    localStorage.setItem("token", data.token);
    localStorage.setItem("email", data.email);
    setEmail(data.email);
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
    localStorage.removeItem("token");
    localStorage.removeItem("email");
    setEmail(null);
  };

  const value = useMemo(
    () => ({ email, isAuthenticated: email !== null, login, register, guestLogin, logout }),
    [email]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
