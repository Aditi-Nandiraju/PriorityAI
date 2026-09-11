import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api.js";
import { useAuth } from "../context/AuthContext.jsx";
import IncidentCard from "../components/IncidentCard.jsx";
import ResourceStrip from "../components/ResourceStrip.jsx";

const UNDER_RESOURCED = new Set(["PARTIALLY_RESOURCED", "UNRESOURCED"]);

export default function Board() {
  const { isAuthenticated } = useAuth();
  const [incidents, setIncidents] = useState(null);
  const [error, setError] = useState("");
  const [statusFilter, setStatusFilter] = useState("active");
  const [plan, setPlan] = useState(null);
  const [planStale, setPlanStale] = useState(false); // true = preview, false = committed run
  const [method, setMethod] = useState("optimal");
  const [busy, setBusy] = useState(false);
  const [onlyUnder, setOnlyUnder] = useState(false);

  const loadIncidents = useCallback(async () => {
    const q = statusFilter === "all" ? "" : `?status=${statusFilter}`;
    setIncidents(await api.get(`/incidents${q}`, { auth: false }));
  }, [statusFilter]);

  const loadPreview = useCallback(async () => {
    setPlan(await api.get(`/simulate/preview?method=${method}`, { auth: false }));
    setPlanStale(true);
  }, [method]);

  const refresh = useCallback(async () => {
    setError("");
    try {
      await Promise.all([loadIncidents(), loadPreview()]);
    } catch (err) {
      setError(err.message);
    }
  }, [loadIncidents, loadPreview]);

  useEffect(() => {
    refresh();
  }, [refresh]);

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

  const statusById = useMemo(() => {
    const m = {};
    for (const a of plan?.allocations || []) m[a.incident_id] = a;
    return m;
  }, [plan]);

  const visible = useMemo(() => {
    if (!incidents) return null;
    if (!onlyUnder) return incidents;
    return incidents.filter((inc) => UNDER_RESOURCED.has(statusById[inc.id]?.status));
  }, [incidents, onlyUnder, statusById]);

  const underCount = incidents
    ? incidents.filter((inc) => UNDER_RESOURCED.has(statusById[inc.id]?.status)).length
    : 0;

  return (
    <div>
      <div className="page-head">
        <h2>Incident Board</h2>
        <div className="controls">
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="active">Active</option>
            <option value="all">All</option>
            <option value="resolved">Resolved</option>
          </select>
          <button className="btn ghost" onClick={refresh} disabled={busy}>
            Refresh
          </button>
        </div>
      </div>

      <ResourceStrip remaining={plan?.remaining_inventory} />

      <div className="card sim-panel">
        <div className="sim-head">
          <strong>Allocation simulation</strong>
          <div className="controls">
            <label className="inline">
              Method
              <select value={method} onChange={(e) => setMethod(e.target.value)}>
                <option value="optimal">optimal (ILP)</option>
                <option value="greedy">greedy</option>
              </select>
            </label>
            <button className="btn ghost" onClick={runAndLog} disabled={busy}>
              Run &amp; log
            </button>
          </div>
        </div>

        {plan && (
          <div className="sim-result">
            <div className="sim-summary">
              <Stat label="fully" value={plan.summary.fully_resourced} tone="ok" />
              <Stat label="partial" value={plan.summary.partially_resourced} tone="warn" />
              <Stat label="unresourced" value={plan.summary.unresourced} tone="bad" />
              <Stat label="response gaps" value={plan.summary.response_gaps} tone="bad" />
              {plan.solver && (
                <span className="muted small">
                  solver: {plan.solver.status} · objective {Math.round(plan.solver.objective)}
                </span>
              )}
              <span className="muted small">
                {planStale ? "live preview (not logged)" : "committed run"}
              </span>
            </div>
            <table className="sim-table">
              <thead>
                <tr>
                  <th>Priority</th>
                  <th>Type</th>
                  <th>Severity</th>
                  <th>Status</th>
                  <th>Shortage</th>
                </tr>
              </thead>
              <tbody>
                {plan.allocations.map((a) => (
                  <tr key={a.incident_id} className={`alloc-${a.status}`}>
                    <td>{a.priority_score}</td>
                    <td>{a.incident_type.replace(/_/g, " ")}</td>
                    <td>{a.severity_class}</td>
                    <td>{a.status.replace(/_/g, " ").toLowerCase()}</td>
                    <td className="muted">
                      {Object.entries(a.shortages || {})
                        .map(([k, v]) => `${k}:${v}`)
                        .join(", ") || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {error && <div className="alert error">{error}</div>}

      <div className="board-controls">
        <label className="checkbox">
          <input
            type="checkbox"
            checked={onlyUnder}
            onChange={(e) => setOnlyUnder(e.target.checked)}
          />
          Show only under-resourced
        </label>
        <span className={`under-count ${underCount ? "has" : ""}`}>
          {underCount} of {incidents?.length ?? 0} under-resourced ({method})
        </span>
      </div>

      {!visible ? (
        <p className="muted">loading incidents…</p>
      ) : visible.length === 0 ? (
        <p className="muted">
          {onlyUnder ? "No under-resourced incidents." : "No incidents. Create one under Ingest → Single Entry."}
        </p>
      ) : (
        <div className="incident-grid">
          {visible.map((inc) => (
            <IncidentCard
              key={inc.id}
              incident={inc}
              allocation={statusById[inc.id]}
              canAssign={isAuthenticated}
              busy={busy}
              onQuickAssign={quickAssign}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, tone }) {
  return (
    <span className={`stat stat-${tone}`}>
      <strong>{value}</strong> {label}
    </span>
  );
}
