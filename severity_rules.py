"""
severity_rules.py
-----------------
Transparent, deterministic severity scoring for the LIVE PriorityAI pipeline.

This replaces the live use of the RandomForest severity classifier
(`train_severity_model.py`) with a plain weighted sum that an operator can read,
audit and override. The classifier is retained only as an OFFLINE exploratory
tool: its feature importances were used to derive the weights below, and those
weights were then validated against the classifier's own predictions on the
full 1,200-incident dataset (run `python severity_rules.py`):

    rule vs classifier  - class agreement : 94.9%
    rule vs classifier  - Pearson  (score): 0.954
    rule vs classifier  - Spearman (score): 0.942
    rule vs ground truth - class agreement : 83.7%   (classifier itself: 83.3%)

Disagreements are all adjacent-class (MEDIUM<->HIGH, HIGH<->CRITICAL); the rule
never diverges from the classifier by more than one severity level.

Severity depends ONLY on structural incident facts. Report volume and
evidence-quality signals belong to the separate CONFIDENCE dimension and must
never appear in this module.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Weights
# ---------------------------------------------------------------------------
# Derived from the retrained classifier's feature importances
# (models/severity_classifier.joblib: 8 structural features, importances that
# sum to 1.0), scaled by 260 and rounded to whole numbers. The scale factor and
# the class thresholds below were chosen to maximise agreement with the
# classifier over the full dataset -- see `validate()`.
#
# To re-derive after retraining the classifier: `python severity_rules.py`
# prints the freshly suggested weights and the resulting agreement.
SEVERITY_WEIGHTS: dict[str, float] = {
    "person_trapped":          49.0,
    "injury_reported":         44.0,
    "hazardous_material":      44.0,
    "building_collapse_flag":  39.0,
    "fire_present":            34.0,
    "hospital_affected":       17.0,
    "elderly_or_children":     17.0,
    "critical_infrastructure": 16.0,
}

SEVERITY_MAX = 100.0

# Thresholds on the 0-100 score: < LOW | MEDIUM | HIGH | CRITICAL >
SEVERITY_BINS = (20.0, 50.0, 70.0)
SEVERITY_CLASSES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")

# The derivation constant, kept here so validation and any future re-derivation
# use the same value that produced the weights above.
_IMPORTANCE_SCALE = 260.0


def compute_severity(flags: dict) -> float:
    """
    Weighted sum of the structural severity flags, clamped to 0-100.

    `flags` maps feature name -> truthy/falsy value (bool or 0/1). Keys not in
    SEVERITY_WEIGHTS are ignored; missing keys are treated as absent. Pure and
    deterministic -- same input always gives the same score.
    """
    score = sum(
        weight
        for feature, weight in SEVERITY_WEIGHTS.items()
        if flags.get(feature)
    )
    return round(min(float(score), SEVERITY_MAX), 1)


def classify_severity(score: float) -> str:
    """Map a 0-100 severity score to LOW / MEDIUM / HIGH / CRITICAL."""
    low, medium, high = SEVERITY_BINS
    if score < low:
        return "LOW"
    if score < medium:
        return "MEDIUM"
    if score < high:
        return "HIGH"
    return "CRITICAL"


def severity_breakdown(flags: dict) -> dict:
    """
    Full explanation of a severity score for operator-facing display:
    the score, its class, and each flag's individual contribution.
    """
    contributions = {
        feature: weight
        for feature, weight in SEVERITY_WEIGHTS.items()
        if flags.get(feature)
    }
    raw = sum(contributions.values())
    score = round(min(float(raw), SEVERITY_MAX), 1)
    return {
        "score": score,
        "class": classify_severity(score),
        "contributions": dict(sorted(contributions.items(), key=lambda kv: -kv[1])),
        "raw_sum": raw,
        "clamped": raw > SEVERITY_MAX,
    }


# ---------------------------------------------------------------------------
# Validation (offline only - never imported by the live pipeline)
# ---------------------------------------------------------------------------
def validate() -> dict:
    """
    Compare this rule against the trained classifier on the full dataset.
    Requires `data/incidents.csv` and a trained `models/` (run
    generate_data.py + train_severity_model.py first).
    """
    from pathlib import Path
    import numpy as np
    import pandas as pd
    import joblib
    from scipy.stats import pearsonr, spearmanr

    root = Path(__file__).resolve().parent
    features = list(SEVERITY_WEIGHTS)

    df = pd.read_csv(root / "data" / "incidents.csv")
    clf = joblib.load(root / "models" / "severity_classifier.joblib")
    le = joblib.load(root / "models" / "label_encoder.joblib")
    imputer = joblib.load(root / "models" / "imputer.joblib")

    # classifier predictions on the same 8 structural features it was trained on
    model_features = [
        "person_trapped", "injury_reported", "fire_present", "hospital_affected",
        "elderly_or_children", "hazardous_material", "building_collapse_flag",
        "critical_infrastructure",
    ]
    X = pd.DataFrame(imputer.transform(df[model_features]), columns=model_features)
    clf_class = le.inverse_transform(clf.predict(X))
    clf_ord = np.array([SEVERITY_CLASSES.index(c) for c in clf_class])

    # rule predictions
    rule_score = df.apply(lambda r: compute_severity(r.to_dict()), axis=1).to_numpy()
    rule_class = np.array([classify_severity(s) for s in rule_score])

    agree_clf = float((rule_class == clf_class).mean())
    agree_truth = float((rule_class == df["severity_class"].to_numpy()).mean())
    pearson = float(pearsonr(rule_score, clf_ord)[0])
    spearman = float(spearmanr(rule_score, clf_ord)[0])
    rule_ord = np.array([SEVERITY_CLASSES.index(c) for c in rule_class])
    within_one = float((np.abs(rule_ord - clf_ord) <= 1).mean())

    # freshly suggested weights from the current model, for re-derivation
    importances = pd.Series(clf.feature_importances_, index=model_features)
    suggested = (importances * _IMPORTANCE_SCALE).round(1)

    confusion = pd.crosstab(
        pd.Series(rule_class, name="rule"),
        pd.Series(clf_class, name="classifier"),
    ).reindex(index=SEVERITY_CLASSES, columns=SEVERITY_CLASSES, fill_value=0)

    return {
        "n": len(df),
        "class_agreement_vs_classifier": agree_clf,
        "class_agreement_vs_ground_truth": agree_truth,
        "pearson_score_vs_classifier": pearson,
        "spearman_score_vs_classifier": spearman,
        "within_one_class_vs_classifier": within_one,
        "suggested_weights_from_current_model": suggested.to_dict(),
        "confusion": confusion,
    }


if __name__ == "__main__":
    r = validate()
    print(f"dataset rows: {r['n']}\n")
    print(f"class agreement  rule vs classifier   : {r['class_agreement_vs_classifier']:.1%}")
    print(f"class agreement  rule vs ground truth : {r['class_agreement_vs_ground_truth']:.1%}")
    print(f"within one class rule vs classifier   : {r['within_one_class_vs_classifier']:.1%}")
    print(f"Pearson  score   rule vs classifier   : {r['pearson_score_vs_classifier']:.3f}")
    print(f"Spearman score   rule vs classifier   : {r['spearman_score_vs_classifier']:.3f}")
    print("\nconfusion (rows = rule, cols = classifier):")
    print(r["confusion"])
    print(f"\nweights currently in use (scale {_IMPORTANCE_SCALE:g}):")
    for k, v in SEVERITY_WEIGHTS.items():
        print(f"  {k:<26} {v:>5.1f}")
    print("\nsuggested weights from the CURRENT model (retrain -> re-check these):")
    for k, v in r["suggested_weights_from_current_model"].items():
        print(f"  {k:<26} {v:>5.1f}")
