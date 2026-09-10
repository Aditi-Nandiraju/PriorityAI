import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";

// Usable two ways:
//   <Route element={<ProtectedRoute />}> ... nested routes ... </Route>
//   <ProtectedRoute requireAdmin><Page /></ProtectedRoute>
export default function ProtectedRoute({ children, requireAdmin = false }) {
  const { isAuthenticated, isAdmin } = useAuth();
  const location = useLocation();

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  if (requireAdmin && !isAdmin) {
    return <Navigate to="/board" replace />;
  }
  return children ? children : <Outlet />;
}
