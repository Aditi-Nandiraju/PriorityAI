// Compact inventory readout. Reads `resources` (the GET /resources payload:
// {pools, inventory, committed, available}) from the caller's state rather
// than fetching its own copy, so it's always showing the exact same numbers
// demo mode / assignments mutate elsewhere on the page - never a second,
// possibly-stale source of truth.
export default function ResourceStrip({ resources }) {
  if (!resources) return <div className="resource-strip muted">loading inventory…</div>;

  const total = resources.inventory || {};
  const available = resources.available || total;

  return (
    <div className="resource-strip">
      {Object.entries(total).map(([type, qty]) => (
        <span key={type} className="res-chip">
          <span className="res-name">{type.replace(/_/g, " ")}</span>
          <span className="res-qty">
            {available[type] ?? qty}/{qty}
          </span>
        </span>
      ))}
    </div>
  );
}
