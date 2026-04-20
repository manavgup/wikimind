// Zustand store for authentication state.
//
// Session is managed via HttpOnly cookies — the frontend never touches
// the JWT directly. Auth state is determined by calling /auth/me on mount.

import { create } from "zustand";

export interface AuthUser {
  id: string;
  email: string;
  name: string | null;
  avatar_url: string | null;
}

interface AuthState {
  user: AuthUser | null;
  isAuthenticated: boolean;
  authDisabled: boolean;
  setUser: (user: AuthUser) => void;
  setAuthDisabled: (disabled: boolean) => void;
  logout: () => void;
}

export const useAuth = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: false,
  authDisabled: false,
  setUser: (user) => set({ user, isAuthenticated: true }),
  setAuthDisabled: (disabled) => set({ authDisabled: disabled }),
  logout: () => {
    set({ user: null, isAuthenticated: false });
  },
}));
