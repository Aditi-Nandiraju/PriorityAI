import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout.jsx";
import ProtectedRoute from "./components/ProtectedRoute.jsx";
import Login from "./pages/Login.jsx";
import Ingest from "./pages/Ingest.jsx";
import Board from "./pages/Board.jsx";
import IncidentDetail from "./pages/IncidentDetail.jsx";
import Resources from "./pages/Resources.jsx";
import ActivityLog from "./pages/ActivityLog.jsx";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />

      <Route element={<ProtectedRoute />}>
        <Route element={<Layout />}>
          <Route index element={<Navigate to="/board" replace />} />
          <Route path="/ingest" element={<Ingest />} />
          <Route path="/board" element={<Board />} />
          <Route path="/incident/:id" element={<IncidentDetail />} />
          <Route path="/resources" element={<Resources />} />
          <Route
            path="/activity"
            element={
              <ProtectedRoute requireAdmin>
                <ActivityLog />
              </ProtectedRoute>
            }
          />
        </Route>
      </Route>

      <Route path="*" element={<Navigate to="/board" replace />} />
    </Routes>
  );
}
