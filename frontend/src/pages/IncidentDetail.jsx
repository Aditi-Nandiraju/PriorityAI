import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api.js";
import { useAuth } from "../context/AuthContext.jsx";

export default function IncidentDetail() {
  const { id } = useParams();
  const [inc, setInc] = useState(null);
  const [error, setError] = useState("");

  const loadIncident = useCallback(() => {
    setError("");
    api
      .get(`/incidents/${id}`, { auth: false })
      .then(setInc)
      .catch((e) => setError(e.message));
  }, [id]);

  useEffect(() => {
    loadIncident();
  }, [loadIncident]);

  if (error) return <div className="alert error">{error}</div>;
  if (!inc) return <p className="muted">loading…</p>;

  const bd = inc.severity_breakdown || {};
  const contributions = bd.contributions || {};

  return (
    <div className="detail">
      <Link to="/board" className="back">
        ← Board
      </Link>
      <div className="page-head">
        <h2>
          <span className={`sev-badge sev-${inc.severity_class}`}>{inc.severity_class}</span>{" "}
          {inc.incident_type.replace(/_/g, " ")}
        </h2>
        <span className={`chip status-${inc.status}`}>{inc.status}</span>
      </div>

      <div className="detail-grid">
        <Field label="Location" value={inc.location || "—"} />
        <Field label="Priority score" value={inc.priority_score} />
        <Field label="Severity score" value={`${inc.severity_score} / ${bd.raw_sum ?? inc.severity_score}`} />
        <Field label="Confidence score" value={inc.confidence_score} />
        <Field label="Source" value={inc.source || "—"} />
        <Field label="Created by" value={inc.created_by || "—"} />
        <Field label="Created at" value={fmt(inc.created_at)} />
      </div>

      <AllocationCard incident={inc} onChange={loadIncident} />

      <div className="card">
        <h3>Severity breakdown</h3>
        {Object.keys(contributions).length === 0 ? (
          <p className="muted">No structural flags set.</p>
        ) : (
          <ul className="contrib-list">
            {Object.entries(contributions)
              .sort((a, b) => b[1] - a[1])
              .map(([k, v]) => (
                <li key={k}>
                  <span>{k.replace(/_/g, " ")}</span>
                  <span className="muted">+{v}</span>
                </li>
              ))}
          </ul>
        )}
        {bd.clamped && <p className="muted small">score clamped to 100 (raw sum {bd.raw_sum})</p>}
      </div>

      {inc.confidence_inputs && (
        <div className="card">
          <h3>Confidence inputs</h3>
          <pre className="result-json">{JSON.stringify(inc.confidence_inputs, null, 2)}</pre>
        </div>
      )}

      {inc.notes && (
        <div className="card">
          <h3>Notes</h3>
          <p>{inc.notes}</p>
        </div>
      )}

      <details className="card">
        <summary>Raw record</summary>
        <pre className="result-json">{JSON.stringify(inc, null, 2)}</pre>
      </details>
    </div>
  );
}

