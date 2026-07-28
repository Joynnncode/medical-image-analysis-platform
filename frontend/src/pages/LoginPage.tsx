import axios from "axios";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export function LoginPage() {
  const { login, guestLogin } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [guestLoading, setGuestLoading] = useState(false);

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
        {error && <div className="form-error">{error}</div>}
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
          <button className="btn btn-primary" type="submit" disabled={submitting} style={{ width: "100%" }}>
            {submitting ? "Logging in..." : "Log in"}
          </button>
        </form>
        <button
          className="btn"
          type="button"
          onClick={handleGuest}
          disabled={guestLoading}
          style={{ width: "100%", marginTop: "0.75rem" }}
        >
          {guestLoading ? "Starting guest session..." : "Try it as a guest"}
        </button>
        <p className="text-muted" style={{ marginTop: "1rem", fontSize: "0.9rem" }}>
          No account? <Link to="/register">Register</Link>
        </p>
      </div>
    </div>
  );
}
