import { Navigate } from "react-router-dom";
import { useAuth } from "../../store/auth";

/** Shows children (landing page) for unauthenticated users; redirects to /inbox otherwise. */
export function LandingRoute({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuth((s) => s.isAuthenticated);
  const authDisabled = useAuth((s) => s.authDisabled);

  if (authDisabled || isAuthenticated) {
    return <Navigate to="/inbox" replace />;
  }

  return <>{children}</>;
}
