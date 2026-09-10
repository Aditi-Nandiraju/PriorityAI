import { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";

export default function ActivityLog() {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      setRows(await api.get("/audit?limit=500"));
    } catch (err) {
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (error) return <div className="alert error">{error}</div>;
  if (!rows) return <p className="muted">loading…</p>;

  const shown = filter
    ? rows.filter(
        (r) =>
          r.action?.includes(filter) ||
          r.username?.includes(filter) ||
          JSON.stringify(r.details).includes(filter)
      )
    : rows;

  return (
    <div>
      <div className="page-head">
        <h2>Activity Log</h2>
        <div className="controls">
          <input
            placeholder="filter…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          <button className="btn ghost" onClick={load}>
            Refresh
          </button>
        </div>
      </div>
      <p className="muted small">
        Append-only audit trail — one row per mutating action, attributed to the operator.
        {shown.length !== rows.length && ` Showing ${shown.length} of ${rows.length}.`}
      </p>

      <table className="data-table audit">
        <thead>
          <tr>
            <th>When</th>
            <th>User</th>
            <th>Action</th>
            <th>Details</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((r) => (
            <tr key={r.id}>
              <td className="nowrap">{fmt(r.timestamp)}</td>
              <td>
                <span className="chip">{r.username}</span>
              </td>
              <td>
                <code>{r.action}</code>
              </td>
              <td>
                <pre className="detail-cell">{JSON.stringify(r.details)}</pre>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
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
