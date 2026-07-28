import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export function NavBar() {
  const { email, isAuthenticated, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  return (
    <nav className="navbar">
      <Link to="/" className="navbar-brand">
        <span className="dot" />
        Medical Image Analysis
      </Link>
      <div className="navbar-links">
        {isAuthenticated ? (
          <>
            <Link to="/research/ich-segmentation" className="navbar-link">
              Research
            </Link>
            <span className="navbar-email">{email}</span>
            <button className="btn" onClick={handleLogout}>
              Log out
            </button>
          </>
        ) : (
          <Link to="/login" className="btn">
            Log in
          </Link>
        )}
      </div>
    </nav>
  );
}
