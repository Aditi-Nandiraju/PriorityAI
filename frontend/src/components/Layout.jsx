import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";
import { NAV } from "../nav.js";

export default function Layout() {
  const { username, role, logout } = useAuth();
  const tabs = NAV.filter((t) => t.roles.includes(role));

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          PriorityAI <span className="tag">decision support</span>
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
