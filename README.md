# PriorityAI

Disaster-response decision-support prototype: **evidence → incident → severity
+ confidence → resource requirement → allocation → operator decision**, with
nothing ever auto-dispatched.

Two rules hold everywhere in this codebase:

1. **Severity ("how bad") and confidence ("how sure") are separate dimensions**
   and never feed each other. Report volume affects confidence only.
2. **The live path is deterministic and explainable** — plain weighted
   formulas and rule lookups (`severity_rules.py`, `resource_rules.py`,
   `app/allocation.py`), not a model making runtime decisions. The
   RandomForest classifier (`train_severity_model.py`) is an offline
   exploration tool only — its feature importances were used to *derive* the
   live formula, once, and are validated against it (`python severity_rules.py`).

## Architecture

```
generate_data.py ──▶ data/incidents.csv ──▶ train_severity_model.py (offline)
                                                       │
                                          feature importances derive weights
                                                       ▼
                                             severity_rules.py (live formula)
                                                       │
                        ┌──────────────────────────────┴───────────────────────┐
                        ▼                                                      ▼
                  app/ (FastAPI + MongoDB)  ◀────────────────────  frontend/ (React)
                  JWT auth · reports · incidents                   BoardDataContext holds the
                  resource_rules.py + app/allocation.py             live incidents/resources/plan
                  (greedy / optimal ILP)                            above the routed pages, so it
                  audit_log on every mutation                       survives navigating around
```

## Prerequisites

