# PriorityAI — backend core

A working, offline, end-to-end prototype of the pipeline:

```
synthetic reports -> incident fusion -> severity/confidence/impact scoring
    -> resource requirement inference -> inventory + allocation simulation
```

Nothing here calls an external API or downloads a model — TF-IDF is used for
text similarity, so it runs anywhere with no setup beyond `pip install`.

## Run it

```bash
pip install -r requirements.txt

# CLI demo — prints the full pipeline for the synthetic dataset
python3 demo.py

# API server — for the frontend to hit
uvicorn app.api:app --reload --port 8000
# then see http://localhost:8000/docs for interactive API docs
```

## What's real vs. what's a placeholder

| Piece | Status | Notes |
|---|---|---|
| Incident fusion | Working, simplistic | TF-IDF + location + type match. Swap in `sentence-transformers` embeddings for better generalization if you have time — the function signature in `fusion.py` doesn't need to change. |
| Incident classification | **Working — local ML** | `app/classifier.py`: TF-IDF + calibrated LinearSVC, trained from scratch on `app/training_data.py`, no downloads, no API calls. 98% agreement with hand-labels on the demo dataset after one training-data fix (see below). Extend `training_data.py` with more/better examples — especially vernacular/code-mixed phrasing if you build the multilingual angle — before demo day. |
| Severity / confidence / impact scoring | Working, rule-based | Deliberately kept explainable — see `scoring.py`. This is a good place to spend polish time since it's your core differentiator, not a place to add ML. |
| Conflict detection | Working, narrow | Only checks a couple of known claim keys (`structure`, `trapped`). Extend the claim schema for more conflict types. |
| Resource requirement inference | Working, rule-based | Lookup table in `resource_rules.py`. Easy to extend, easy to explain to judges. |
| Allocation simulation | Working | `simulation.py` — allocate/release/shortage detection, all deterministic. This is your best demo moment. |
| API | Working, in-memory state | No DB. Fine for a hackathon demo; add persistence only if you have spare time. |

## Suggested week plan from here

- **Day 1–2 (done as of this file):** backend pipeline + API — get it working end-to-end on synthetic data.
- **Day 2–3:** replace the placeholder classification with either (a) a small classifier trained on your synthetic set, or (b) honest keyword rules — don't over-invest here, it's not your differentiator.
- **Day 3–4:** frontend skeleton — incident board, incident detail, resource panel, hitting the API above.
- **Day 5:** simulation panel UI — the interactive "allocate and watch consequences" screen. This is what should get the most polish.
- **Day 6:** integrate real synthetic dataset variety (more incident types/locations), write your 3-minute demo script and pick the exact scenario you'll walk judges through (recommend: the building-collapse-vs-flood priority contrast, then the Scenario 2 shortage moment in `demo.py`).
- **Day 7:** buffer, bug fixes, rehearse.

## Known rough edges to fix before demo day

- `_severity()` and `_confidence()` in `scoring.py` are simple weighted rules — tune the weights against your final synthetic dataset so the numbers "feel right" to a judge (e.g. building collapse should visibly outrank a big flood).
- Fusion threshold (`SIMILARITY_THRESHOLD` in `fusion.py`) was tuned against the sample dataset only — recheck after you expand the dataset.
- No undo/rollback in the simulation yet — `ResourceInventory.release()` exists but the API doesn't expose it. Add a `/release/{incident_id}` endpoint if you want a "what if I reassign instead" demo flow.
- Classifier training data (`app/training_data.py`) is small (~40 examples) and hand-written — it will systematically mislabel any phrasing pattern it hasn't seen (we hit exactly this with flood reports that also mentioned "road" and "traffic" — fixed by adding disambiguating examples). Before demo day, run `python3 demo.py` and manually check `_predicted_type` vs `incident_type` agreement on your final dataset — don't assume it generalizes without checking.
- `classifier.joblib` gets cached on disk after first training — delete it and rerun if you change `training_data.py` and don't see the update take effect.
- Everything here is local/offline by design — no API keys, no external calls at inference time. The only exception, if you add it, is downloading pretrained transformer weights (e.g. `sentence-transformers`) once during development; after that it's offline too.
