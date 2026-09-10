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
"""
from __future__ import annotations

from collections import Counter
from typing import Any

import pulp

from resource_rules import RESOURCE_REQUIREMENTS

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


# --------------------------------------------------------------------------- #
def _entry(inc: dict, req: dict, allocated: dict, shortages: dict) -> dict:
    if not shortages:
        status = "FULLY_RESOURCED"
    elif any(v > 0 for v in allocated.values()):
        status = "PARTIALLY_RESOURCED"
    else:
        status = "UNRESOURCED"
    return {
        "incident_id": inc["id"],
        "incident_type": inc["incident_type"],
        "severity_class": inc.get("severity_class"),
        "priority_score": inc["priority_score"],
        "required": dict(req),
        "allocated": {k: v for k, v in allocated.items() if v},
        "shortages": shortages,
        "status": status,
    }


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
        req = RESOURCE_REQUIREMENTS.get(inc["incident_type"], {})
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

    req_types = {r for inc in incidents for r in RESOURCE_REQUIREMENTS.get(inc["incident_type"], {})}
    for rtype in req_types:
        cap = inventory.get(rtype, 0)
        prob += (
            pulp.lpSum(
                RESOURCE_REQUIREMENTS.get(inc["incident_type"], {}).get(rtype, 0) * x[inc["id"]]
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
        req = RESOURCE_REQUIREMENTS.get(inc["incident_type"], {})
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
