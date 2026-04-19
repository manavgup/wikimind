import { useEffect, useState } from "react";
import { useAuth } from "../../store/auth";
import { fetchCurrentUser } from "../../api/auth";
import { ApiError } from "../../api/client";

export default function AuthProvider({ children }: { children: React.ReactNode }) {
  const token = useAuth((s) => s.token);
  const setToken = useAuth((s) => s.setToken);
  const setUser = useAuth((s) => s.setUser);
  const setAuthDisabled = useAuth((s) => s.setAuthDisabled);
  const logout = useAuth((s) => s.logout);
  const [ready, setReady] = useState(false);

  // Extract token from URL query string (OAuth callback redirects to /?token=...)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const urlToken = params.get("token");
    if (urlToken) {
      setToken(urlToken);
      // Clean the URL
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, [setToken]);

  useEffect(() => {
    if (!token) {
      // No token — probe /auth/me to check if auth is even enabled.
      fetchCurrentUser()
        .then((user) => {
          // Auth disabled on backend — user returned without token.
          setUser(user);
          setAuthDisabled(true);
          setReady(true);
        })
        .catch((err) => {
          if (err instanceof ApiError && err.status === 401) {
            // 401 = auth is enabled, user needs to log in.
            setReady(true);
          } else {
            // Network error or 404 = auth endpoint doesn't exist (disabled).
            setAuthDisabled(true);
            setReady(true);
          }
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
