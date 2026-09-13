"""
resource_rules.py
-----------------
Single source of truth for the deterministic resource layer:

  * RESOURCE_REQUIREMENTS - incident type -> {resource_type: units needed}
  * DEFAULT_INVENTORY     - starting unit counts per resource type
  * INCIDENT_TYPES / RESOURCE_TYPES - derived vocabularies

Imported by generate_data.py (synthetic data), resource_allocator.py (offline
CLI) and app/ (the live API), so the mapping never drifts between them.

Plain lookup tables on purpose: an operator can read and edit them, and every
allocation decision traces back to a line here.
"""
from __future__ import annotations

# rescue_team is a specialised life-safety asset (extrication, swiftwater, USAR);
# low-acuity clearance jobs (road_blockage, power_outage) draw on a lighter
# ground_team instead so they don't compete for the same scarce pool.
RESOURCE_REQUIREMENTS: dict[str, dict[str, int]] = {
    "fire": {"fire_engine": 1, "rescue_team": 1},
    "flood": {"rescue_boat": 1, "rescue_team": 1, "medical_team": 1},
    "building_collapse": {"rescue_team": 2, "ambulance": 1},
    "medical_emergency": {"ambulance": 1, "medical_team": 1},
    "road_blockage": {"ground_team": 1},
    "power_outage": {"ground_team": 1},
    "chemical_leak": {"hazmat_team": 1, "medical_team": 1},
    "industrial_accident": {"hazmat_team": 1, "ambulance": 1, "rescue_team": 1},
}

# Starting inventory for the live API and the CLI demo. Tuned so that a realistic
# active queue leaves a visible-but-not-total response gap.
DEFAULT_INVENTORY: dict[str, int] = {
    "ambulance": 6,
    "fire_engine": 5,
    "rescue_boat": 4,
    "rescue_team": 18,
    "ground_team": 9,
    "medical_team": 6,
    "hazmat_team": 2,
}

INCIDENT_TYPES: tuple[str, ...] = tuple(RESOURCE_REQUIREMENTS)
RESOURCE_TYPES: tuple[str, ...] = tuple(
    sorted({r for req in RESOURCE_REQUIREMENTS.values() for r in req})
)

# --------------------------------------------------------------------------- #
# Zones - rough categorical distance, NOT real GPS/routing. Hand-authored for
# the locations that actually appear in our demo data (data/replay/*.csv +
# incident locations), same spirit as everything else here: a plain lookup
# table an operator can read and edit, not a computed/geocoded value.
# --------------------------------------------------------------------------- #
ZONES: tuple[str, ...] = ("Central Market", "Ramanthapur", "Gowliguda", "NH44", "Industrial Area")

# 0 = same zone, 1 = adjacent, 2 = far. Symmetric - each unordered pair stored
# once; get_zone_distance() checks both orders. Every zone is implicitly
# distance 0 from itself (handled in get_zone_distance, not listed below).
ZONE_DISTANCE: dict[tuple[str, str], int] = {
    ("Central Market", "Gowliguda"): 1,        # both central, close together
    ("Central Market", "Ramanthapur"): 2,
    ("Central Market", "NH44"): 2,
    ("Central Market", "Industrial Area"): 2,
    ("Ramanthapur", "Gowliguda"): 2,
    ("Ramanthapur", "NH44"): 1,                 # NH44 runs past Ramanthapur
    ("Ramanthapur", "Industrial Area"): 2,
    ("Gowliguda", "NH44"): 2,
    ("Gowliguda", "Industrial Area"): 1,
    ("NH44", "Industrial Area"): 1,             # industrial areas sit along the highway
}

# One hand-picked home zone per resource type, used to seed the default
# inventory pools so the distance tiebreak has real data to work with out of
# the box (see app/seed.py). Purely illustrative - an admin can reassign any
# pool's zone from the Resources page.
DEFAULT_RESOURCE_ZONES: dict[str, str] = {
    "ambulance": "Central Market",
    "fire_engine": "Gowliguda",
    "rescue_boat": "Ramanthapur",
    "rescue_team": "Central Market",
    "ground_team": "NH44",
    "medical_team": "Central Market",
    "hazmat_team": "Industrial Area",
}


def get_zone_distance(zone_a: str | None, zone_b: str | None) -> int | None:
    """
    Rough categorical distance (0/1/2) between two zones, or None if either is
    missing or not a recognised zone. None must never be treated as 0 or as
    "far" by a caller - guessing a fake distance is worse than admitting there
    isn't one; see app/allocation.py: resolve_priority_ties.
    """
    if not zone_a or not zone_b or zone_a not in ZONES or zone_b not in ZONES:
        return None
    if zone_a == zone_b:
        return 0
    return ZONE_DISTANCE.get((zone_a, zone_b), ZONE_DISTANCE.get((zone_b, zone_a)))
