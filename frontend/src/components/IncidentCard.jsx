import { Link } from "react-router-dom";

// `allocation` (optional) is this incident's row from the latest allocation plan.
// When it's PARTIALLY_RESOURCED / UNRESOURCED the card is flagged.
export default function IncidentCard({ incident, allocation }) {
  const sev = incident.severity_class || "LOW";
  const status = allocation?.status;
  const under = status === "PARTIALLY_RESOURCED" || status === "UNRESOURCED";
  const shortages = Object.entries(allocation?.shortages || {})
    .map(([k, v]) => `${k.replace(/_/g, " ")} ×${v}`)
    .join(", ");

  return (
    <Link
      to={`/incident/${incident.id}`}
      className={`incident-card${under ? ` under under-${status}` : ""}`}
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
      <div className="ic-foot muted small">
        <span className={`chip status-${incident.status}`}>{incident.status}</span>
        <span>{incident.created_by ? `by ${incident.created_by}` : ""}</span>
      </div>
    </Link>
  );
}
