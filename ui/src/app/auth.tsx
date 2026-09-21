// Auth context (feature 007, T012).
// Reads the bearer token (memory/sessionStorage), attaches it via the API
// client, surfaces 401/403 explanations (FR-013), and preserves wizard draft
// state across session expiry (FR-021).

import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { ApiClient, ControlPlaneApi, type AuthContext as AuthState } from "./api";

const TOKEN_KEY = "datafoundry.token";
const PROVIDER_KEY = "datafoundry.provider";
const DRAFT_PREFIX = "datafoundry.draft.";

function readAuth(): AuthState {
  if (typeof window === "undefined") {
    return { token: null, provider: null };
  }
  return {
    token: window.sessionStorage.getItem(TOKEN_KEY),
    provider: (window.sessionStorage.getItem(PROVIDER_KEY) as "aws" | "gcp" | null) || null,
  };
}

interface AuthApi {
  auth: AuthState;
  api: ControlPlaneApi;
  setToken: (token: string | null, provider?: "aws" | "gcp") => void;
  saveDraft: (key: string, value: unknown) => void;
  loadDraft: <T>(key: string) => T | null;
  clearDraft: (key: string) => void;
}

const AuthContext = createContext<AuthApi | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [auth, setAuth] = useState<AuthState>(readAuth);

  const client = useMemo(
    () => new ApiClient(import.meta.env.VITE_API_PREFIX || "/api/v1", auth),
    [auth],
  );
  const api = useMemo(() => new ControlPlaneApi(client), [client]);

  const setToken = useCallback((token: string | null, provider?: "aws" | "gcp") => {
    const next: AuthState = { token, provider: provider ?? null };
    setAuth(next);
    if (typeof window === "undefined") return;
    if (token) {
      window.sessionStorage.setItem(TOKEN_KEY, token);
      if (provider) window.sessionStorage.setItem(PROVIDER_KEY, provider);
    } else {
      window.sessionStorage.removeItem(TOKEN_KEY);
      window.sessionStorage.removeItem(PROVIDER_KEY);
    }
  }, []);

  const saveDraft = useCallback((key: string, value: unknown) => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(`${DRAFT_PREFIX}${key}`, JSON.stringify(value));
  }, []);

  const loadDraft = useCallback(<T,>(key: string): T | null => {
    if (typeof window === "undefined") return null;
    const raw = window.localStorage.getItem(`${DRAFT_PREFIX}${key}`);
    if (!raw) return null;
    try {
      return JSON.parse(raw) as T;
    } catch {
      return null;
    }
  }, []);

  const clearDraft = useCallback((key: string) => {
    if (typeof window === "undefined") return;
    window.localStorage.removeItem(`${DRAFT_PREFIX}${key}`);
  }, []);

  const value = useMemo(
    () => ({ auth, api, setToken, saveDraft, loadDraft, clearDraft }),
    [auth, api, setToken, saveDraft, loadDraft, clearDraft],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthApi {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}