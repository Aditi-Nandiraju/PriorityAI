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
