"""
generate_data.py
-----------------
Generates a synthetic incident dataset for PriorityAI, following the factor
model described in the design doc (Module 3: Severity, Module 4: Confidence).

Design principle (from the doc, kept intact here):
    Report volume is treated as evidence toward CONFIDENCE, not a direct
    driver of SEVERITY. This is enforced structurally: `num_reports` is
    generated independently of severity-causing features, and the labeling
    function never reads `num_reports`.

Randomness layers (added so training data isn't unrealistically clean):
    1. Weight jitter    -- each incident's severity weights wobble ±15% from
                           the doc's base weights (no two incidents score the
                           same fire the same way; sensors/reporters vary).
    2. Feature flip noise -- ~4% chance any boolean feature is flipped, to
                           imitate imperfect extraction from noisy text.
    3. Missing values   -- some confidence-related fields are randomly
                           blanked out, to imitate incomplete field reports.
    4. Label noise      -- ~6% of severity_class labels are nudged to an
                           adjacent class, to imitate inconsistent human
                           tagging/QA on the training labels themselves.
"""

from pathlib import Path

import numpy as np
import pandas as pd

from resource_rules import RESOURCE_REQUIREMENTS

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

# Change this seed (or pass seed=None) to get a different random dataset each run.
SEED = 42
RNG = np.random.default_rng(SEED)

FLIP_NOISE_PROB = 0.04      # chance a boolean feature gets randomly flipped
MISSING_VALUE_PROB = 0.05   # chance a confidence field is missing
LABEL_NOISE_PROB = 0.06     # chance the final label is nudged to a neighbor class

INCIDENT_TYPES = [
    "fire", "flood", "building_collapse", "medical_emergency",
    "road_blockage", "power_outage", "chemical_leak", "industrial_accident",
]

# Severity weights, directly lifted from the doc's Module 3 example weights
SEVERITY_WEIGHTS = {
    "person_trapped": 50,
    "injury_reported": 40,
    "fire_present": 50,
    "hospital_affected": 30,
    "elderly_or_children": 20,
    "hazardous_material": 45,
    "building_collapse_flag": 55,
    "critical_infrastructure": 25,
}

SEVERITY_BINS = [0, 30, 55, 78, 1000]          # LOW / MEDIUM / HIGH / CRITICAL
SEVERITY_LABELS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

# Resource requirement per incident type now lives in resource_rules.py (shared
# with the allocator and the API); re-exported here for backwards compatibility.


def _sample_binary(p):
    return RNG.random() < p


