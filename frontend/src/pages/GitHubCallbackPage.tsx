import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

// The API finishes a GitHub sign-in by redirecting here with the session in
// the URL fragment, which never reaches a server.
function readFragment() {
  const params = new URLSearchParams(window.location.hash.slice(1));
  const token = params.get("token");
  const name = params.get("name");
  const expiresAt = params.get("expiresAt");
  return token && name && expiresAt ? { token, email: name, expiresAt } : null;
}

export function GitHubCallbackPage() {
  const { completeGitHubLogin } = useAuth();
  const navigate = useNavigate();
  // Read during render, before the effect wipes the fragment: StrictMode runs
  // effects twice in development, and the second run would otherwise find an
  // empty hash and report a sign-in that had in fact succeeded as a failure.
  const [session] = useState(readFragment);

  useEffect(() => {
    // Out of the address bar and the history entry, so the token is not left
    // somewhere it can be copied or bookmarked.
    window.history.replaceState(null, "", window.location.pathname);

    if (session === null) {
      navigate("/login?error=github", { replace: true });
      return;
    }
    completeGitHubLogin(session);
    navigate("/", { replace: true });
  }, [session]);

  return (
    <div className="page page-narrow">
      <p className="text-muted">Signing you in...</p>
    </div>
  );
}
