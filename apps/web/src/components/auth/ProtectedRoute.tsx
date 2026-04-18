import { Navigate } from "react-router-dom";
import { useAuth } from "../../store/auth";

export default function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuth((s) => s.isAuthenticated);
  const authDisabled = useAuth((s) => s.authDisabled);

  if (authDisabled || isAuthenticated) {
    return <>{children}</>;
  }

  return <Navigate to="/login" replace />;
}
