import { Link } from "react-router-dom";

// `allocation` (optional) is this incident's row from the latest allocation plan.
// When it's PARTIALLY_RESOURCED / UNRESOURCED the card is flagged, and (if the
// viewer is signed in) it gets inline "assign suggested" / "clear" controls so
// the operator doesn't have to open every incident. Resolving is NOT a manual
// board action - see hooks/useDemoMode.js: an incident resolves once it's
// fully resourced and nothing more is outstanding, same as it would in reality.
// Once resolved, the board greys the card out and sorts it to the end (see
// Board.jsx) - but reopening it here IS a manual, one-click action, since
// that's just undoing a mistake, not faking a resolution.
export default function IncidentCard({ incident, allocation, canAssign, busy, onQuickAssign, onReopen }) {
  const sev = incident.severity_class || "LOW";
  const status = allocation?.status;
  const resolved = incident.status === "resolved";
  // guard on incident.status too: once an incident is resolved (including by
  // demo mode) its old allocation row can be stale - never highlight it as
  // under-resourced or offer assign actions once it's no longer active.
  const under = incident.status === "active" && (status === "PARTIALLY_RESOURCED" || status === "UNRESOURCED");

  const assigned = allocation?.assigned || incident.assigned || {};
  const suggested = allocation?.allocated || {}; // solver's extra units for this incident
  const hasSuggestion = Object.values(suggested).some((v) => v > 0);
  const hasAssigned = Object.values(assigned).some((v) => v > 0);

  const shortages = Object.entries(allocation?.shortages || {})
    .map(([k, v]) => `${k.replace(/_/g, " ")} ×${v}`)
    .join(", ");

  function applySuggested(e) {
    e.preventDefault();
    e.stopPropagation();
    // replace-semantics PUT: existing assignment + the solver's suggestion
    const merged = { ...assigned };
    for (const [k, v] of Object.entries(suggested)) merged[k] = (merged[k] || 0) + v;
    onQuickAssign(incident.id, merged);
  }

  function clearAssigned(e) {
    e.preventDefault();
    e.stopPropagation();
    onQuickAssign(incident.id, {});
  }

  function reopen(e) {
    e.preventDefault();
    e.stopPropagation();
    onReopen(incident.id);
  }

  return (
    <Link
      to={`/incident/${incident.id}`}
      className={`incident-card${under ? ` under under-${status}` : ""}${resolved ? " resolved" : ""}`}
    >
      <div className="ic-top">
        <span className={`sev-badge sev-${sev}`}>{sev}</span>
        <span className="ic-type">{(incident.incident_type || "").replace(/_/g, " ")}</span>
        <span className="ic-priority" title="priority score">
          P {incident.priority_score ?? "—"}
        </span>
      </div>
      <div className="ic-meta muted">
        <span>{incident.location || "location unknown"}</span>
        <span>·</span>
        <span>severity {incident.severity_score ?? "—"}</span>
        <span>·</span>
        <span>confidence {incident.confidence_score ?? "—"}</span>
      </div>

      {under && (
        <div className={`ic-alloc ic-alloc-${status}`}>
          {status === "UNRESOURCED" ? "⚠ unresourced" : "⚠ under-resourced"}
          {shortages && <span className="muted"> — short {shortages}</span>}
        </div>
      )}

      {hasAssigned && (
        <div className="ic-assigned">
          assigned:{" "}
          {Object.entries(assigned)
            .map(([k, v]) => `${v}× ${k.replace(/_/g, " ")}`)
            .join(", ")}
        </div>
      )}

      {canAssign && incident.status === "active" && (hasSuggestion || hasAssigned) && (
        <div className="ic-actions">
          {hasSuggestion && (
            <button className="btn primary xs" onClick={applySuggested} disabled={busy}>
              Assign suggested
              {" ("}
              {Object.entries(suggested)
                .map(([k, v]) => `${v} ${k.replace(/_/g, " ")}`)
                .join(", ")}
              {")"}
            </button>
          )}
          {hasAssigned && (
            <button className="btn ghost xs" onClick={clearAssigned} disabled={busy}>
              Clear
            </button>
          )}
        </div>
      )}

      {canAssign && resolved && (
        <div className="ic-actions">
          <button className="btn ghost xs" onClick={reopen} disabled={busy}>
            ↺ Reopen
          </button>
        </div>
      )}

      <div className="ic-foot muted small">
        <span className={`chip status-${incident.status}`}>{incident.status}</span>
        {incident.assignment_status === "FULLY_ASSIGNED" && (
          <span className="chip assigned-chip">resources assigned</span>
        )}
        {incident.assignment_status === "PARTIALLY_ASSIGNED" && (
          <span className="chip part-assigned-chip">part-assigned</span>
        )}
        <span>{incident.created_by ? `by ${incident.created_by}` : ""}</span>
      </div>
    </Link>
  );
}