- Python 3.11+ (developed on 3.13)
- Node.js 18+ and npm
- A MongoDB connection string — [Atlas](https://www.mongodb.com/atlas) free
  tier works. **Not required to get started**: if it can't connect, the API
  falls back to an in-process store automatically (data won't persist across
  restarts, but every endpoint still works).

## 1. One-time setup

```bash
# from the project root
python -m venv .venv
.venv\Scripts\Activate.ps1          # Windows PowerShell
# source .venv/bin/activate         # macOS/Linux

pip install -r requirements.txt
```

Create `.env` from the template and fill in your Mongo connection string:

```bash
cp .env.example .env
```

```ini
MONGODB_URI="mongodb+srv://<user>:<password>@<cluster>.mongodb.net"
JWT_SECRET="<generate one — see below>"
```

Generate a real `JWT_SECRET` (don't ship the placeholder):

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

`.env` is git-ignored. **Never commit it** — it holds real database
credentials and the JWT signing secret.

Install the frontend:

```bash
cd frontend
npm install
cd ..
```

## 2. Pre-flight check (do this after any Mongo-related change)

```bash
python scripts/check_mongo_connection.py
```

Confirms `.env` → Atlas → read/write permissions end-to-end, and tells you
exactly what's wrong (DNS/network vs. wrong password vs. missing role) if it
isn't. A green run here means the database layer isn't the cause of anything
that breaks later.

## 3. Create demo accounts (once, on a fresh database)

```bash
python scripts/seed_users.py
```

Safe to re-run — skips usernames that already exist. Creates:

| username | password | role |
|---|---|---|
| `admin` | `admin123` | admin |
| `operator` | `operator123` | operator |
| `viewer` | `viewer123` | operator |

(If Mongo is unreachable, the API seeds these same accounts into its
in-memory fallback automatically on startup instead — no separate step needed.)

## 4. Run it — two terminals

**Terminal 1 — backend**, from the project root, venv active:

```bash
python -m uvicorn app.main:app --reload --port 8000
```

Watch for `Connected to MongoDB Atlas` (or the in-memory fallback line — the
app still runs either way). Interactive API docs: http://localhost:8000/docs

**Terminal 2 — frontend**:

```bash
cd frontend
npm run dev
```

It prints the local URL — `http://localhost:5173` (or the next free port if
that one's taken). Open it and log in with one of the accounts above.

> **Windows note:** use `python`, not `python3`. A venv puts `python.exe` on
> your `PATH` but not `python3.exe`, so `python3` silently falls through to
> the Microsoft Store Python stub, which has none of your packages installed.
> Check with `python -c "import sys; print(sys.executable)"` — it should
> point inside `.venv`.

## Using the app

Six views behind login, role-gated (`frontend/src/nav.js`):

| View | Who | What |
|---|---|---|
| **Login** | everyone | JWT via `/auth/login` |
| **Ingest / Manual Entry** | operator, admin | 3 tabs: paste text (splits into reports on blank lines), upload CSV (source-aware columns; an "Uploaded files" log shows every CSV ingested, by whom, and what came of it), single structured incident entry with a live severity preview |
| **Incident Board** | operator, admin | cards + a collapsible allocation-simulation panel (`optimal` ILP or `greedy`, with its own "only under-resourced" filter on the plan table); highlights under-resourced cards live; inline "assign suggested" per card; a **Demo mode** toggle that periodically auto-resolves a fully-resourced incident for presentation purposes (client-side only — see the TODO in `frontend/src/hooks/useDemoMode.js`) |
| **Incident Detail** | operator, admin | severity breakdown, requirement vs. suggestion vs. committed assignment, who else is competing for the same resource, resolve/reopen |
| **Resource Inventory** | view: everyone · edit: admin | pool quantities, total/committed/available |
| **Activity Log** | admin | every mutating action, attributed to the operator who did it |

Demo mode, the live plan, and the incident list all live in
`frontend/src/context/BoardDataContext.jsx`, above the routed pages — so
toggling demo mode on and then clicking into an incident no longer resets it;
it keeps running (and toasting) no matter which page you're on.

## Optional: replay real data through the API

```bash
python scripts/load_incidents_csv.py 25 --sources social_media,ground_team
```

Samples rows from `data/incidents.csv`, posts them to `/incidents/manual`, and
prints a CSV-vs-API severity comparison to confirm `severity_rules.py`
computes identically online and offline. `python scripts/load_incidents_csv.py --help`
for all options (account, source selection, sample size).

## The offline ML pipeline (optional — not needed to run the app)

Regenerates the synthetic dataset and the exploratory classifier that
`severity_rules.py`'s weights were derived from:

```bash
python generate_data.py            # -> data/incidents.csv (1,200 synthetic incidents)
python train_severity_model.py     # trains + evaluates the RandomForest (offline only)
python severity_rules.py           # validates the live formula against it
python resource_allocator.py       # CLI demo of the greedy allocator
python visualize.py                # -> outputs/*.png
```

## Frontend tests (no backend needed)

```bash
cd frontend
npm run build                          # production build — catches import/syntax errors
node scripts/demo-mode-smoke.mjs       # pure-logic tests for the demo-mode simulator
npx vite-node scripts/ssr-smoke.mjs    # renders every page server-side, checks nothing throws
```

## Project structure

```
priorityAI v1/
├── .env / .env.example         MONGODB_URI, JWT_SECRET (see setup above)
├── generate_data.py             synthetic incident dataset generator
├── train_severity_model.py      offline RandomForest — exploration only, not used live
├── severity_rules.py            LIVE severity formula (weighted sum) + validation against the model
├── resource_rules.py            resource requirements per incident type + default inventory
├── resource_allocator.py        offline CLI demo of the greedy allocator
├── visualize.py                 diagnostic plots for the offline model
├── data/incidents.csv           generated dataset
├── models/*.joblib              trained offline model artifacts
├── outputs/                     offline eval plots/metrics
├── scripts/
│   ├── check_mongo_connection.py   pre-flight DB check
│   ├── seed_users.py               create demo accounts
│   ├── atlas_sanity.py             cross-check the app and Compass see the same data
│   └── load_incidents_csv.py       replay CSV rows through the live API
├── app/                          FastAPI backend
│   ├── main.py                   all routes
│   ├── auth.py                   JWT + bcrypt
│   ├── config.py                 loads .env — the only module that touches os.environ
│   ├── db.py                     Mongo connection + in-memory fallback
│   ├── models.py                 Pydantic schemas
│   ├── allocation.py             greedy / optimal (PuLP ILP) allocators
│   ├── parsers.py                CSV / paste ingestion
│   └── seed.py                   startup seeding (resources always; users only in fallback mode)
└── frontend/                     React (Vite)
    ├── src/pages/                 the 6 views
    ├── src/components/            IncidentCard, ResourceStrip, Toaster, Layout, ...
    ├── src/context/                AuthContext (JWT), BoardDataContext (incidents/resources/demo mode)
    ├── src/hooks/useDemoMode.js    the demo-mode simulator
    └── scripts/                    ssr-smoke.mjs, demo-mode-smoke.mjs (see "Frontend tests" above)
```

## Known limitations

- MongoDB fallback is in-memory only — data is lost on restart when Atlas is
  unreachable. Fine for a demo, not for anything persistent.
- **Demo mode** on the Incident Board is a client-side placeholder (see the
  TODO in `frontend/src/hooks/useDemoMode.js`) — it never calls the backend,
  and only resolves incidents that are already fully resourced. A real
  resolve action already exists: `POST /incidents/{id}/status`.
- The `optimal` allocator maximizes total priority-weighted coverage; it can
  leave the single highest-priority incident partially covered to fully cover
  several lower-priority ones. That's mathematically correct for its
  objective, but worth knowing before a demo.
- Confidence scoring (`app/allocation.py: default_confidence`) is a simple
  stopgap formula; a dedicated `confidence_rules.py` mirroring
  `severity_rules.py` is planned but not built.
