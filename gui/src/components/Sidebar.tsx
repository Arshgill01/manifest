import type { ReactNode } from "react";
import { prettyModel } from "../lib/derive";
import type { RunStart } from "../lib/types";
import type { Mode, RunEntry } from "../hooks/useRunSource";

interface Props {
  runs: RunEntry[];
  selected: RunEntry | null;
  onSelect: (r: RunEntry) => void;
  mode: Mode;
  onGoLive: () => void;
  hasRealRuns: boolean;
  run: RunStart | null;
  board: ReactNode;
}

export function runTitle(r: RunEntry | null) {
  if (!r) return "No run";
  const base = r.name.replace(/\.jsonl$/, "");
  const m = base.match(/^(\d{4})(\d\d)(\d\d)-(\d\d)(\d\d)(\d\d)-(.+)$/);
  return m ? `${m[7]} · ${m[4]}:${m[5]}` : base;
}

function ago(ms?: number) {
  if (!ms) return "";
  const s = Math.max(0, (Date.now() - ms) / 1000);
  if (s < 60) return "now";
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

export function Sidebar({ runs, selected, onSelect, mode, onGoLive, hasRealRuns, run, board }: Props) {
  const real = runs.filter((r) => r.source === "runs");
  const other = runs.filter((r) => r.source !== "runs");
  const live = mode === "live";

  const item = (r: RunEntry) => (
    <li key={r.id}>
      <button className={`run-item ${selected?.id === r.id ? "on" : ""}`} onClick={() => onSelect(r)} disabled={live} aria-current={selected?.id === r.id ? "true" : undefined}>
        {live && selected?.id === r.id && <span className="live-dot on" aria-hidden="true" />}
        <span className="run-name">{runTitle(r)}</span>
        <span className="run-meta">{r.source === "runs" ? ago(r.mtimeMs) : r.source === "file" ? "file" : "fixture"}</span>
      </button>
    </li>
  );

  return (
    <aside className="sidebar" aria-label="Runs and tasks">
      <div className="sb-brand">
        <svg className="brand-mark" viewBox="0 0 32 32" aria-hidden="true">
          <rect width="32" height="32" rx="7" />
          <path d="M8 23V9l8 8 8-8v14" />
        </svg>
        <span className="brand-name">manifest</span>
        <span className="brand-tag">harness</span>
      </div>

      <button className={`sb-primary ${live ? "is-live" : ""}`} onClick={onGoLive} disabled={!hasRealRuns && !live} title={hasRealRuns ? "Tail the newest run in .manifest/runs (L)" : "No runs in .manifest/runs yet"}>
        <span className={`live-dot ${live ? "on" : ""}`} aria-hidden="true" />
        {live ? "Following live run" : "Go live"}
      </button>

      <nav className="sb-section" aria-label="Runs">
        <h2 className="sb-h">Runs</h2>
        <ul className="run-list">
          {real.map(item)}
          {real.length === 0 && <li className="sb-empty">Nothing in .manifest/runs yet</li>}
          {other.length > 0 && <li className="sb-sub">Fixtures &amp; files</li>}
          {other.map(item)}
        </ul>
      </nav>

      <div className="sb-board">{board}</div>

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
          <dd>
            {prettyModel(run?.teacher ?? "deepseek")}
          </dd>
        </div>
      </dl>
    </aside>
  );
}
