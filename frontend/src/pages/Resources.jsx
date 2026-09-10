import { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import { useAuth } from "../context/AuthContext.jsx";

const RESOURCE_TYPES = [
  "ambulance",
  "fire_engine",
  "rescue_boat",
  "rescue_team",
  "ground_team",
  "medical_team",
  "hazmat_team",
];

export default function Resources() {
  const { isAdmin } = useAuth();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [edits, setEdits] = useState({});
  const [savingId, setSavingId] = useState(null);

  const load = useCallback(async () => {
    setError("");
    try {
      setData(await api.get("/resources", { auth: false }));
      setEdits({});
    } catch (err) {
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function saveRow(pool) {
    const next = edits[pool.id];
    if (!next) return;
    setSavingId(pool.id);
    setError("");
    try {
      const body = {};
      if (next.label !== undefined && next.label !== pool.label) body.label = next.label;
      if (next.quantity !== undefined && Number(next.quantity) !== pool.quantity)
        body.quantity = Number(next.quantity);
      if (Object.keys(body).length) await api.put(`/resources/${pool.id}`, body);
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setSavingId(null);
    }
  }

  if (error && !data) return <div className="alert error">{error}</div>;
  if (!data) return <p className="muted">loading…</p>;

  return (
    <div>
      <div className="page-head">
        <h2>Resource Inventory</h2>
        {!isAdmin && <span className="muted small">view only — admin role required to edit</span>}
      </div>

      {error && <div className="alert error">{error}</div>}

      <table className="data-table">
        <thead>
          <tr>
            <th>Type</th>
            <th>Label</th>
            <th>Quantity</th>
            {isAdmin && <th />}
          </tr>
        </thead>
        <tbody>
          {data.pools.map((pool) => {
            const e = edits[pool.id] || {};
            return (
              <tr key={pool.id}>
                <td>{pool.resource_type.replace(/_/g, " ")}</td>
                <td>
                  {isAdmin ? (
                    <input
                      value={e.label ?? pool.label ?? ""}
                      onChange={(ev) =>
                        setEdits((m) => ({ ...m, [pool.id]: { ...e, label: ev.target.value } }))
                      }
                    />
                  ) : (
                    pool.label
                  )}
                </td>
                <td>
                  {isAdmin ? (
                    <input
                      type="number"
                      min="0"
                      className="qty"
                      value={e.quantity ?? pool.quantity}
                      onChange={(ev) =>
                        setEdits((m) => ({ ...m, [pool.id]: { ...e, quantity: ev.target.value } }))
                      }
                    />
                  ) : (
                    pool.quantity
                  )}
                </td>
                {isAdmin && (
                  <td>
                    <button
                      className="btn ghost"
                      disabled={!edits[pool.id] || savingId === pool.id}
                      onClick={() => saveRow(pool)}
                    >
                      {savingId === pool.id ? "…" : "Save"}
                    </button>
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
        <tfoot>
          <tr>
            <td className="muted">total by type</td>
            <td />
            <td className="muted">
              {Object.values(data.inventory).reduce((a, b) => a + b, 0)}
            </td>
            {isAdmin && <td />}
          </tr>
        </tfoot>
      </table>

      {isAdmin && <AddPool onDone={load} setError={setError} existing={data.pools} />}
    </div>
  );
}

function AddPool({ onDone, setError }) {
  const [resourceType, setResourceType] = useState(RESOURCE_TYPES[0]);
  const [label, setLabel] = useState("");
  const [quantity, setQuantity] = useState(1);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const body = { resource_type: resourceType, quantity: Number(quantity) };
      if (label.trim()) body.label = label.trim();
      await api.post("/resources", body);
      setLabel("");
      setQuantity(1);
      await onDone();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card add-pool" onSubmit={submit}>
      <strong>Add resource pool</strong>
      <div className="row wrap">
        <label>
          Type
          <select value={resourceType} onChange={(e) => setResourceType(e.target.value)}>
            {RESOURCE_TYPES.map((t) => (
              <option key={t} value={t}>
                {t.replace(/_/g, " ")}
              </option>
            ))}
          </select>
        </label>
        <label>
          Label (optional)
          <input value={label} onChange={(e) => setLabel(e.target.value)} />
        </label>
        <label>
          Quantity
          <input
            type="number"
            min="0"
            className="qty"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
          />
        </label>
        <button className="btn primary" disabled={busy}>
          {busy ? "Adding…" : "Add"}
        </button>
      </div>
    </form>
  );
}
