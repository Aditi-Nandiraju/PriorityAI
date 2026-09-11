// Pure-logic test for the demo-mode simulator - no React, no real timers.
import assert from "node:assert/strict";
import {
  applyRelease,
  isReadyToResolve,
  markResolved,
  pickReleaseCandidate,
  randomDelay,
  releaseSummary,
} from "../src/hooks/useDemoMode.js";

let failures = 0;
function check(name, fn) {
  try {
    fn();
    console.log(`  ok   ${name}`);
  } catch (e) {
    failures++;
    console.log(`  FAIL ${name}: ${e.message}`);
  }
}

// Only "a" and "d" are eligible: active AND fully resourced (nothing
// outstanding). "e" is the key case - partially assigned is NOT eligible,
// because that incident still has unmet needs in reality.
const incidents = [
  {
    id: "a",
    status: "active",
    incident_type: "fire",
    location: "Main St",
    assignment_status: "FULLY_ASSIGNED",
    assigned: { fire_engine: 1, rescue_team: 1 },
  },
  {
    id: "b",
    status: "active",
    incident_type: "flood",
    location: "5th Ave",
    assignment_status: "UNASSIGNED",
    assigned: {},
  },
  {
    id: "c",
    status: "resolved",
    incident_type: "chemical_leak",
    assignment_status: "FULLY_ASSIGNED", // fully assigned but NOT active -> ineligible
    assigned: { hazmat_team: 1 },
  },
  {
    id: "d",
    status: "active",
    incident_type: "medical_emergency",
    assignment_status: "FULLY_ASSIGNED",
    assigned: { ambulance: 2, medical_team: 1 },
  },
  {
    id: "e",
    status: "active",
    incident_type: "building_collapse",
    assignment_status: "PARTIALLY_ASSIGNED", // needs 2 rescue_team, only has 1
    assigned: { rescue_team: 1 },
  },
];

console.log("isReadyToResolve:");
check("true only for active + FULLY_ASSIGNED + something actually assigned", () => {
  assert.equal(isReadyToResolve(incidents[0]), true); // a
  assert.equal(isReadyToResolve(incidents[1]), false); // b: unassigned
  assert.equal(isReadyToResolve(incidents[2]), false); // c: resolved
  assert.equal(isReadyToResolve(incidents[3]), true); // d
  assert.equal(isReadyToResolve(incidents[4]), false); // e: only partially assigned
});

console.log("\npickReleaseCandidate:");
check("only ever picks fully-resourced active incidents, never a partial one", () => {
  for (let i = 0; i < 200; i++) {
    const picked = pickReleaseCandidate(incidents);
    assert.ok(picked, "should find a candidate");
    assert.ok(["a", "d"].includes(picked.target.id), `picked ${picked.target.id}`);
    assert.notEqual(picked.target.id, "e", "must never pick a partially-assigned incident");
  }
});
check("null when nothing is fully resourced", () => {
  assert.equal(pickReleaseCandidate([incidents[1], incidents[2], incidents[4]]), null);
  assert.equal(pickReleaseCandidate([]), null);
  assert.equal(pickReleaseCandidate(undefined), null);
});
check("released is a snapshot, not a live reference to inc.assigned", () => {
  const inc = {
    id: "x",
    status: "active",
    assignment_status: "FULLY_ASSIGNED",
    assigned: { rescue_team: 1 },
  };
  const picked = pickReleaseCandidate([inc]);
  picked.released.rescue_team = 999;
  assert.equal(inc.assigned.rescue_team, 1, "mutating the returned copy must not touch the incident");
});

console.log("\napplyRelease:");
check("moves qty from committed to available, leaves other types alone", () => {
  const resources = {
    inventory: { rescue_team: 10, ambulance: 5 },
    committed: { rescue_team: 6, ambulance: 3 },
    available: { rescue_team: 4, ambulance: 2 },
  };
  const next = applyRelease(resources, { rescue_team: 2 });
  assert.equal(next.available.rescue_team, 6);
  assert.equal(next.committed.rescue_team, 4);
  assert.equal(next.available.ambulance, 2, "untouched type must be unchanged");
  assert.equal(next.committed.ambulance, 3, "untouched type must be unchanged");
  assert.deepEqual(resources.available, { rescue_team: 4, ambulance: 2 }, "input must not be mutated");
});
check("never drives committed negative", () => {
  const resources = { committed: { rescue_team: 1 }, available: { rescue_team: 0 } };
  const next = applyRelease(resources, { rescue_team: 5 });
  assert.equal(next.committed.rescue_team, 0);
  assert.equal(next.available.rescue_team, 5);
});
check("null resources passes through unchanged", () => {
  assert.equal(applyRelease(null, { rescue_team: 1 }), null);
});

console.log("\nmarkResolved:");
check("resolves exactly the target incident, clears its assignment", () => {
  const next = markResolved(incidents, "a");
  const a = next.find((i) => i.id === "a");
  assert.equal(a.status, "resolved");
  assert.deepEqual(a.assigned, {});
  assert.equal(a.assignment_status, "UNASSIGNED");
});
check("every other incident is untouched (same object identity)", () => {
  const next = markResolved(incidents, "a");
  for (const id of ["b", "c", "d", "e"]) {
    const before = incidents.find((i) => i.id === id);
    const after = next.find((i) => i.id === id);
    assert.strictEqual(before, after, `incident ${id} must be the same object reference`);
  }
});
check("original array is not mutated", () => {
  markResolved(incidents, "a");
  assert.equal(incidents.find((i) => i.id === "a").status, "active");
});

console.log("\nreleaseSummary:");
check("formats human-readable, order preserved", () => {
  assert.equal(releaseSummary({ rescue_team: 2, ambulance: 1 }), "2× rescue team, 1× ambulance");
});

console.log("\nrandomDelay:");
check("stays within [20s, 90s] by default, and within a custom range", () => {
  for (let i = 0; i < 500; i++) {
    const d = randomDelay();
    assert.ok(d >= 20_000 && d < 90_000, `default delay out of range: ${d}`);
  }
  for (let i = 0; i < 500; i++) {
    const d = randomDelay(1000, 2000);
    assert.ok(d >= 1000 && d < 2000, `custom delay out of range: ${d}`);
  }
});

console.log(`\n${failures === 0 ? "ALL PASS" : failures + " FAILURE(S)"}`);
process.exit(failures === 0 ? 0 : 1);
