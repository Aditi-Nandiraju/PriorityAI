import { useMemo, useState } from "react";
import { useAuth } from "../context/AuthContext.jsx";
import { useBoardData } from "../context/BoardDataContext.jsx";
import IncidentCard from "../components/IncidentCard.jsx";
import ResourceStrip from "../components/ResourceStrip.jsx";

const UNDER_RESOURCED = new Set(["PARTIALLY_RESOURCED", "UNRESOURCED"]);

export default function Board() {
  const { isAuthenticated } = useAuth();
  const {
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
    demoMode,
    setDemoMode,
    replayStatus,
    startReplay,
    stopReplay,
  } = useBoardData();

  const [compression, setCompression] = useState(60);
  const [onlyUnder, setOnlyUnder] = useState(false); // filters the incident CARDS below
  const [simCollapsed, setSimCollapsed] = useState(false); // collapses the sim panel's details
  const [simOnlyUnder, setSimOnlyUnder] = useState(false); // filters the sim panel's TABLE rows

  const statusById = useMemo(() => {
    const m = {};
    for (const a of plan?.allocations || []) m[a.incident_id] = a;
    return m;
  }, [plan]);

  // Re-apply the status filter client-side too (not just via the server query
  // that fetched `incidents`): local state can now change without a refetch -
  // e.g. demo mode resolving an incident - so an "Active" view must stop
  // showing something the moment its local status flips to resolved.
  const visible = useMemo(() => {
    if (!incidents) return null;
    let list = incidents;
    if (statusFilter !== "all") {
      list = list.filter((inc) => inc.status === statusFilter);
    }
    if (onlyUnder) {
      list = list.filter((inc) => UNDER_RESOURCED.has(statusById[inc.id]?.status));
    }
    return list;
  }, [incidents, statusFilter, onlyUnder, statusById]);

  const underCount = incidents
    ? incidents.filter(
        (inc) => inc.status === "active" && UNDER_RESOURCED.has(statusById[inc.id]?.status)
      ).length
    : 0;

  const simRows = useMemo(() => {
    if (!plan) return [];
    return simOnlyUnder ? plan.allocations.filter((a) => UNDER_RESOURCED.has(a.status)) : plan.allocations;
  }, [plan, simOnlyUnder]);

  return (
    <div>
      <div className="page-head">
        <h2>Incident Board</h2>
        <div className="controls">
          <label
            className="inline demo-toggle"
            title="Client-side placeholder: periodically resolves a fully-resourced incident and releases its resources, for presentation purposes only."
          >
            <input
              type="checkbox"
              checked={demoMode}
              onChange={(e) => setDemoMode(e.target.checked)}
            />
            Demo mode
          </label>
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

      {isAuthenticated && (
        <div className="card live-feed-panel">
          <div className="sim-head">
            <div className="sim-title">
              <strong>Live feed replay</strong>
              <span className="muted small">
                drips data/replay/*.csv into Reports, realistically paced, loops forever
              </span>
            </div>
            <div className="controls">
              {replayStatus?.running ? (
                <>
                  <span className="muted small">
                    cycle {replayStatus.cycle} · {replayStatus.reports_ingested_this_cycle}/
                    {replayStatus.total_reports_per_cycle} this cycle · compression{" "}
                    {replayStatus.compression_factor}×
                  </span>
                  <button className="btn ghost" onClick={stopReplay} disabled={busy}>
                    Stop
                  </button>
                </>
              ) : (
                <>
                  <label className="inline">
                    compression
                    <input
                      type="number"
                      min="1"
                      className="qty"
                      value={compression}
                      onChange={(e) => setCompression(Number(e.target.value))}
                    />
                  </label>
                  <button className="btn primary" onClick={() => startReplay(compression)} disabled={busy}>
                    Start live feed
                  </button>
                </>
              )}
            </div>
          </div>
          {replayStatus?.error && <div className="alert error">replay stopped: {replayStatus.error}</div>}
        </div>
      )}

      <ResourceStrip resources={resources} />

      <div className="card sim-panel">
        <div className="sim-head">
          <div className="sim-title">
            <button
              className="btn ghost xs sim-collapse-btn"
              onClick={() => setSimCollapsed((v) => !v)}
              aria-expanded={!simCollapsed}
              title={simCollapsed ? "Expand" : "Collapse"}
            >
              {simCollapsed ? "▸" : "▾"}
            </button>
            <strong>Allocation simulation</strong>
          </div>
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

        {!simCollapsed && plan && (
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
              <label className="checkbox small sim-only-under">
                <input
                  type="checkbox"
                  checked={simOnlyUnder}
                  onChange={(e) => setSimOnlyUnder(e.target.checked)}
                />
                only under-resourced
              </label>
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
                {simRows.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="muted">
                      No under-resourced incidents in this plan.
                    </td>
                  </tr>
                ) : (
                  simRows.map((a) => (
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
                  ))
                )}
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
