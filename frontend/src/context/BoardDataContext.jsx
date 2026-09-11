import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { useDemoMode } from "../hooks/useDemoMode.js";

const BoardDataContext = createContext(null);
const TOAST_LIFETIME_MS = 7000;
const REPLAY_POLL_MS = 3000;

/**
 * Holds the "live picture" (incidents, resource inventory, the allocation
 * plan, demo mode, toasts) ABOVE the routed pages, so it survives navigating
 * between Board / IncidentDetail / etc. instead of being reset every time a
 * page remounts. This is what fixes demo mode "unchecking itself" the moment
 * you click into an incident - before this, that state lived inside Board.jsx
 * and was torn down whenever you navigated away from it.
 */
export function BoardDataProvider({ children }) {
  const [incidents, setIncidents] = useState(null);
  const [resources, setResources] = useState(null); // {pools, inventory, committed, available}
  const [error, setError] = useState("");
  const [statusFilter, setStatusFilter] = useState("active");
  const [plan, setPlan] = useState(null);
  const [planStale, setPlanStale] = useState(false); // true = preview, false = committed run
  const [method, setMethod] = useState("optimal");
  const [busy, setBusy] = useState(false);

  const loadIncidents = useCallback(async () => {
    const q = statusFilter === "all" ? "" : `?status=${statusFilter}`;
    setIncidents(await api.get(`/incidents${q}`, { auth: false }));
  }, [statusFilter]);

  const loadResources = useCallback(async () => {
    setResources(await api.get("/resources", { auth: false }));
  }, []);

  const loadPreview = useCallback(async () => {
    setPlan(await api.get(`/simulate/preview?method=${method}`, { auth: false }));
    setPlanStale(true);
  }, [method]);

  // real, backend-driven refresh. Demo mode deliberately never calls this -
  // it would immediately overwrite the simulated state with real data.
  const refresh = useCallback(async () => {
    setError("");
    try {
      await Promise.all([loadIncidents(), loadResources(), loadPreview()]);
    } catch (err) {
      setError(err.message);
    }
  }, [loadIncidents, loadResources, loadPreview]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // --- toasts ---------------------------------------------------------------
  const [toasts, setToasts] = useState([]);
  const toastTimers = useRef({});

  const pushToast = useCallback((toast) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    setToasts((prev) => [...prev, { id, ...toast }]);
    toastTimers.current[id] = setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
      delete toastTimers.current[id];
    }, TOAST_LIFETIME_MS);
  }, []);

  const dismissToast = useCallback((id) => {
    clearTimeout(toastTimers.current[id]);
    delete toastTimers.current[id];
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  useEffect(
    () => () => {
      Object.values(toastTimers.current).forEach(clearTimeout);
    },
    []
  );

  // --- demo mode: operates on this exact incidents/resources state, so it
  // never disagrees with what's on screen, on whichever page you're viewing.
  const { demoMode, setDemoMode } = useDemoMode({
    incidents,
    setIncidents,
    resources,
    setResources,
    pushToast,
  });

  // --- live-feed replay: server-driven (app/replay.py), this is read-only
  // polling of /replay/status plus thin wrappers around start/stop. The
  // "SIMULATED" badge and cycle count come straight from the backend, so if
  // this browser tab reloads mid-loop the badge picks the real state back up.
  const [replayStatus, setReplayStatus] = useState(null);

  const pollReplayStatus = useCallback(async () => {
    try {
      setReplayStatus(await api.get("/replay/status", { auth: false }));
    } catch {
      // transient - next poll retries. Not worth surfacing as a page error.
    }
  }, []);

  useEffect(() => {
    pollReplayStatus();
    const id = setInterval(pollReplayStatus, REPLAY_POLL_MS);
    return () => clearInterval(id);
  }, [pollReplayStatus]);

  const startReplay = (compression) =>
    withBusy(async () => {
      setReplayStatus(await api.post(`/replay/start?compression=${compression}`));
    });

  const stopReplay = () =>
    withBusy(async () => {
      await api.post("/replay/stop");
      await pollReplayStatus();
    });

  async function withBusy(fn) {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const runAndLog = () =>
    withBusy(async () => {
      setPlan(await api.post(`/simulate?method=${method}`));
      setPlanStale(false);
    });

  // assigns to ONE incident only (the card the operator clicked)
  const quickAssign = (id, assigned) =>
    withBusy(async () => {
      await api.put(`/incidents/${id}/assignment`, { assigned });
      await refresh();
    });

  const value = {
    incidents,
    resources,
    error,
    statusFilter,
    setStatusFilter,
    plan,
    planStale,
    method,
    setMethod,
    busy,
    refresh,
    runAndLog,
    quickAssign,
    toasts,
    pushToast,
    dismissToast,
    demoMode,
    setDemoMode,
    replayStatus,
    startReplay,
    stopReplay,
  };

  return <BoardDataContext.Provider value={value}>{children}</BoardDataContext.Provider>;
}

export function useBoardData() {
  const ctx = useContext(BoardDataContext);
  if (!ctx) throw new Error("useBoardData must be used inside <BoardDataProvider>");
  return ctx;
}
