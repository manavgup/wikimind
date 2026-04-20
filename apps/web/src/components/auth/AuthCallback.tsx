import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../store/auth";
import { fetchCurrentUser } from "../../api/auth";

export default function AuthCallback() {
  const navigate = useNavigate();
  const setUser = useAuth((s) => s.setUser);

  useEffect(() => {
    // The backend set an HttpOnly cookie before redirecting here.
    // Call /auth/me to validate the session and get the user profile.
    fetchCurrentUser()
      .then((user) => {
        setUser(user);
        navigate("/", { replace: true });
      })
      .catch(() => {
        navigate("/login", { replace: true });
      });
  }, [setUser, navigate]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-white">
      <p className="text-slate-500">Signing in...</p>
    </div>
  );
}
