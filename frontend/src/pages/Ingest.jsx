import { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import SeverityPreview from "../components/SeverityPreview.jsx";

const SOURCES = [
  { value: "social_media", label: "Social media" },
  { value: "ground_team", label: "Ground team" },
  { value: "citizen_reports", label: "Citizen reports" },
];

const INCIDENT_TYPES = [
  "fire",
  "flood",
  "building_collapse",
  "medical_emergency",
  "road_blockage",
  "power_outage",
  "chemical_leak",
  "industrial_accident",
];

const FLAGS = [
  "person_trapped",
  "injury_reported",
  "fire_present",
  "hospital_affected",
  "elderly_or_children",
  "hazardous_material",
  "building_collapse_flag",
  "critical_infrastructure",
];

const TABS = [
  { id: "paste", label: "Paste Text" },
  { id: "csv", label: "Upload CSV" },
  { id: "single", label: "Single Entry" },
];

export default function Ingest() {
  const [tab, setTab] = useState("paste");
  return (
    <div>
      <h2>Ingest / Manual Entry</h2>
      <div className="subtabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`subtab ${tab === t.id ? "active" : ""}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="card">
        {tab === "paste" && <PasteTab />}
        {tab === "csv" && <CsvTab />}
        {tab === "single" && <SingleEntryTab />}
      </div>
    </div>
  );
}

function Result({ result, error }) {
  if (error) return <div className="alert error">{error}</div>;
  if (!result) return null;
  return <pre className="result-json">{JSON.stringify(result, null, 2)}</pre>;
}

function PasteTab() {
  const [source, setSource] = useState("citizen_reports");
  const [location, setLocation] = useState("");
  const [text, setText] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const preview = text
    .trim()
    .split(/\n\s*\n/)
    .map((s) => s.trim())
    .filter(Boolean);

  async function submit(e) {
    e.preventDefault();
    setError("");
    setResult(null);
    setBusy(true);
    try {
      const body = { source_type: source, text };
      if (location.trim()) body.location = location.trim();
      setResult(await api.post("/reports/paste", body));
      setText("");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="stack">
      <p className="muted">
        One report per block; blank lines separate reports. {preview.length} report
        {preview.length === 1 ? "" : "s"} detected.
      </p>
      <div className="row">
        <label>
          Source
          <select value={source} onChange={(e) => setSource(e.target.value)}>
            {SOURCES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        <label className="grow">
          Location (optional, applied to all)
          <input value={location} onChange={(e) => setLocation(e.target.value)} />
        </label>
      </div>
      <label>
        Text
        <textarea
          rows={10}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={"Smoke near the market\n\nRoad flooded at 5th Ave, cars stuck\n\nPeople stranded on a rooftop"}
          required
        />
      </label>
      <button className="btn primary" disabled={busy || preview.length === 0}>
        {busy ? "Submitting…" : `Create ${preview.length} report${preview.length === 1 ? "" : "s"}`}
      </button>
      <Result result={result} error={error} />
    </form>
  );
}

function CsvTab() {
  const [source, setSource] = useState("social_media");
  const [file, setFile] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [files, setFiles] = useState(null);
  const [filesError, setFilesError] = useState("");

  const loadFiles = useCallback(() => {
    api
      .get("/files?limit=50", { auth: false })
      .then(setFiles)
      .catch((e) => setFilesError(e.message));
  }, []);

  useEffect(() => {
    loadFiles();
  }, [loadFiles]);

  async function submit(e) {
    e.preventDefault();
    setError("");
    setResult(null);
    if (!file) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      setResult(await api.upload(`/ingest/${source}`, fd));
      setFile(null);
      loadFiles();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <form onSubmit={submit} className="stack">
        <p className="muted">
          CSV needs a <code>text</code> column. <code>location</code> and{" "}
          <code>occurred_at</code> are optional. Columns that don't belong to the chosen
          source (e.g. a <code>phone</code> column on citizen reports) are dropped and
          listed back.
        </p>
        <div className="row">
          <label>
            Source
            <select value={source} onChange={(e) => setSource(e.target.value)}>
              {SOURCES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
          <label className="grow">
            File
            <input
              type="file"
              accept=".csv,text/csv"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
          </label>
        </div>
        <button className="btn primary" disabled={busy || !file}>
          {busy ? "Uploading…" : "Upload"}
        </button>
        <Result result={result} error={error} />
      </form>

      <UploadedFiles files={files} error={filesError} onRefresh={loadFiles} />
    </div>
  );
}

// A running record of every CSV that has actually been ingested: what it was
// called, which source it went in as, who uploaded it, and what came of it
// (rows turned into reports, columns dropped for not belonging to that source).
function UploadedFiles({ files, error, onRefresh }) {
  return (
    <div className="card">
      <div className="sim-head">
        <h3>Uploaded files</h3>
        <button className="btn ghost" onClick={onRefresh}>
          Refresh
        </button>
      </div>
      {error && <div className="alert error">{error}</div>}
      {!files ? (
        <p className="muted">loading…</p>
      ) : files.length === 0 ? (
        <p className="muted">No CSVs uploaded yet.</p>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>File</th>
              <th>Source</th>
              <th>Size</th>
              <th>Reports</th>
              <th>Dropped columns</th>
              <th>Uploaded by</th>
              <th>When</th>
            </tr>
          </thead>
          <tbody>
            {files.map((f) => (
              <tr key={f.id}>
                <td>{f.filename}</td>
                <td>{f.source_type.replace(/_/g, " ")}</td>
                <td className="muted">{formatBytes(f.size_bytes)}</td>
                <td>{f.reports_created}</td>
                <td className="muted">
                  {f.dropped_columns?.length ? f.dropped_columns.join(", ") : "—"}
                </td>
                <td>{f.uploaded_by}</td>
                <td className="muted nowrap">{fmtDate(f.uploaded_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function formatBytes(n) {
  if (n == null) return "—";
  if (n < 1024) return `${n} B`;
  return `${(n / 1024).toFixed(1)} KB`;
}

function fmtDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function SingleEntryTab() {
  const [incidentType, setIncidentType] = useState("fire");
  const [location, setLocation] = useState("");
  const [notes, setNotes] = useState("");
  const [flags, setFlags] = useState({});
  const [conf, setConf] = useState({
    num_sources: "",
    ground_confirmed: false,
    agreement_ratio: "",
    recency_minutes: "",
  });
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  function toggle(flag) {
    setFlags((f) => ({ ...f, [flag]: !f[flag] }));
  }

  async function submit(e) {
    e.preventDefault();
    setError("");
    setResult(null);
    setBusy(true);
    try {
      const body = {
        incident_type: incidentType,
        flags: Object.fromEntries(Object.entries(flags).filter(([, v]) => v)),
      };
      if (location.trim()) body.location = location.trim();
      if (notes.trim()) body.notes = notes.trim();
      const c = {};
      if (conf.num_sources !== "") c.num_sources = Number(conf.num_sources);
      if (conf.ground_confirmed) c.ground_confirmed = true;
      if (conf.agreement_ratio !== "") c.agreement_ratio = Number(conf.agreement_ratio);
      if (conf.recency_minutes !== "") c.recency_minutes = Number(conf.recency_minutes);
      if (Object.keys(c).length) body.confidence = c;

      setResult(await api.post("/incidents/manual", body));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="stack">
      <p className="muted">
        Structured incident entry — severity is computed immediately from the flags
        (report volume never counts toward it).
      </p>
      <div className="row">
        <label>
          Incident type
          <select value={incidentType} onChange={(e) => setIncidentType(e.target.value)}>
            {INCIDENT_TYPES.map((t) => (
              <option key={t} value={t}>
                {t.replace(/_/g, " ")}
              </option>
            ))}
          </select>
        </label>
        <label className="grow">
          Location
          <input value={location} onChange={(e) => setLocation(e.target.value)} />
        </label>
      </div>

      <fieldset>
        <legend>Structural flags</legend>
        <div className="flag-grid">
          {FLAGS.map((f) => (
            <label key={f} className="checkbox">
              <input type="checkbox" checked={!!flags[f]} onChange={() => toggle(f)} />
              {f.replace(/_/g, " ")}
            </label>
          ))}
        </div>
      </fieldset>

      <SeverityPreview flags={flags} />

      <fieldset>
        <legend>Confidence inputs (optional)</legend>
        <div className="row wrap">
          <label>
            Independent sources
            <input
              type="number"
              min="0"
              value={conf.num_sources}
              onChange={(e) => setConf({ ...conf, num_sources: e.target.value })}
            />
          </label>
          <label>
            Agreement ratio (0–1)
            <input
              type="number"
              step="0.05"
              min="0"
              max="1"
              value={conf.agreement_ratio}
              onChange={(e) => setConf({ ...conf, agreement_ratio: e.target.value })}
            />
          </label>
          <label>
            Latest report age (min)
            <input
              type="number"
              min="0"
              value={conf.recency_minutes}
              onChange={(e) => setConf({ ...conf, recency_minutes: e.target.value })}
            />
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={conf.ground_confirmed}
              onChange={(e) => setConf({ ...conf, ground_confirmed: e.target.checked })}
            />
            Ground-confirmed
          </label>
        </div>
      </fieldset>

      <label>
        Notes
        <textarea rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </label>

      <button className="btn primary" disabled={busy}>
        {busy ? "Creating…" : "Create incident"}
      </button>
      <Result result={result} error={error} />
    </form>
  );
}
