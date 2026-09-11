import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";
import { useBoardData } from "../context/BoardDataContext.jsx";
import { NAV } from "../nav.js";
import Toaster from "./Toaster.jsx";

export default function Layout() {
  const { username, role, logout } = useAuth();
  const { demoMode, toasts, dismissToast, replayStatus } = useBoardData();
  const tabs = NAV.filter((t) => t.roles.includes(role));

  return (
    <div className="shell">
      {/* lives here (not on Board) so a demo-mode toast still shows up even
          while you're looking at an incident, resources, etc. */}
      <Toaster toasts={toasts} onDismiss={dismissToast} />

      <header className="topbar">
        <div className="brand">
          PriorityAI <span className="tag">decision support</span>
          {demoMode && <span className="demo-pill">DEMO MODE</span>}
          {replayStatus?.running && (
            <span className="live-feed-pill" title="Reports are dripping in from a looping demo dataset, not real operators.">
              Live feed — cycle {replayStatus.cycle}
            </span>
          )}
        </div>
        <nav className="tabs">
          {tabs.map((t) => (
            <NavLink
              key={t.to}
              to={t.to}
              className={({ isActive }) => (isActive ? "tab active" : "tab")}
            >
              {t.label}
            </NavLink>
          ))}
        </nav>
        <div className="user">
          <span className="who">
            {username} <span className={`role role-${role}`}>{role}</span>
          </span>
          <button className="btn ghost" onClick={logout}>
            Sign out
          </button>
        </div>
      </header>
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
