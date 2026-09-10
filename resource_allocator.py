"""
resource_allocator.py
----------------------
Implements the doc's Priority Engine (Sec 17) + Response Simulation (Sec 15-16)
on top of the trained severity classifier.

Priority = f(severity_class, confidence_score, resource_urgency)
Resources are matched by incident_type -> required resource types (Sec 14),
then allocated greedily in priority order. Incidents that cannot be fully
resourced are flagged as a response gap (Sec 15/16), never silently dropped.

This module does NOT autonomously dispatch -- it produces a recommended
allocation plan for a human operator to approve, per the doc's stated
non-negotiable: "AI recommendations do not autonomously dispatch resources."
"""

from pathlib import Path

import joblib
import pandas as pd

from resource_rules import DEFAULT_INVENTORY, RESOURCE_REQUIREMENTS
from train_severity_model import FEATURE_COLS

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
MODEL_DIR = BASE_DIR / "models"
OUTPUT_DIR = BASE_DIR / "outputs"

SEVERITY_WEIGHT = {"CRITICAL": 100, "HIGH": 75, "MEDIUM": 45, "LOW": 15}


def load_classifier():
    clf = joblib.load(f"{MODEL_DIR}/severity_classifier.joblib")
    le = joblib.load(f"{MODEL_DIR}/label_encoder.joblib")
    imputer = joblib.load(f"{MODEL_DIR}/imputer.joblib")
    return clf, le, imputer


def classify_incidents(df: pd.DataFrame) -> pd.DataFrame:
    clf, le, imputer = load_classifier()
    X = pd.DataFrame(imputer.transform(df[FEATURE_COLS]), columns=FEATURE_COLS, index=df.index)
    pred_idx = clf.predict(X)
    proba = clf.predict_proba(X)
    df = df.copy()
    df["predicted_severity"] = le.inverse_transform(pred_idx)
    df["severity_confidence_pct"] = (proba.max(axis=1) * 100).round(1)
    return df


def compute_priority(df: pd.DataFrame) -> pd.DataFrame:
    """
    Priority score combines:
      - predicted severity (main driver, from the classifier)
      - evidence confidence_score (how sure we are it's real)
    Report volume is deliberately excluded here too.
    """
    df = df.copy()
    df["priority_score"] = (
        0.7 * df["predicted_severity"].map(SEVERITY_WEIGHT)
        + 0.3 * df["confidence_score"]
    ).round(1)
    return df.sort_values("priority_score", ascending=False).reset_index(drop=True)


def allocate_resources(df: pd.DataFrame, inventory: dict) -> tuple[list[dict], dict]:
    """
    Greedy allocation in priority order. `inventory` is mutated in place to
    reflect remaining available units (mirrors Sec 16's "available/busy" panel).
    Returns (allocation_log, final_inventory).
    """
    inventory = dict(inventory)  # don't mutate caller's dict
    log = []

    for _, row in df.iterrows():
        req = RESOURCE_REQUIREMENTS.get(row["incident_type"], {})
        allocation = {}
        shortages = {}

        for resource_type, qty_needed in req.items():
            available = inventory.get(resource_type, 0)
            granted = min(available, qty_needed)
            allocation[resource_type] = granted
            inventory[resource_type] = available - granted
            if granted < qty_needed:
                shortages[resource_type] = qty_needed - granted

        status = "FULLY_RESOURCED" if not shortages else (
            "PARTIALLY_RESOURCED" if allocation and any(v > 0 for v in allocation.values()) else "UNRESOURCED"
        )

        log.append({
            "incident_id": row["incident_id"],
            "incident_type": row["incident_type"],
            "predicted_severity": row["predicted_severity"],
            "priority_score": row["priority_score"],
            "required": req,
            "allocated": allocation,
            "shortages": shortages,
            "status": status,
        })

    return log, inventory


def print_report(log: list[dict], final_inventory: dict, top_n=15):
    print(f"{'ID':<5}{'Type':<20}{'Severity':<10}{'Priority':<10}{'Status':<20}Shortage")
    print("-" * 90)
    for entry in log[:top_n]:
        shortage_str = ", ".join(f"{k}:{v}" for k, v in entry["shortages"].items()) or "-"
        print(
            f"{entry['incident_id']:<5}{entry['incident_type']:<20}{entry['predicted_severity']:<10}"
            f"{entry['priority_score']:<10}{entry['status']:<20}{shortage_str}"
        )

    gaps = [e for e in log if e["shortages"]]
    print(f"\n[!] Response gaps detected: {len(gaps)} of {len(log)} incidents "
          f"could not be fully resourced with current inventory.")
    print("\nRemaining inventory after allocation:")
    for k, v in final_inventory.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    df = pd.read_csv(DATA_DIR / "incidents.csv")

    # Simulate a live "current incident queue": a snapshot of active/unresolved incidents
    active_incidents = df.sample(30, random_state=7).reset_index(drop=True)

    df_pred = classify_incidents(active_incidents)
    df_ranked = compute_priority(df_pred)

    # A deliberately CONSTRAINED inventory, to demonstrate shortages (Sec 16)
    inventory = dict(DEFAULT_INVENTORY)

    print("Starting inventory:", inventory)
    print()
    log, final_inventory = allocate_resources(df_ranked, inventory)
    print_report(log, final_inventory, top_n=30)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(log).to_json(
        OUTPUT_DIR / "allocation_log.json", orient="records", indent=2
    )
    print("\nSaved outputs/allocation_log.json")
