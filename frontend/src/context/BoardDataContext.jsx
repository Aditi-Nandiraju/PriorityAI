import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { useAuth } from "./AuthContext.jsx";
import { useDemoMode } from "../hooks/useDemoMode.js";

const BoardDataContext = createContext(null);
const TOAST_LIFETIME_MS = 7000;
const REPLAY_POLL_MS = 3000;
const NOTIFY_POLL_MS = 4000; // server already scopes this to resources/assignment actions

const fmtType = (s) => (s || "").replace(/_/g, " ");

// Humanises one GET /notifications row (same shape as an audit_log entry).
function formatNotification(n) {
  const d = n.details || {};
  switch (n.action) {
    case "resources:create":
      return `${n.username} added a new ${fmtType(d.resource_type)} pool (${d.quantity})`;
    case "resources:update": {
      const changes = Object.entries(d.changes || {})
        .map(([k, v]) => `${k} → ${v}`)
        .join(", ");
      return `${n.username} updated ${fmtType(d.resource_type)}: ${changes}`;
    }
    case "incidents:assign": {
      const assigned = Object.entries(d.assigned || {});
      const incType = fmtType(d.incident_type) || "an incident";
      if (assigned.length === 0) {
        return `${n.username} cleared the resource assignment on ${incType}`;
      }
      const summary = assigned.map(([k, v]) => `${v}× ${fmtType(k)}`).join(", ");
      return `${n.username} assigned ${summary} to ${incType}`;
    }
    default:
      return `${n.username} ${n.action}`;
  }
}

/**
 * Holds the "live picture" (incidents, resource inventory, the allocation
 * plan, demo mode, toasts) ABOVE the routed pages, so it survives navigating
 * between Board / IncidentDetail / etc. instead of being reset every time a
 * page remounts. This is what fixes demo mode "unchecking itself" the moment
 * you click into an incident - before this, that state lived inside Board.jsx
 * and was torn down whenever you navigated away from it.
 */
export function BoardDataProvider({ children }) {
  const { username } = useAuth();
  const [incidents, setIncidents] = useState(null);
  const [resources, setResources] = useState(null); // {pools, inventory, committed, available}
  const [error, setError] = useState("");
  // Defaults to "all", not "active": resolved incidents need to actually be
  // visible (greyed, sunk to the end - see Board.jsx) for that to read as an
  // indication of anything. Under "active only" they'd just vanish instead of
  // showing as resolved, which looks like nothing happened.
  const [statusFilter, setStatusFilter] = useState("all");
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

  // --- cross-operator notifications: two people, two localhosts, one shared
  // Atlas database. Poll GET /notifications (resource + assignment changes
  // only) and toast anything new that someone ELSE did, then pull fresh
  // incidents/resources so this tab's numbers actually match what they did -
  // a toast with stale numbers behind it would be worse than no toast.
  const seenNotificationIds = useRef(null); // null = haven't seeded the backlog yet

  const pollNotifications = useCallback(async () => {
    let recent;
    try {
      recent = await api.get("/notifications?limit=20");
    } catch {
      return; // transient - next poll retries
    }
    if (seenNotificationIds.current === null) {
      // first poll ever: mark existing history as seen, don't toast a backlog
      seenNotificationIds.current = new Set(recent.map((n) => n.id));
      return;
    }
    const fresh = recent.filter((n) => !seenNotificationIds.current.has(n.id)).reverse();
    if (fresh.length === 0) return;

    let peerChange = false;
    for (const n of fresh) {
      seenNotificationIds.current.add(n.id);
      if (n.username !== username) {
        pushToast({ kind: "peer", text: formatNotification(n) });
        peerChange = true;
      }
    }
    if (peerChange) refresh();
  }, [username, pushToast, refresh]);

  useEffect(() => {
    pollNotifications();
    const id = setInterval(pollNotifications, NOTIFY_POLL_MS);
    return () => clearInterval(id);
  }, [pollNotifications]);

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

  // brings a resolved incident back to active - a correction, not a fake
  // resolution, so (unlike marking resolved) this stays a plain manual action
  const reopenIncident = (id) =>
    withBusy(async () => {
      await api.post(`/incidents/${id}/status`, { status: "active" });
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
    reopenIncident,
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
