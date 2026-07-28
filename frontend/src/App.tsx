import { Navigate, Route, BrowserRouter as Router, Routes } from "react-router-dom";
import "./App.css";
import { NavBar } from "./components/NavBar";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { AuthProvider } from "./context/AuthContext";
import { DashboardPage } from "./pages/DashboardPage";
import { LoginPage } from "./pages/LoginPage";
import { RegisterPage } from "./pages/RegisterPage";
import { ResearchPage } from "./pages/ResearchPage";
import { ScanDetailPage } from "./pages/ScanDetailPage";

function App() {
  return (
    <AuthProvider>
      <Router>
        <div className="app-shell">
          <NavBar />
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
            <Route
              path="/"
              element={
                <ProtectedRoute>
                  <DashboardPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/scans/:id"
              element={
                <ProtectedRoute>
                  <ScanDetailPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/research/ich-segmentation"
              element={
                <ProtectedRoute>
                  <ResearchPage />
                </ProtectedRoute>
              }
            />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </div>
      </Router>
    </AuthProvider>
  );
}

export default App;
