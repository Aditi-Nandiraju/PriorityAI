"""
allocation.py
-------------
Priority scoring + two resource-allocation strategies for POST /simulate.

    greedy   - walk incidents high-priority-first, take what's available.
               Fast, transparent, but a cluster of mid-priority incidents can
               starve a single higher-priority one that needs a scarce type.

    optimal  - integer program (PuLP/CBC): choose the subset of incidents to
               FULLY resource that maximises total priority, subject to the
               inventory. Leftover units are then greedily spread over the
               remaining incidents so the plan still shows partial coverage.

Both are deterministic and produce a *recommended* plan only -- nothing is
dispatched automatically.

Priority ties: resolve_priority_ties() pre-orders incidents so that, among
incidents sharing the exact same priority_score, the one closer (by hand-
authored zone distance - see resource_rules.py) to a pool it needs comes
first. The caller (app/main.py) applies this BEFORE calling allocate(), and
because Python's sort is stable, that order survives allocate_greedy()'s own
priority sort untouched -- greedy therefore honours the distance tiebreak
exactly. allocate_optimal()'s ILP subset *selection* is the one place this
isn't guaranteed: CBC resolves an exact objective tie by its own internal
search, not by input list order. The tiebreak still governs which of the
tied incidents gets the *leftovers* in optimal mode (the greedy top-up phase
reuses the same order), just not the solver's core subset choice.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

import pulp

from resource_rules import RESOURCE_REQUIREMENTS, get_zone_distance

# priority = 0.7 * severity + 0.3 * confidence   (report volume excluded)
SEVERITY_WEIGHT = {"LOW": 15, "MEDIUM": 45, "HIGH": 75, "CRITICAL": 100}


def default_confidence(inputs: dict[str, Any] | None) -> float:
    """
    Plain evidence-confidence score (0-100) from optional field inputs. Mirrors
    the weighted formula in generate_data.py. A dedicated confidence_rules.py is
    a planned separate module; until then this keeps priority well-defined.
    """
    if not inputs:
        return 50.0
    num_sources = min(int(inputs.get("num_sources") or 1), 3)
    ground = 1 if inputs.get("ground_confirmed") else 0
    agreement = inputs.get("agreement_ratio")
    agreement = 0.7 if agreement is None else float(agreement)
    recency = inputs.get("recency_minutes")
    recency = 60.0 if recency is None else float(recency)
    score = 20 * num_sources + 25 * ground + 30 * agreement + 15 * (1 - min(recency / 180, 1))
    return round(min(max(score, 0.0), 100.0), 1)


def compute_priority(severity_class: str, confidence_score: float) -> float:
    return round(0.7 * SEVERITY_WEIGHT[severity_class] + 0.3 * float(confidence_score), 1)


def _incident_zone_distance(inc: dict, pools_by_type: dict[str, list[str]]) -> int | None:
    """Closest zone-distance from this incident's location to ANY pool of a
    resource type it still needs, or None if that can't be determined - either
    the incident's location isn't a recognised zone (e.g. "Unknown", free text
    from a report with no clean location), or none of the relevant pools have
    a home_zone set."""
    best = None
    for rtype in _req(inc):
        for pool_zone in pools_by_type.get(rtype, []):
            d = get_zone_distance(inc.get("location"), pool_zone)
            if d is not None and (best is None or d < best):
                best = d
    return best


def resolve_priority_ties(
    incidents: list[dict], pools_by_type: dict[str, list[str]]
) -> tuple[list[dict], dict[str, str]]:
    """
    Stable-sorts by priority_score descending (the allocator's existing,
    unchanged primary order), then - ONLY within a run of incidents sharing
    the EXACT same priority_score - reorders that run: the incidents in it
    with a computable zone distance come first (closest first), followed by
    the incidents in it with no computable distance, in their original
    (stable) order. A distance-based reorder can never move an incident
    across a priority boundary; it only decides order among incidents already
    tied on priority.

    Per-incident, not all-or-nothing: a single incident in a tied run with an
    unresolvable location (e.g. "Unknown") does NOT disable the tiebreak for
    the rest of that run - each incident is tagged with the method that
    actually applied to IT, so it's never silently blended together.

    Returns (ordered_incidents, tiebreak_info) where tiebreak_info maps
    incident id -> "distance" | "fallback_no_location_data" for incidents that
    were actually part of a tie; incidents with a unique priority_score are
    left out of the map entirely (there was nothing to break).
    """
    ordered = sorted(incidents, key=lambda i: i["priority_score"], reverse=True)
    tiebreak_info: dict[str, str] = {}

    i, n = 0, len(ordered)
    while i < n:
        j = i
        while j + 1 < n and ordered[j + 1]["priority_score"] == ordered[i]["priority_score"]:
            j += 1
        if j > i:  # a genuine tie: 2+ incidents at this exact priority_score
            run = ordered[i : j + 1]
            with_distance = [(inc, _incident_zone_distance(inc, pools_by_type)) for inc in run]
            resolvable = sorted((p for p in with_distance if p[1] is not None), key=lambda p: p[1])
            unresolvable = [inc for inc, d in with_distance if d is None]  # keeps original relative order

            ordered[i : j + 1] = [inc for inc, _ in resolvable] + unresolvable
            for inc, _ in resolvable:
                tiebreak_info[inc["id"]] = "distance"
            for inc in unresolvable:
                tiebreak_info[inc["id"]] = "fallback_no_location_data"
        i = j + 1

    return ordered, tiebreak_info


def _req(inc: dict) -> dict[str, int]:
    """
    What this incident still needs from the allocator. When the caller has
    already committed some resources to it (operator assignment), it passes
    `required_remaining` = requirement minus what's assigned; otherwise fall
    back to the full type requirement.
    """
    if "required_remaining" in inc:
        return {k: v for k, v in inc["required_remaining"].items() if v > 0}
    return RESOURCE_REQUIREMENTS.get(inc["incident_type"], {})


# --------------------------------------------------------------------------- #
def _entry(inc: dict, req: dict, allocated: dict, shortages: dict) -> dict:
    if not shortages:
        status = "FULLY_RESOURCED"
    elif any(v > 0 for v in allocated.values()):
        status = "PARTIALLY_RESOURCED"
    else:
        status = "UNRESOURCED"
    entry = {
        "incident_id": inc["id"],
        "incident_type": inc["incident_type"],
        "severity_class": inc.get("severity_class"),
        "priority_score": inc["priority_score"],
        "required": dict(req),
        "allocated": {k: v for k, v in allocated.items() if v},
        "shortages": shortages,
        "status": status,
    }
    if inc.get("assigned"):
        entry["assigned"] = dict(inc["assigned"])
    return entry


def _plan(method, allocations, starting_inv, remaining_inv, solver=None) -> dict:
    counts = Counter(a["status"] for a in allocations)
    plan = {
        "method": method,
        "summary": {
            "incidents": len(allocations),
            "fully_resourced": counts.get("FULLY_RESOURCED", 0),
            "partially_resourced": counts.get("PARTIALLY_RESOURCED", 0),
            "unresourced": counts.get("UNRESOURCED", 0),
            "response_gaps": sum(1 for a in allocations if a["shortages"]),
        },
        "starting_inventory": dict(starting_inv),
        "remaining_inventory": {k: v for k, v in remaining_inv.items()},
        "allocations": allocations,
    }
    if solver is not None:
        plan["solver"] = solver
    return plan


def _greedy_fill(incidents, inv, allocations, skip_ids=frozenset()):
    for inc in sorted(incidents, key=lambda i: i["priority_score"], reverse=True):
        if inc["id"] in skip_ids:
            continue
        req = _req(inc)
        allocated, shortages = {}, {}
        for rtype, need in req.items():
            got = min(inv.get(rtype, 0), need)
            allocated[rtype] = got
            inv[rtype] = inv.get(rtype, 0) - got
            if got < need:
                shortages[rtype] = need - got
        allocations.append(_entry(inc, req, allocated, shortages))


def allocate_greedy(incidents: list[dict], inventory: dict[str, int]) -> dict:
    inv = dict(inventory)
    allocations: list[dict] = []
    _greedy_fill(incidents, inv, allocations)
    return _plan("greedy", allocations, inventory, inv)


def allocate_optimal(incidents: list[dict], inventory: dict[str, int]) -> dict:
    if not incidents:
        return _plan("optimal", [], inventory, dict(inventory),
                     solver={"status": "trivial", "objective": 0.0})

    prob = pulp.LpProblem("priorityai_allocation", pulp.LpMaximize)
    x = {inc["id"]: pulp.LpVariable(f"x_{k}", cat="Binary") for k, inc in enumerate(incidents)}
    prob += pulp.lpSum(inc["priority_score"] * x[inc["id"]] for inc in incidents)

    req_types = {r for inc in incidents for r in _req(inc)}
    for rtype in req_types:
        cap = inventory.get(rtype, 0)
        prob += (
            pulp.lpSum(
                _req(inc).get(rtype, 0) * x[inc["id"]]
                for inc in incidents
            )
            <= cap
        )

    prob.solve(pulp.PULP_CBC_CMD(msg=False))
    chosen = {i for i, var in x.items() if (var.value() or 0) > 0.5}

    inv = dict(inventory)
    allocations: list[dict] = []
    # fully resource the chosen set (feasible by construction), in priority order
    for inc in sorted(incidents, key=lambda i: i["priority_score"], reverse=True):
        if inc["id"] not in chosen:
            continue
        req = _req(inc)
        allocated = {}
        for rtype, need in req.items():
            allocated[rtype] = need
            inv[rtype] = inv.get(rtype, 0) - need
        allocations.append(_entry(inc, req, allocated, {}))

    # spread whatever's left over the rest
    _greedy_fill(incidents, inv, allocations, skip_ids=chosen)

    # keep allocations sorted by priority for a stable, readable plan
    allocations.sort(key=lambda a: a["priority_score"], reverse=True)
    return _plan(
        "optimal", allocations, inventory, inv,
        solver={"status": pulp.LpStatus[prob.status], "objective": pulp.value(prob.objective)},
    )


def allocate(method: str, incidents: list[dict], inventory: dict[str, int]) -> dict:
    if method == "optimal":
        return allocate_optimal(incidents, inventory)
    if method == "greedy":
        return allocate_greedy(incidents, inventory)
    raise ValueError(f"unknown method {method!r}; use 'optimal' or 'greedy'")
