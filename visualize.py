from pathlib import Path

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from sklearn.metrics import ConfusionMatrixDisplay

from train_severity_model import (FEATURE_COLS, SEVERITY_ORDER, load_data,
                                   train_classifier, train_clustering)

OUT = Path(__file__).resolve().parent / "outputs"
OUT.mkdir(parents=True, exist_ok=True)

df = load_data()
clf, le, report, cm, importances, (X_test, y_test, y_pred) = train_classifier(df)
df_clustered, agreement = train_clustering(df)

# 1. Feature importance
fig, ax = plt.subplots(figsize=(7, 5))
importances.sort_values().plot(kind="barh", ax=ax, color="#c0392b")
ax.set_title("Severity classifier — feature importance")
ax.set_xlabel("Importance")
fig.tight_layout()
fig.savefig(f"{OUT}/feature_importance.png", dpi=150)
plt.close(fig)

# 2. Confusion matrix
fig, ax = plt.subplots(figsize=(5.5, 5))
disp = ConfusionMatrixDisplay(confusion_matrix=cm, display_labels=le.classes_)
disp.plot(ax=ax, cmap="Reds", colorbar=False)
ax.set_title("Severity classifier — confusion matrix")
fig.tight_layout()
fig.savefig(f"{OUT}/confusion_matrix.png", dpi=150)
plt.close(fig)

# 3. Clustering PCA scatter, colored by TRUE severity vs colored by CLUSTER
fig, axes = plt.subplots(1, 2, figsize=(11, 5))
palette = {"LOW": "#2ecc71", "MEDIUM": "#f1c40f", "HIGH": "#e67e22", "CRITICAL": "#c0392b"}

for label in SEVERITY_ORDER:
    sub = df_clustered[df_clustered["severity_class"] == label]
    axes[0].scatter(sub["pca_x"], sub["pca_y"], s=10, alpha=0.6, label=label, color=palette[label])
axes[0].set_title("True severity_class (ground truth)")
axes[0].legend(fontsize=8)

for cluster_id in sorted(df_clustered["cluster"].unique()):
    sub = df_clustered[df_clustered["cluster"] == cluster_id]
    guess = sub["cluster_severity_guess"].iloc[0]
    axes[1].scatter(sub["pca_x"], sub["pca_y"], s=10, alpha=0.6,
                     label=f"cluster {cluster_id} (~{guess})")
axes[1].set_title(f"KMeans clusters (unsupervised)\nagreement with true label: {agreement:.1%}")
axes[1].legend(fontsize=8)

fig.suptitle("Supervised labels vs. unsupervised clustering — same PCA projection")
fig.tight_layout()
fig.savefig(f"{OUT}/clustering_vs_classification.png", dpi=150)
plt.close(fig)

print("Saved 3 plots to outputs/:")
print(" - feature_importance.png")
print(" - confusion_matrix.png")
print(" - clustering_vs_classification.png")