// Requirement · AI suggestion · who else is competing for the same resources ·
// the operator's own committed assignment (which they can override). Resolving
// the incident releases its resources back to the pool.
function AllocationCard({ incident, onChange }) {
  const { isAuthenticated } = useAuth();
  const id = incident.id;
  const [method, setMethod] = useState("optimal");
  const [con, setCon] = useState(null);
  const [draft, setDraft] = useState({}); // {resource_type: qty} the operator is editing
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [openType, setOpenType] = useState(null);

  const load = useCallback(() => {
    setErr("");
    api
      .get(`/incidents/${id}/contention?method=${method}`, { auth: false })
      .then((c) => {
        setCon(c);
        // pre-fill the editor: current assignment if any, else the AI suggestion
        const hasAssigned = Object.keys(c.assigned || {}).length > 0;
        const base = hasAssigned ? c.assigned : c.suggested;
        setDraft(Object.fromEntries(Object.keys(c.required).map((k) => [k, base[k] ?? 0])));
      })
      .catch((e) => setErr(e.message));
  }, [id, method]);

  useEffect(() => {
    load();
  }, [load]);

  async function commit(assigned) {
    setBusy(true);
    setErr("");
    try {
      await api.put(`/incidents/${id}/assignment`, { assigned });
      onChange();
      load();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function setStatus(status) {
    setBusy(true);
    setErr("");
    try {
      await api.post(`/incidents/${id}/status`, { status });
      onChange();
      load();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (!con) return <div className="card muted">loading allocation…</div>;

  const reqTypes = Object.keys(con.required);
  const resolved = incident.status !== "active";
  const cap = (t) =>
    (con.availability[t]?.assigned_to_this_incident ?? 0) +
    (con.availability[t]?.available_now ?? 0);

  return (
    <div className="card">
      <div className="sim-head">
        <h3>Allocation &amp; assignment</h3>
        <div className="controls">
          <label className="inline">
            Method
            <select value={method} onChange={(e) => setMethod(e.target.value)}>
              <option value="optimal">optimal (ILP)</option>
              <option value="greedy">greedy</option>
            </select>
          </label>
          {isAuthenticated && !resolved && (
            <button className="btn ghost" onClick={() => setStatus("resolved")} disabled={busy}>
              Resolve (release)
            </button>
          )}
          {isAuthenticated && resolved && (
            <button className="btn ghost" onClick={() => setStatus("active")} disabled={busy}>
              Reopen
            </button>
          )}
        </div>
      </div>

      {err && <div className="alert error">{err}</div>}

      {reqTypes.length === 0 ? (
        <p className="muted">This incident type needs no resources.</p>
      ) : resolved ? (
        <p className="muted">
          Incident is {incident.status} — resources released. Reopen to assign again.
        </p>
      ) : (
        <>
          <p className="muted small">
            AI suggestion ({method}):{" "}
            {Object.entries(con.suggested).length
              ? Object.entries(con.suggested)
                  .map(([k, v]) => `${v}× ${k.replace(/_/g, " ")}`)
                  .join(", ")
              : "nothing available for it"}
            {" · "}
            plan: {con.plan_summary.fully_resourced} fully / {con.plan_summary.response_gaps} gaps ·
            this incident would be{" "}
            <span className={`chip alloc-chip ${con.sim_status}`}>
              {(con.sim_status || "").replace(/_/g, " ").toLowerCase()}
            </span>
          </p>

          <table className="data-table assign-table">
            <thead>
              <tr>
                <th>Resource</th>
                <th>Needs</th>
                <th>Suggested</th>
                <th>Assign</th>
                <th>Available</th>
                <th>Also needed by</th>
              </tr>
            </thead>
            <tbody>
              {reqTypes.map((t) => {
                const rivals = con.competitors[t] || [];
                return (
                  <tr key={t}>
                    <td>{t.replace(/_/g, " ")}</td>
                    <td>{con.required[t]}</td>
                    <td className="muted">{con.suggested[t] ?? 0}</td>
                    <td>
                      <input
                        type="number"
                        min="0"
                        max={cap(t)}
                        className="qty"
                        value={draft[t] ?? 0}
                        disabled={!isAuthenticated}
                        onChange={(e) =>
                          setDraft({ ...draft, [t]: Math.max(0, Number(e.target.value)) })
                        }
                      />
                    </td>
                    <td className="muted">
                      {con.availability[t]?.available_now} of {con.availability[t]?.total}
                    </td>
                    <td>
                      <button
                        className="btn ghost xs"
                        onClick={() => setOpenType(openType === t ? null : t)}
                      >
                        {rivals.length} incident{rivals.length === 1 ? "" : "s"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {openType && (
            <div className="competitors">
              <strong>Also need {openType.replace(/_/g, " ")}:</strong>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Incident</th>
                    <th>Priority</th>
                    <th>Needs</th>
                    <th>Assigned</th>
                    <th>Sim status</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {(con.competitors[openType] || []).map((c) => (
                    <tr key={c.id}>
                      <td>{c.incident_type.replace(/_/g, " ")}</td>
                      <td>{c.priority_score}</td>
                      <td>{c.requires}</td>
                      <td>{c.assigned || "—"}</td>
                      <td>
                        <span className={`chip alloc-chip ${c.sim_status}`}>
                          {(c.sim_status || "").replace(/_/g, " ").toLowerCase()}
                        </span>
                      </td>
                      <td>
                        <Link to={`/incident/${c.id}`}>open</Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {isAuthenticated ? (
            <div className="assign-actions">
              <button
                className="btn ghost"
                onClick={() =>
                  setDraft(
                    Object.fromEntries(reqTypes.map((t) => [t, con.suggested[t] ?? 0]))
                  )
                }
              >
                Use suggestion
              </button>
              <button className="btn primary" onClick={() => commit(draft)} disabled={busy}>
                {busy ? "Saving…" : "Commit assignment"}
              </button>
              <button className="btn ghost" onClick={() => commit({})} disabled={busy}>
                Clear
              </button>
              {Object.keys(con.assigned).length > 0 && (
                <span className="muted small">
                  committed:{" "}
                  {Object.entries(con.assigned)
                    .map(([k, v]) => `${v}× ${k.replace(/_/g, " ")}`)
                    .join(", ")}
                </span>
              )}
            </div>
          ) : (
            <p className="muted small">Sign in to assign resources.</p>
          )}
        </>
      )}
    </div>
  );
}

function Field({ label, value }) {
  return (
    <div className="field">
      <div className="field-label muted">{label}</div>
      <div className="field-value">{value}</div>
    </div>
  );
}

function fmt(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}
