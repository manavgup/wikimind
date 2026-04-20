import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../store/auth";
import { fetchCurrentUser } from "../../api/auth";
import { CompileAnimation } from "../landing/CompileAnimation";

export default function AuthCallback() {
  const navigate = useNavigate();
  const setUser = useAuth((s) => s.setUser);
  const [showAnimation, setShowAnimation] = useState(false);

  useEffect(() => {
    // The backend set an HttpOnly cookie before redirecting here.
    // Call /auth/me to validate the session and get the user profile.
    fetchCurrentUser()
      .then((user) => {
        setUser(user);
        setShowAnimation(true);
      })
      .catch(() => {
        navigate("/", { replace: true });
      });
  }, [setUser, navigate]);

  if (showAnimation) {
    return <CompileAnimation onComplete={() => navigate("/inbox", { replace: true })} />;

  return (
    <div className="flex min-h-screen items-center justify-center bg-white">
      <p className="text-slate-500">Signing in...</p>
    </div>
  );
}
