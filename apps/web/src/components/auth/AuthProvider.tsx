import { useEffect, useState } from "react";
import { useAuth } from "../../store/auth";
import { fetchCurrentUser } from "../../api/auth";
import { ApiError } from "../../api/client";

export default function AuthProvider({ children }: { children: React.ReactNode }) {
  const setUser = useAuth((s) => s.setUser);
  const setAuthDisabled = useAuth((s) => s.setAuthDisabled);
  const logout = useAuth((s) => s.logout);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    // Probe /auth/me — the HttpOnly cookie (if present) is sent automatically.
    fetchCurrentUser()
      .then((user) => {
        if (user.id === "anonymous") {
          // Auth disabled on backend — anonymous stub returned.
          setAuthDisabled(true);
        } else {
          setUser(user);
        }
        setReady(true);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          // Auth is enabled but no valid session — user needs to log in.
          logout();
        } else {
          // Network error or auth endpoint doesn't exist — treat as disabled.
          setAuthDisabled(true);
        }
        setReady(true);
      });
  }, [setUser, setAuthDisabled, logout]);

  if (!ready) {
    return <div className="min-h-screen bg-white" />;
  }

  return <>{children}</>;
}
