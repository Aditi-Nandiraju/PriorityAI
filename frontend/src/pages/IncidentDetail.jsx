import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api.js";

export default function IncidentDetail() {
  const { id } = useParams();
  const [inc, setInc] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setError("");
    api
      .get(`/incidents/${id}`, { auth: false })
      .then(setInc)
      .catch((e) => setError(e.message));
  }, [id]);

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

      <ResourcesCard incidentId={id} required={inc.required_resources} status={inc.status} />

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

// Shows the incident type's fixed resource requirement, and — via the read-only
// /incidents/{id}/allocation preview — whether the current queue + inventory can
// actually cover it (optimal or greedy). No writes, no audit entry.
function ResourcesCard({ incidentId, required, status }) {
  const [method, setMethod] = useState("optimal");
  const [alloc, setAlloc] = useState(null);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    setErr("");
    api
      .get(`/incidents/${incidentId}/allocation?method=${method}`, { auth: false })
      .then(setAlloc)
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false));
  }, [incidentId, method]);

  useEffect(() => {
    load();
  }, [load]);

  const reqEntries = Object.entries(required || {});
  const row = alloc?.allocation;

  return (
    <div className="card">
      <div className="sim-head">
        <h3>Resources</h3>
        <div className="controls">
          <label className="inline">
            Method
            <select value={method} onChange={(e) => setMethod(e.target.value)}>
              <option value="optimal">optimal (ILP)</option>
              <option value="greedy">greedy</option>
            </select>
          </label>
          <button className="btn ghost" onClick={load} disabled={loading}>
            {loading ? "…" : "Re-check"}
          </button>
        </div>
      </div>

      <p className="muted small">
        Requirement:{" "}
        {reqEntries.length === 0
          ? "none"
          : reqEntries.map(([k, v]) => `${v}× ${k.replace(/_/g, " ")}`).join(", ")}
      </p>

      {err && <div className="alert error">{err}</div>}

      {status !== "active" ? (
        <p className="muted">Incident is {status} — not part of the live simulation.</p>
      ) : !row ? (
        <p className="muted">{loading ? "checking allocation…" : "no allocation result"}</p>
      ) : (
        <>
          <p>
            <span className={`chip alloc-chip ${row.status}`}>
              {row.status.replace(/_/g, " ").toLowerCase()}
            </span>{" "}
            <span className="muted small">
              at priority {row.priority_score} · {method} plan:{" "}
              {alloc.plan_summary.fully_resourced} fully / {alloc.plan_summary.response_gaps} gaps
            </span>
          </p>
          <table className="data-table">
            <thead>
              <tr>
                <th>Resource</th>
                <th>Needed</th>
                <th>Allocated</th>
                <th>Short</th>
              </tr>
            </thead>
            <tbody>
              {reqEntries.map(([k, need]) => (
                <tr key={k}>
                  <td>{k.replace(/_/g, " ")}</td>
                  <td>{need}</td>
                  <td>{row.allocated?.[k] ?? 0}</td>
                  <td className={row.shortages?.[k] ? "short" : "muted"}>
                    {row.shortages?.[k] ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
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
