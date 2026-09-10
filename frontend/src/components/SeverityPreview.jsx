import { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";

// Live flag -> severity score/class preview (CMS_SPEC.md).
// Mirrors severity_rules.compute_severity: weighted sum of active structural
// flags, clamped to `max`, then binned. Config is fetched from
// GET /severity/config so the widget never drifts from the backend.
export default function SeverityPreview({ flags }) {
  const [cfg, setCfg] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api
      .get("/severity/config", { auth: false })
      .then(setCfg)
      .catch((e) => setErr(e.message));
  }, []);

  const result = useMemo(() => {
    if (!cfg) return null;
    const active = Object.entries(cfg.weights).filter(([k]) => flags[k]);
    const raw = active.reduce((s, [, w]) => s + w, 0);
    const score = Math.min(raw, cfg.max);
    const { medium_at, high_at, critical_at } = cfg.bins;
    let klass = "LOW";
    if (score >= critical_at) klass = "CRITICAL";
    else if (score >= high_at) klass = "HIGH";
    else if (score >= medium_at) klass = "MEDIUM";
    return { active, raw, score, klass, clamped: raw > cfg.max };
  }, [cfg, flags]);

  if (err) return <div className="alert error">severity preview unavailable: {err}</div>;
  if (!result) return <div className="sev-preview muted">loading severity model…</div>;

  const pct = (result.score / cfg.max) * 100;

  return (
    <div className="sev-preview">
      <div className="sev-head">
        <span className={`sev-badge sev-${result.klass}`}>{result.klass}</span>
        <span className="sev-score">
          {result.score}
          <span className="muted">/{cfg.max}</span>
          {result.clamped && <span className="muted small"> (clamped from {result.raw})</span>}
        </span>
      </div>
      <div className="sev-bar">
        <div className={`sev-fill sev-${result.klass}`} style={{ width: `${pct}%` }} />
      </div>
      {result.active.length > 0 ? (
        <ul className="sev-contrib">
          {result.active
            .sort((a, b) => b[1] - a[1])
            .map(([k, w]) => (
              <li key={k}>
                <span>{k.replace(/_/g, " ")}</span>
                <span className="muted">+{w}</span>
              </li>
            ))}
        </ul>
      ) : (
        <p className="muted small">No flags set — severity is LOW.</p>
      )}
    </div>
  );
}
