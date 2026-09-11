// Minimal toast stack. `kind: "demo"` renders with a distinct color + a
// SIMULATED badge so a demo-mode event can never be mistaken for a real
// backend-driven update.
export default function Toaster({ toasts, onDismiss }) {
  if (!toasts.length) return null;
  return (
    <div className="toaster">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast-${t.kind || "info"}`}>
          {t.kind === "demo" && <span className="toast-badge">SIMULATED</span>}
          <span className="toast-text">{t.text}</span>
          <button className="toast-close" onClick={() => onDismiss(t.id)} aria-label="dismiss">
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
