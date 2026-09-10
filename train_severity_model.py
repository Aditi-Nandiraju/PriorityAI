"""
train_severity_model.py
------------------------
Trains the PriorityAI severity classifier.

Two approaches are built, per the request ("clusters or just classified"):

1. SUPERVISED CLASSIFIER (primary, recommended for production use)
   A RandomForestClassifier predicts severity_class (LOW/MEDIUM/HIGH/CRITICAL)
   from raw incident features. This is what should actually drive resource
   allocation, because it gives calibrated class probabilities and transparent
   feature importances an operator can be shown.

2. UNSUPERVISED CLUSTERING (comparison / exploratory view)
   KMeans groups incidents purely by feature similarity, with no labels.
   Useful for "does the operational data naturally separate into severity-like
   groups?" but clusters are NOT ordered or labeled by severity a priori, so
   they are re-mapped to severity levels by their average severity_score only
   for reporting/visualization -- never for allocation decisions.

Severity is predicted from the 8 STRUCTURAL incident features ONLY. Report
volume (`num_reports`) and evidence-quality signals (`num_sources`,
`ground_confirmed`, `agreement_ratio`, `recency_minutes`) are deliberately
excluded: they belong to the separate CONFIDENCE dimension (computed in
generate_data.py) and must never inform severity -- "the loudest incident is
not necessarily the most urgent one".
"""

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder, StandardScaler

BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR / "data" / "incidents.csv"
MODEL_DIR = BASE_DIR / "models"
OUTPUT_DIR = BASE_DIR / "outputs"
MODEL_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Structural incident facts only. Confidence/evidence-quality signals and
# report volume are NOT here by design -- see module docstring.
FEATURE_COLS = [
    "person_trapped", "injury_reported", "fire_present", "hospital_affected",
    "elderly_or_children", "hazardous_material", "building_collapse_flag",
    "critical_infrastructure",
]

TARGET_COL = "severity_class"
SEVERITY_ORDER = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]


def load_data():
    return pd.read_csv(DATA_PATH)


def train_classifier(df: pd.DataFrame):
    X_raw = df[FEATURE_COLS]
    y = df[TARGET_COL]

    # The dataset now contains real missing values (Randomness layer 3) --
    # impute with the median so the classifier can still handle incomplete
    # field reports, same as a production system would need to.
    imputer = SimpleImputer(strategy="median")
    X = pd.DataFrame(imputer.fit_transform(X_raw), columns=FEATURE_COLS, index=X_raw.index)
    joblib.dump(imputer, f"{MODEL_DIR}/imputer.joblib")

    le = LabelEncoder()
    le.fit(SEVERITY_ORDER)
    y_enc = le.transform(y)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y_enc, test_size=0.2, random_state=42, stratify=y_enc
    )

    clf = RandomForestClassifier(
        n_estimators=300, max_depth=8, min_samples_leaf=3,
        class_weight="balanced", random_state=42,
    )
    clf.fit(X_train, y_train)

    y_pred = clf.predict(X_test)
    report = classification_report(
        y_test, y_pred, target_names=le.classes_, output_dict=True
    )
    cm = confusion_matrix(y_test, y_pred)

    importances = pd.Series(clf.feature_importances_, index=FEATURE_COLS).sort_values(ascending=False)

    joblib.dump(clf, f"{MODEL_DIR}/severity_classifier.joblib")
    joblib.dump(le, f"{MODEL_DIR}/label_encoder.joblib")

    return clf, le, report, cm, importances, (X_test, y_test, y_pred)


def train_clustering(df: pd.DataFrame, n_clusters=4):
    X_raw = df[FEATURE_COLS]
    imputer = SimpleImputer(strategy="median")
    X = imputer.fit_transform(X_raw)
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    km = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    cluster_labels = km.fit_predict(X_scaled)

    df_clustered = df.copy()
    df_clustered["cluster"] = cluster_labels

    # Map clusters -> severity-like ranking purely by mean severity_score,
    # for human-readable reporting only (NOT used as ground truth).
    cluster_means = df_clustered.groupby("cluster")["severity_score"].mean().sort_values()
    rank_to_label = {cluster: label for cluster, label in zip(cluster_means.index, SEVERITY_ORDER)}
    df_clustered["cluster_severity_guess"] = df_clustered["cluster"].map(rank_to_label)

    pca = PCA(n_components=2, random_state=42)
    coords = pca.fit_transform(X_scaled)
    df_clustered["pca_x"] = coords[:, 0]
    df_clustered["pca_y"] = coords[:, 1]

    joblib.dump({"scaler": scaler, "kmeans": km, "pca": pca, "rank_to_label": rank_to_label},
                f"{MODEL_DIR}/clustering_bundle.joblib")

    # agreement between the unsupervised clusters and the true severity labels
    agreement = (df_clustered["cluster_severity_guess"] == df_clustered["severity_class"]).mean()

    return df_clustered, agreement


if __name__ == "__main__":
    df = load_data()

    print("=" * 60)
    print("1) SUPERVISED SEVERITY CLASSIFIER")
    print("=" * 60)
    clf, le, report, cm, importances, split = train_classifier(df)
    print(pd.DataFrame(report).T.round(3))
    print("\nConfusion matrix (rows=true, cols=pred), order:", list(le.classes_))
    print(cm)
    print("\nFeature importances (higher = more influence on predicted severity):")
    print(importances.round(3))
    print(
        "\n-> Severity uses the 8 structural features only. Report volume and "
        "evidence-quality signals are excluded by design and feed the separate "
        "confidence dimension instead."
    )

    print("\n" + "=" * 60)
    print("2) UNSUPERVISED CLUSTERING (comparison view)")
    print("=" * 60)
    df_clustered, agreement = train_clustering(df)
    print(df_clustered.groupby("cluster")[["severity_score", "confidence_score"]].mean().round(1))
    print(f"\nCluster-vs-true-label agreement rate: {agreement:.1%}")
    print(
        "-> Clustering gives a rough exploratory grouping but is noticeably less accurate "
        "than the supervised classifier; kept only as a comparison view, not for allocation."
    )

    df_clustered.to_csv(OUTPUT_DIR / "incidents_with_predictions.csv", index=False)

    summary = {
        "classifier_macro_f1": report["macro avg"]["f1-score"],
        "classifier_accuracy": report["accuracy"],
        "clustering_agreement_with_true_severity": agreement,
        "severity_features": FEATURE_COLS,
        "severity_feature_importance": importances.round(3).to_dict(),
    }
    with open(OUTPUT_DIR / "model_summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    print("\nSaved model_summary.json and incidents_with_predictions.csv")
