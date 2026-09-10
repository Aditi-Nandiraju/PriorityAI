"""
scripts/load_incidents_csv.py
-----------------------------
Replay rows from data/incidents.csv through the LIVE API to

  1. populate the demo database with realistic incidents, and
  2. prove severity_rules.py scores identically online (in the API) and offline
     (imported here, the same code the derivation script used).

For each sampled row:
  * POST /incidents/manual  with the 8 structural flags read straight from the
    CSV, location "Unknown", incident_type from the CSV.
  * optionally POST one /reports/manual per SELECTED source
    (social_media / citizen_reports / ground_team), with text synthesised from
    the row. Unselected sources are skipped. These sources are the same ones you
    pick/enter by hand in the CMS Ingest screen.

Then it prints, per row:
    CSV            - the generator's own severity_score / severity_class
                     (jittered + label-noised; a reference point, not ground truth)
    offline rule   - severity_rules.compute_severity() run locally here
    online API     - what POST /incidents/manual computed and returned
and checks offline == online for every row (that is the real validation).

Each POST creates its own audit_log row under whichever seeded account is used.

    python scripts/load_incidents_csv.py                     # 25 rows, all 3 sources
    python scripts/load_incidents_csv.py 50
    python scripts/load_incidents_csv.py 10 --sources ground_team,social_media
    python scripts/load_incidents_csv.py 10 --sources none    # incidents only
    python scripts/load_incidents_csv.py 10 --account operator
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

from severity_rules import classify_severity, compute_severity  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "incidents.csv"

STRUCTURAL_FLAGS = [
    "person_trapped",
    "injury_reported",
    "fire_present",
    "hospital_affected",
    "elderly_or_children",
    "hazardous_material",
    "building_collapse_flag",
    "critical_infrastructure",
]
ALL_SOURCES = ("social_media", "citizen_reports", "ground_team")
SEEDED_ACCOUNTS = {"admin": "admin123", "operator": "operator123", "viewer": "viewer123"}


def http(method: str, url: str, token: str | None = None, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read() or "null")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or "null")
    except urllib.error.URLError as exc:
        raise SystemExit(f"cannot reach the API at {url} — is uvicorn running?  ({exc})")


def as_bool(value: str) -> bool:
    return str(value).strip() in {"1", "1.0", "true", "True"}


def synth_text(row: dict, active: list[str]) -> str:
    kind = row["incident_type"].replace("_", " ")
    if active:
        return f"Reported {kind} at Unknown - " + ", ".join(f.replace("_", " ") for f in active) + "."
    return f"Reported {kind} at Unknown - details unconfirmed."


def report_body(source: str, row: dict, active: list[str]) -> dict:
    body = {"source_type": source, "text": synth_text(row, active), "location": "Unknown"}
    if source == "social_media":
        body.update(platform="twitter", handle="@field_watch")
    elif source == "ground_team":
        body.update(team_id=f"GT-{row['incident_id']}", unit="field", verified=True)
    # citizen_reports: text + location only, by design
    return body


def resolve_sources(raw: str, parser: argparse.ArgumentParser) -> list[str]:
    raw = raw.strip().lower()
    if raw in {"", "none"}:
        return []
    if raw == "all":
        return list(ALL_SOURCES)
    picked = [s.strip() for s in raw.split(",") if s.strip()]
    unknown = [s for s in picked if s not in ALL_SOURCES]
    if unknown:
        parser.error(f"unknown source(s) {unknown}; choose from {list(ALL_SOURCES)} / all / none")
    # dedupe, keep canonical order
    return [s for s in ALL_SOURCES if s in picked]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("n", nargs="?", type=int, default=25, help="rows to sample (default 25)")
    parser.add_argument("--api", default="http://localhost:8000", help="API base URL")
    parser.add_argument(
        "--account",
        default="admin",
        choices=sorted(SEEDED_ACCOUNTS),
        help="seeded account to authenticate as (default admin)",
    )
    parser.add_argument("--password", help="override the seeded account password")
    parser.add_argument(
        "--sources",
        default="all",
        help=f"report sources to also create per row: {','.join(ALL_SOURCES)} | all | none "
        "(default all)",
    )
    parser.add_argument("--seed", type=int, default=7, help="sampling RNG seed (default 7)")
    args = parser.parse_args()

    selected = resolve_sources(args.sources, parser)
    unselected = [s for s in ALL_SOURCES if s not in selected]

    if not CSV_PATH.exists():
        raise SystemExit(f"{CSV_PATH} not found — run:  python generate_data.py")

    with CSV_PATH.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    n = max(0, min(args.n, len(rows)))
    sample = random.Random(args.seed).sample(rows, n)

    password = args.password or SEEDED_ACCOUNTS[args.account]
    code, tok = http(
        "POST", f"{args.api}/auth/login", body={"username": args.account, "password": password}
    )
    if code != 200:
        raise SystemExit(f"login failed ({code}): {tok}")
    token = tok["access_token"]

    print(f"authenticated as {tok['username']} ({tok['role']})")
    print(f"report sources   selected: {selected or '(none)'}")
    print(f"                 unselected: {unselected}")
    print(f"loading {n} incident(s) from {CSV_PATH.name}\n")

    results: list[dict] = []
    reports_created = 0
    for row in sample:
        flags = {f: as_bool(row[f]) for f in STRUCTURAL_FLAGS}  # all 8, as booleans
        active = [f for f in STRUCTURAL_FLAGS if flags[f]]

        offline_score = compute_severity(flags)
        offline_class = classify_severity(offline_score)

        code, inc = http(
            "POST",
            f"{args.api}/incidents/manual",
            token=token,
            body={"incident_type": row["incident_type"], "location": "Unknown", "flags": flags},
        )
        if code != 200:
            print(f"  ! row {row['incident_id']}: /incidents/manual failed ({code}): {inc}")
            continue

        results.append(
            {
                "id": row["incident_id"],
                "type": row["incident_type"],
                "csv_score": float(row["severity_score"]),
                "csv_class": row["severity_class"],
                "offline_score": offline_score,
                "offline_class": offline_class,
                "api_score": inc["severity_score"],
                "api_class": inc["severity_class"],
            }
        )

        for src in selected:
            c, r = http(
                "POST", f"{args.api}/reports/manual", token=token, body=report_body(src, row, active)
            )
            if c == 200:
                reports_created += 1
            else:
                print(f"  ! row {row['incident_id']}: report[{src}] failed ({c}): {r}")

    if not results:
        print("no incidents were created.")
        return 1

    # -------- comparison --------
    print(
        f"{'id':>5}  {'type':<19} "
        f"{'CSV':>13}  {'offline rule':>13}  {'online API':>13}  check"
    )
    print("-" * 92)
    mismatch = 0
    csv_agree = 0
    for r in results:
        identical = (
            r["offline_score"] == r["api_score"] and r["offline_class"] == r["api_class"]
        )
        mismatch += not identical
        csv_agree += r["api_class"] == r["csv_class"]
        print(
            f"{r['id']:>5}  {r['type']:<19} "
            f"{r['csv_score']:>6.0f} {r['csv_class']:<6} "
            f"{r['offline_score']:>6.1f} {r['offline_class']:<6} "
            f"{r['api_score']:>6.1f} {r['api_class']:<6} "
            f"{'ok' if identical else 'DIFF'}"
        )
    print("-" * 92)

    total = len(results)
    print(f"\nincidents created : {total}")
    print(f"reports created   : {reports_created}" + (f"  ({', '.join(selected)})" if selected else ""))
    print(
        f"\noffline vs online severity_rules : {total - mismatch}/{total} identical  "
        + ("✓ severity_rules runs the same online as offline" if mismatch == 0 else "✗ MISMATCH — investigate")
    )
    print(
        f"online rule vs CSV severity_class : {csv_agree}/{total} agree ({csv_agree / total:.0%})  "
        "— expected below 100%: the CSV class carries the generator's jitter + label noise, "
        "the rule is the clean weighted sum"
    )
    return 0 if mismatch == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
