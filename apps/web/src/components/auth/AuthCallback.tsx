import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../store/auth";

export default function AuthCallback() {
  const navigate = useNavigate();
  const setToken = useAuth((s) => s.setToken);

  useEffect(() => {
    const hash = window.location.hash.substring(1);
    const params = new URLSearchParams(hash);
    const token = params.get("token");
    if (token) {
      setToken(token);
      navigate("/", { replace: true });
    } else {
      navigate("/login", { replace: true });
    }
  }, [setToken, navigate]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-zinc-950">
      <p className="text-zinc-400">Signing in...</p>
    </div>
  );
}
