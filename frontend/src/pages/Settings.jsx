import { useState } from "react";
import { useBoardData } from "../context/BoardDataContext.jsx";

// Admin-only. Demo-facing controls that don't need to sit next to the
// incident list: toggling them mid-demo doesn't require the fast back-and-
// forth that method/Run & log do (see Board.jsx), so pulling them out here
// keeps the board focused on the actual live-demo flow.
export default function Settings() {
  const { demoMode, setDemoMode, replayStatus, startReplay, stopReplay, busy } = useBoardData();
  const [compression, setCompression] = useState(60);

  return (
    <div className="stack">
      <h2>Settings</h2>
      <p className="muted">Demo-facing controls. Admin-only.</p>

      <div className="card">
        <h3>Demo mode</h3>
        <p className="muted small">
          Client-side only — periodically resolves a fully-resourced incident and releases its
          resources, purely for presentation. Never calls the backend; toasts carry a "SIMULATED"
          badge so they're never mistaken for a real operator action. See the TODO in{" "}
          <code>frontend/src/hooks/useDemoMode.js</code>.
        </p>
        <label className="inline demo-toggle">
          <input type="checkbox" checked={demoMode} onChange={(e) => setDemoMode(e.target.checked)} />
          Demo mode {demoMode ? "on" : "off"}
        </label>
      </div>

      <div className="card">
        <h3>Live feed replay</h3>
        <p className="muted small">
          Drips <code>data/replay/*.csv</code> into Reports — real backend writes, realistically
          paced from each row's timestamp (compressed by the factor below, clamped 0.5–6s per
          gap), looping forever. Cycle 2+ jitters the order slightly so repeats aren't identical.
        </p>

        {replayStatus?.running ? (
          <div className="stack">
            <div className="sim-summary">
              <Stat label="cycle" value={replayStatus.cycle} tone="ok" />
              <Stat
                label="reports this cycle"
                value={`${replayStatus.reports_ingested_this_cycle}/${replayStatus.total_reports_per_cycle}`}
                tone="ok"
              />
              <span className="muted small">compression {replayStatus.compression_factor}×</span>
            </div>
            <button className="btn ghost" onClick={stopReplay} disabled={busy}>
              Stop live feed
            </button>
          </div>
        ) : (
          <div className="row">
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
          </div>
        )}
        {replayStatus?.error && <div className="alert error">replay stopped: {replayStatus.error}</div>}
      </div>
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
