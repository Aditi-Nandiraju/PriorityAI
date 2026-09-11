import { useCallback, useEffect, useRef, useState } from "react";

/**
 * DEMO-MODE RESOURCE-RELEASE SIMULATOR
 * -------------------------------------
 * Entirely client-side. Makes the board look "alive" during a live demo:
 * there is no manual "resolve" button on the board - instead, an incident
 * resolves on its own, the way it realistically would, once it is FULLY
 * resourced (every unit it needs is assigned - nothing outstanding). At that
 * point it's simulated as handled: those units move back to "available" and
 * the incident flips to resolved, all in the SAME React state (`incidents` /
 * `resources`) the rest of the UI reads, so the resource strip and the board
 * never disagree with a demo toast. A partially-resourced incident is never a
 * candidate - it still has unmet needs, so it wouldn't be done in reality.
 *
 * This is a presentation stand-in, not a missing feature: a real resolve
 * action already exists - POST /incidents/{id}/status {status:"resolved"}
 * (see app/main.py: set_incident_status) - which does the same release,
 * backend-driven and written to audit_log. See the TODO below.
 *
 * The pure state-transition functions are exported separately so they can be
 * unit-tested without mounting React or waiting on real timers.
 */

const MIN_DELAY_MS = 20_000;
const MAX_DELAY_MS = 90_000;

export function randomDelay(min = MIN_DELAY_MS, max = MAX_DELAY_MS) {
  return min + Math.random() * (max - min);
}

/** Eligible to auto-resolve: active, has resources assigned, and nothing more
 * is outstanding (assignment_status is set server-side - see app/main.py:
 * _assignment_status - and mirrored here after a simulated release). */
export function isReadyToResolve(inc) {
  return (
    inc.status === "active" &&
    inc.assignment_status === "FULLY_ASSIGNED" &&
    !!inc.assigned &&
    Object.values(inc.assigned).some((q) => q > 0)
  );
}

/** Randomly pick one fully-resourced active incident to "resolve". Null if none qualify. */
export function pickReleaseCandidate(incidents) {
  const candidates = (incidents || []).filter(isReadyToResolve);
  if (candidates.length === 0) return null;
  const target = candidates[Math.floor(Math.random() * candidates.length)];
  return { target, released: { ...target.assigned } };
}

/** Move `released` units from committed back to available. Pure, no mutation. */
export function applyRelease(resources, released) {
  if (!resources) return resources;
  const available = { ...resources.available };
  const committed = { ...resources.committed };
  for (const [rtype, qty] of Object.entries(released)) {
    available[rtype] = (available[rtype] || 0) + qty;
    committed[rtype] = Math.max(0, (committed[rtype] || 0) - qty);
  }
  return { ...resources, available, committed };
}

/** Mark exactly one incident resolved + cleared. Every other incident untouched. */
export function markResolved(incidents, targetId) {
  return (incidents || []).map((inc) =>
    inc.id === targetId
      ? { ...inc, status: "resolved", assigned: {}, assignment_status: "UNASSIGNED" }
      : inc
  );
}

export function releaseSummary(released) {
  return Object.entries(released)
    .map(([rtype, qty]) => `${qty}× ${rtype.replace(/_/g, " ")}`)
    .join(", ");
}

export function useDemoMode({ incidents, setIncidents, resources, setResources, pushToast }) {
  const [demoMode, setDemoMode] = useState(false);

  // Always-current snapshots so the recursive timer never acts on stale
  // closures from whenever it happened to be scheduled.
  const latest = useRef({ incidents, resources });
  useEffect(() => {
    latest.current = { incidents, resources };
  }, [incidents, resources]);

  const enabledRef = useRef(demoMode);
  useEffect(() => {
    enabledRef.current = demoMode;
  }, [demoMode]);

  const timerRef = useRef(null);
  const fireRef = useRef(() => {});

  // Rebind the fire handler every render so it always closes over the
  // latest setIncidents/setResources/pushToast without re-creating the timer.
  useEffect(() => {
    fireRef.current = () => {
      const picked = pickReleaseCandidate(latest.current.incidents);

      if (picked) {
        const { target, released } = picked;

        // --- TODO(demo-mode): this is a CLIENT-SIDE PLACEHOLDER --------------
        // Replace this branch with a real call once demo mode is retired:
        //   await api.post(`/incidents/${target.id}/status`, { status: "resolved" });
        //   await refresh();  // re-pull incidents + /resources from the backend
        // That endpoint already exists (app/main.py: set_incident_status) and
        // has the exact same effect - release assigned resources, mark the
        // incident resolved - except it's backend-driven and audit-logged, per
        // the "every mutating action is attributed to an operator" design
        // decision. Don't let this simulated version quietly become permanent.
        // ----------------------------------------------------------------------
        setResources((prev) => applyRelease(prev, released));
        setIncidents((prev) => markResolved(prev, target.id));

        pushToast({
          kind: "demo",
          text: `${target.incident_type.replace(/_/g, " ")} at ${
            target.location || "an unknown location"
          } resolved — released ${releaseSummary(released)}`,
        });
      }
      // else: nothing is fully resourced right now (only unassigned/partial
      // incidents, or none at all) - nothing realistically "wraps up" yet,
      // skip this tick silently and try again next time.

      if (enabledRef.current) {
        timerRef.current = setTimeout(() => fireRef.current(), randomDelay());
      }
    };
  });

  // Start the chain on toggle-on; always clear the pending timer on
  // toggle-off AND on unmount, so nothing fires against stale/gone state.
  useEffect(() => {
    if (demoMode) {
      timerRef.current = setTimeout(() => fireRef.current(), randomDelay());
    }
    return () => {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    };
  }, [demoMode]);

  return { demoMode, setDemoMode };
}