def generate_incident(incident_id: int) -> dict:
    incident_type = RNG.choice(INCIDENT_TYPES)

    # --- Severity-causing factors (structural facts about the incident) ---
    person_trapped = _sample_binary(0.25)
    injury_reported = _sample_binary(0.3)
    fire_present = 1 if incident_type == "fire" else _sample_binary(0.05)
    hospital_affected = _sample_binary(0.1)
    elderly_or_children = _sample_binary(0.3)
    hazardous_material = 1 if incident_type in ("chemical_leak", "industrial_accident") else _sample_binary(0.03)
    building_collapse_flag = 1 if incident_type == "building_collapse" else _sample_binary(0.02)
    critical_infrastructure = _sample_binary(0.15)

    raw_features = {
        "person_trapped": person_trapped,
        "injury_reported": injury_reported,
        "fire_present": fire_present,
        "hospital_affected": hospital_affected,
        "elderly_or_children": elderly_or_children,
        "hazardous_material": hazardous_material,
        "building_collapse_flag": building_collapse_flag,
        "critical_infrastructure": critical_infrastructure,
    }

    # --- Randomness layer 2: feature flip noise (imperfect extraction) ---
    # A small chance any single boolean gets flipped before it's used to score
    # or stored -- e.g. "injury_reported" mis-tagged from an ambiguous text report.
    noisy_features = {}
    for name, val in raw_features.items():
        if RNG.random() < FLIP_NOISE_PROB:
            val = 1 - val
        noisy_features[name] = val

    # --- Randomness layer 1: per-incident weight jitter ---
    # Each incident applies its own noisy version of the base weights (±15%),
    # so the same feature combination doesn't always score identically.
    jittered_weights = {
        f: w * RNG.uniform(0.85, 1.15) for f, w in SEVERITY_WEIGHTS.items()
    }

    severity_score = sum(
        jittered_weights[f] for f, val in noisy_features.items() if val
    )
    # extra additive noise + clip to 0-100 so the label boundary isn't perfectly deterministic
    severity_score = int(np.clip(severity_score + RNG.normal(0, 6), 0, 100))
    severity_class = pd.cut(
        [severity_score], bins=SEVERITY_BINS, labels=SEVERITY_LABELS, include_lowest=True
    )[0]

    # --- Randomness layer 4: label noise (simulates inconsistent human tagging) ---
    # A minority of labels get nudged one class up or down from what the score
    # implies -- real severity labels in practice come from human triage notes,
    # which disagree with each other near class boundaries.
    if RNG.random() < LABEL_NOISE_PROB:
        idx = SEVERITY_LABELS.index(str(severity_class))
        shift = RNG.choice([-1, 1])
        idx = int(np.clip(idx + shift, 0, len(SEVERITY_LABELS) - 1))
        severity_class = SEVERITY_LABELS[idx]

    # use the (possibly flipped) features for the stored row too, so labels
    # and stored features stay consistent with each other
    person_trapped = noisy_features["person_trapped"]
    injury_reported = noisy_features["injury_reported"]
    fire_present = noisy_features["fire_present"]
    hospital_affected = noisy_features["hospital_affected"]
    elderly_or_children = noisy_features["elderly_or_children"]
    hazardous_material = noisy_features["hazardous_material"]
    building_collapse_flag = noisy_features["building_collapse_flag"]
    critical_infrastructure = noisy_features["critical_infrastructure"]

    # --- Confidence-causing factors (evidence quality, INDEPENDENT of severity) ---
    num_sources = RNG.integers(1, 4)                 # 1-3 independent source types
    ground_confirmed = _sample_binary(0.35)
    agreement_ratio = float(np.clip(RNG.normal(0.75, 0.2), 0, 1))  # how much reports agree
    recency_minutes = RNG.integers(1, 180)           # how old is the latest report

    # num_reports driven by "virality"/topic salience, NOT severity -> the core doc principle
    virality = RNG.choice([1, 1, 1, 2, 2, 5], p=[0.35, 0.2, 0.15, 0.15, 0.1, 0.05])
    num_reports = int(RNG.poisson(8) * virality) + 1

    confidence_score = (
        20 * num_sources
        + 25 * ground_confirmed
        + 30 * agreement_ratio
        + 15 * (1 - min(recency_minutes / 180, 1))
    )
    confidence_score = float(np.clip(confidence_score + RNG.normal(0, 5), 0, 100))

    row = {
        "incident_id": incident_id,
        "incident_type": incident_type,
        # severity-driving features
        "person_trapped": int(person_trapped),
        "injury_reported": int(injury_reported),
        "fire_present": int(fire_present),
        "hospital_affected": int(hospital_affected),
        "elderly_or_children": int(elderly_or_children),
        "hazardous_material": int(hazardous_material),
        "building_collapse_flag": int(building_collapse_flag),
        "critical_infrastructure": int(critical_infrastructure),
        # confidence-driving features (kept separate from severity on purpose)
        "num_sources": int(num_sources),
        "ground_confirmed": int(ground_confirmed),
        "agreement_ratio": round(agreement_ratio, 2),
        "recency_minutes": int(recency_minutes),
        "num_reports": num_reports,
        # targets / derived
        "severity_score": severity_score,
        "severity_class": str(severity_class),
        "confidence_score": round(confidence_score, 1),
    }

    # --- Randomness layer 3: missing values on confidence fields ---
    # Imitates incomplete field reports (e.g. ground team hasn't confirmed yet,
    # or recency wasn't logged). Handled downstream via imputation at training time.
    for field in ("num_sources", "ground_confirmed", "agreement_ratio", "recency_minutes"):
        if RNG.random() < MISSING_VALUE_PROB:
            row[field] = np.nan

    return row


def generate_dataset(n=1200) -> pd.DataFrame:
    rows = [generate_incident(i) for i in range(1, n + 1)]
    df = pd.DataFrame(rows)
    return df


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        RNG = np.random.default_rng(int(sys.argv[1]))  # override seed, e.g. `python generate_data.py 7`

    df = generate_dataset(1200)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(DATA_DIR / "incidents.csv", index=False)
    print(df["severity_class"].value_counts())
    print(f"\nMissing values per column:\n{df.isna().sum()[df.isna().sum() > 0]}")
    print(df.head())
    print(f"\nSaved {len(df)} rows -> data/incidents.csv")
