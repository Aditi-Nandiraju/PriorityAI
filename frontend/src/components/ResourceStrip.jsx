import { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";

// Compact inventory readout. `remaining` (from a simulation plan) is shown
// alongside the total when provided.
export default function ResourceStrip({ remaining }) {
  const [inventory, setInventory] = useState(null);
  const [err, setErr] = useState("");

  const load = useCallback(() => {
    setErr("");
    api
      .get("/resources", { auth: false })
      .then((d) => setInventory(d.inventory))
      .catch((e) => setErr(e.message));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (err) {
    return (
      <div className="alert error">
        resources: {err}{" "}
        <button className="btn ghost" onClick={load}>
          Retry
        </button>
      </div>
    );
  }
  if (!inventory) return <div className="resource-strip muted">loading inventory…</div>;

  return (
    <div className="resource-strip">
      {Object.entries(inventory).map(([type, qty]) => (
        <span key={type} className="res-chip">
          <span className="res-name">{type.replace(/_/g, " ")}</span>
          <span className="res-qty">
            {remaining ? `${remaining[type] ?? 0}/${qty}` : qty}
          </span>
        </span>
      ))}
    </div>
  );
}
