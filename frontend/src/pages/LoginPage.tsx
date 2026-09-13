import axios from "axios";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { API_BASE_URL } from "../api/client";
import { wakeApi } from "../api/wakeApi";
import { useAuth } from "../context/AuthContext";

// An awake API answers /health in well under a second. Saying nothing until
// this has passed keeps the notice from flashing up on every visit.
const WAKE_NOTICE_DELAY_MS = 1500;

const GITHUB_ERRORS: Record<string, string> = {
  github: "GitHub sign-in did not complete. Please try again.",
  "github-unavailable": "GitHub sign-in is not set up on this server.",
};

function GitHubMark() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
    </svg>
  );
}

export function LoginPage() {
  const { login, guestLogin, sessionExpired } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(
    () => GITHUB_ERRORS[searchParams.get("error") ?? ""] ?? null
  );
  const [submitting, setSubmitting] = useState(false);
  const [guestLoading, setGuestLoading] = useState(false);
  const [apiWaking, setApiWaking] = useState(false);

  useEffect(() => {
    let settled = false;
    const timer = setTimeout(() => {
      if (!settled) setApiWaking(true);
    }, WAKE_NOTICE_DELAY_MS);

    wakeApi().finally(() => {
      settled = true;
      clearTimeout(timer);
      setApiWaking(false);
    });

    return () => clearTimeout(timer);
  }, []);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password);
      navigate("/");
    } catch (err) {
      const message = axios.isAxiosError(err) && typeof err.response?.data === "string"
        ? err.response.data
        : "Login failed. Check your credentials.";
      setError(message);
    } finally {
      setSubmitting(false);
    }
  };

  const handleGuest = async () => {
    setError(null);
    setGuestLoading(true);
    try {
      await guestLogin();
      navigate("/");
    } catch {
      setError("Couldn't start a guest session. Please try again.");
    } finally {
      setGuestLoading(false);
    }
  };

  return (
    <div className="page page-narrow">
      <div className="card">
        <h1 style={{ fontSize: "1.4rem", marginBottom: "1.5rem" }}>Log in</h1>
        {apiWaking && (
          <div className="notice">
            Waking the server. Free-tier hosting suspends it after about 15
            minutes idle, and starting it back up takes around 25 seconds.
            You can sign in now and it will go through once the server answers.
          </div>
        )}
        {error ? (
          <div className="form-error">{error}</div>
        ) : (
          sessionExpired && (
            <div className="form-error">Your session has expired. Please log in again.</div>
          )
        )}
        {/* A plain link rather than a request: GitHub sign-in is a chain of
            full-page redirects that ends back here on /auth/github. */}
        <a
          className="btn btn-primary btn-block"
          href={`${API_BASE_URL}/auth/github/login`}
        >
          <GitHubMark />
          Continue with GitHub
        </a>
        <button
          className="btn btn-block"
          type="button"
          onClick={handleGuest}
          disabled={guestLoading}
          style={{ marginTop: "0.75rem" }}
        >
          {guestLoading ? "Starting guest session..." : "Try it as a guest"}
        </button>
        <div className="auth-divider">or with email</div>
        <form onSubmit={handleSubmit}>
          <div className="form-field">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              className="input"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="form-field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              className="input"
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          <button className="btn btn-block" type="submit" disabled={submitting}>
            {submitting ? "Logging in..." : "Log in"}
          </button>
        </form>
        <p className="text-muted" style={{ marginTop: "1rem", fontSize: "0.9rem" }}>
          No account? <Link to="/register">Register</Link>
        </p>
      </div>
    </div>
  );
}
