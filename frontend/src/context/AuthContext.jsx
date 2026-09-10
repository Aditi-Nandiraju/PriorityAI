import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, setTokenGetter, setUnauthorizedHandler } from "../api.js";

const STORAGE_KEY = "priorityai.auth";
const AuthContext = createContext(null);

function loadStored() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }) {
  const navigate = useNavigate();
  const [auth, setAuth] = useState(loadStored); // { token, username, role } | null
  const tokenRef = useRef(auth?.token || null);
  tokenRef.current = auth?.token || null;

  // give the fetch wrapper a live view of the token + a 401 handler
  useEffect(() => {
    setTokenGetter(() => tokenRef.current);
    setUnauthorizedHandler(() => {
      localStorage.removeItem(STORAGE_KEY);
      setAuth(null);
      navigate("/login", { replace: true });
    });
  }, [navigate]);

  useEffect(() => {
    if (auth) localStorage.setItem(STORAGE_KEY, JSON.stringify(auth));
    else localStorage.removeItem(STORAGE_KEY);
  }, [auth]);

  const value = useMemo(
    () => ({
      token: auth?.token || null,
      username: auth?.username || null,
      role: auth?.role || null,
      isAuthenticated: !!auth?.token,
      isAdmin: auth?.role === "admin",
      async login(username, password) {
        const data = await api.post("/auth/login", { username, password }, { auth: false });
        setAuth({ token: data.access_token, username: data.username, role: data.role });
        return data;
      },
      logout() {
        setAuth(null);
        navigate("/login", { replace: true });
      },
    }),
    [auth, navigate]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
