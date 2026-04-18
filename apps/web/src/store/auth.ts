// Zustand store for OAuth2 authentication state.
//
// Persists the JWT token in localStorage so sessions survive page reloads.

import { create } from "zustand";

export interface AuthUser {
  id: string;
  email: string;
  name: string | null;
  avatar_url: string | null;
}

interface AuthState {
  token: string | null;
  user: AuthUser | null;
  isAuthenticated: boolean;
  authDisabled: boolean;
  setToken: (token: string) => void;
  setUser: (user: AuthUser) => void;
  setAuthDisabled: (disabled: boolean) => void;
  logout: () => void;
}

export const useAuth = create<AuthState>((set) => ({
  token: localStorage.getItem("wikimind_token"),
  user: null,
  isAuthenticated: !!localStorage.getItem("wikimind_token"),
  authDisabled: false,
  setToken: (token) => {
    localStorage.setItem("wikimind_token", token);
    set({ token, isAuthenticated: true });
  },
  setUser: (user) => set({ user }),
  setAuthDisabled: (disabled) => set({ authDisabled: disabled }),
  logout: () => {
    localStorage.removeItem("wikimind_token");
    set({ token: null, user: null, isAuthenticated: false });
  },
}));
