// Minimal toast stack.
//   kind: "demo" - distinct color + a SIMULATED badge, so a demo-mode event
//         can never be mistaken for a real backend-driven update.
//   kind: "peer" - distinct color + a TEAM badge, for a change a teammate
//         made from their own localhost (shared Atlas DB) - see
//         BoardDataContext.jsx / GET /notifications.
const BADGES = { demo: "SIMULATED", peer: "TEAM" };

export default function Toaster({ toasts, onDismiss }) {
  if (!toasts.length) return null;
  return (
    <div className="toaster">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast-${t.kind || "info"}`}>
          {BADGES[t.kind] && <span className={`toast-badge toast-badge-${t.kind}`}>{BADGES[t.kind]}</span>}
          <span className="toast-text">{t.text}</span>
          <button className="toast-close" onClick={() => onDismiss(t.id)} aria-label="dismiss">
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
