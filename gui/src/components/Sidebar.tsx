import { prettyModel } from "../lib/derive";
import type { RunStart } from "../lib/types";
import type { RunEntry } from "../hooks/useRunSource";

interface Props {
  runs: RunEntry[];
  selected: RunEntry | null;
  view: "new" | "run";
  onSelect: (r: RunEntry) => void;
  onNew: () => void;
  run: RunStart | null;
}

export function runTitle(r: RunEntry | null) {
  if (!r) return "No run";
  const base = r.name.replace(/\.jsonl$/, "");
  const m = base.match(/^(\d{4})(\d\d)(\d\d)-(\d\d)(\d\d)(\d\d)-(.+)$/);
  if (!m) return base;
  const label = m[7].replace(/^gui-/, "").replace(/-/g, " ");
  return `${label[0].toUpperCase()}${label.slice(1)} · ${m[4]}:${m[5]}`;
}

function ago(ms?: number) {
  if (!ms) return "";
  const s = Math.max(0, (Date.now() - ms) / 1000);
  if (s < 60) return "now";
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

export function Sidebar({ runs, selected, view, onSelect, onNew, run }: Props) {
  const real = runs.filter((r) => r.source === "runs");
  const other = runs.filter((r) => r.source !== "runs");

  const item = (r: RunEntry) => {
    const on = view === "run" && selected?.id === r.id;
    return (
      <li key={r.id}>
        <button className={`run-item ${on ? "on" : ""}`} onClick={() => onSelect(r)} aria-current={on ? "true" : undefined} title={r.name}>
          <span className="run-name">{runTitle(r)}</span>
          {r.live ? <span className="live-dot on" aria-label="live" /> : <span className="run-meta">{r.source === "runs" ? ago(r.mtimeMs) : r.source === "file" ? "file" : "demo"}</span>}
        </button>
      </li>
    );
  };

  return (
    <aside className="sidebar" aria-label="Runs">
      <div className="sb-brand">
        <svg className="brand-mark" viewBox="0 0 32 32" aria-hidden="true">
          <rect width="32" height="32" rx="7" />
          <path d="M8 23V9l8 8 8-8v14" />
        </svg>
        <span className="brand-name">manifest</span>
        <span className="brand-tag">harness</span>
      </div>

      <button className={`sb-primary ${view === "new" ? "on" : ""}`} onClick={onNew}>
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <circle cx="8" cy="8" r="6.2" fill="none" stroke="currentColor" strokeWidth="1.3" />
          <path d="M8 5.2v5.6M5.2 8h5.6" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
        </svg>
        New run
      </button>

      <nav className="sb-section" aria-label="Runs">
        <h2 className="sb-h">Runs</h2>
        <ul className="run-list">
          {real.map(item)}
          {real.length === 0 && <li className="sb-empty">No runs yet. Start one above.</li>}
          {other.length > 0 && <li className="sb-sub">Demo &amp; files</li>}
          {other.map(item)}
        </ul>
      </nav>

      <dl className="sb-foot">
        <div>
          <dt>
            <span className="key key-model" aria-hidden="true" /> Student
          </dt>
          <dd>
            <span className="mono">{run?.student ?? "qwen3.5:4b"}</span> <span className="faint">local</span>
          </dd>
        </div>
        <div>
          <dt>
            <span className="key key-teacher" aria-hidden="true" /> Teacher
          </dt>
          <dd>{prettyModel(run?.teacher ?? "deepseek")}</dd>
        </div>
      </dl>
    </aside>
  );
}
