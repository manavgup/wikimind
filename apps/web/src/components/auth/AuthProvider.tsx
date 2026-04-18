import { useEffect, useState } from "react";
import { useAuth } from "../../store/auth";
import { fetchCurrentUser } from "../../api/auth";

export default function AuthProvider({ children }: { children: React.ReactNode }) {
  const token = useAuth((s) => s.token);
  const setUser = useAuth((s) => s.setUser);
  const setAuthDisabled = useAuth((s) => s.setAuthDisabled);
  const logout = useAuth((s) => s.logout);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!token) {
      // No token — probe /auth/me to check if auth is even enabled.
      fetchCurrentUser()
        .then((user) => {
          setUser(user);
          setReady(true);
        })
        .catch(() => {
          // 404 or network error means auth is disabled on the backend.
          setAuthDisabled(true);
          setReady(true);
        });
      return;
    }

    // Token exists — validate it.
    fetchCurrentUser()
      .then((user) => {
        setUser(user);
        setReady(true);
      })
      .catch(() => {
        logout();
        setReady(true);
      });
  }, [token, setUser, setAuthDisabled, logout]);

  if (!ready) {
    return <div className="min-h-screen bg-zinc-950" />;
  }

  return <>{children}</>;
}
