import { useMemo, useRef, type ChangeEvent, type KeyboardEvent, type PointerEvent } from "react";
import type { RunIndex } from "../lib/derive";
import { indexAtTime } from "../lib/derive";
import type { ManifestEvent } from "../lib/types";
import type { Mode, RunEntry } from "../hooks/useRunSource";
import { SPEEDS, type Speed } from "../hooks/usePlayback";

export interface Marker {
  i: number;
  kind: "proposal" | "accepted" | "rejected" | "block" | "heldout";
  label: string;
}

export function markersOf(events: ManifestEvent[]): Marker[] {
  const out: Marker[] = [];
  for (const e of events) {
    if (e.type === "gate.result") out.push({ i: e.i, kind: e.accepted ? "accepted" : "rejected", label: `${e.accepted ? "Accepted" : "Rejected"} ${e.routine}` });
    else if (e.type === "warden.block") out.push({ i: e.i, kind: "block", label: `Warden blocked ${e.skill}: ${e.attempted}` });
    else if (e.type === "growth.proposal") out.push({ i: e.i, kind: "proposal", label: `Teacher proposed ${e.routine}` });
  }
  return out;
}

interface Props {
  mode: Mode;
  setMode: (m: Mode) => void;
  runs: RunEntry[];
  selected: RunEntry | null;
  onSelect: (r: RunEntry) => void;
  onOpenFile: (f: File) => void;
  hasRealRuns: boolean;
  index: RunIndex;
  count: number;
  n: number;
  playing: boolean;
  following: boolean;
  speed: Speed;
  setSpeed: (s: Speed) => void;
  toggle: () => void;
  seek: (n: number) => void;
  goLive: () => void;
  markers: Marker[];
  clock: string;
}

const labelFor = (r: RunEntry) => (r.source === "runs" ? r.name.replace(/\.jsonl$/, "") : `${r.name.replace(/\.jsonl$/, "")} · ${r.source === "file" ? "local file" : "fixture"}`);

export function Transport(p: Props) {
  const { index, count, n } = p;
  const total = count ? index.ct[count - 1] || 1 : 1;
  const pos = n > 0 && count ? index.ct[n - 1] / total : 0;
  const rail = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const segments = useMemo(() => {
    const starts = index.roundStart.filter((x) => x < count);
    return starts.map((s, r) => {
      const a = index.ct[s] / total;
      const end = r + 1 < starts.length ? index.ct[starts[r + 1]] / total : 1;
      return { r, start: s, left: a, width: Math.max(0, end - a) };
    });
  }, [index, count, total]);

  const fromPointer = (ev: PointerEvent) => {
    const el = rail.current;
    if (!el) return;
    const box = el.getBoundingClientRect();
    const x = Math.min(1, Math.max(0, (ev.clientX - box.left) / box.width));
    p.seek(x >= 0.999 ? count : indexAtTime(index.ct.slice(0, count), x * total));
  };

  const currentRound = segments.reduce((acc, s) => (n > s.start ? s.r : acc), 0);
  const onKey = (ev: KeyboardEvent) => {
    const step = ev.shiftKey ? 50 : 1;
    if (ev.key === "ArrowRight") p.seek(n + step);
    else if (ev.key === "ArrowLeft") p.seek(n - step);
    else if (ev.key === "Home") p.seek(0);
    else if (ev.key === "End") p.seek(count);
    else if (ev.key === "PageDown") p.seek((segments[currentRound + 1]?.start ?? count) + 1);
    else if (ev.key === "PageUp") p.seek((segments[Math.max(0, currentRound - (n > (segments[currentRound]?.start ?? 0) + 1 ? 0 : 1))]?.start ?? 0) + 1);
    else return;
    ev.preventDefault();
    ev.stopPropagation();
  };

  const isLive = p.mode === "live";

  return (
    <div className="transport">
      <div className="seg mode-switch" role="radiogroup" aria-label="Viewer mode">
        {(["replay", "live"] as const).map((m) => (
          <button
            key={m}
            role="radio"
            aria-checked={p.mode === m}
            className={p.mode === m ? "on" : ""}
            disabled={m === "live" && !p.hasRealRuns}
            title={m === "live" && !p.hasRealRuns ? "No runs in .manifest/runs yet" : m === "live" ? "Tail the newest run file (L)" : "Replay a recorded run"}
            onClick={() => p.setMode(m)}
          >
            {m === "live" && <span className={`live-dot ${isLive ? "on" : ""}`} aria-hidden="true" />}
            {m === "replay" ? "Replay" : "Live"}
          </button>
        ))}
      </div>

      <label className="run-pick">
        <span className="sr-only">Run file</span>
        <select
          value={p.selected?.id ?? ""}
          disabled={isLive}
          onChange={(e: ChangeEvent<HTMLSelectElement>) => {
            const r = p.runs.find((x) => x.id === e.target.value);
            if (r) p.onSelect(r);
          }}
        >
          {p.runs.length === 0 && <option value="">no runs</option>}
          {p.runs.map((r) => (
            <option key={r.id} value={r.id}>
              {labelFor(r)}
            </option>
          ))}
        </select>
      </label>
      <button className="btn-quiet" onClick={() => fileInput.current?.click()} title="Open a .jsonl run from disk (or drop it anywhere)">
        Open…
      </button>
      <input
        ref={fileInput}
        type="file"
        accept=".jsonl,application/x-ndjson,text/plain"
        hidden
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) p.onOpenFile(f);
          e.target.value = "";
        }}
      />

      <span className="transport-rule" aria-hidden="true" />

      {isLive ? (
        <button className={`play ${p.following ? "is-live" : ""}`} onClick={p.following ? p.toggle : p.goLive} title={p.following ? "Pause following (space)" : "Jump back to live"}>
          {p.following ? <PauseIcon /> : <LiveIcon />}
          <span>{p.following ? "Following" : "Go live"}</span>
        </button>
      ) : (
        <button className="play" onClick={p.toggle} aria-label={p.playing ? "Pause (space)" : "Play (space)"} title={p.playing ? "Pause (space)" : "Play (space)"}>
          {p.playing ? <PauseIcon /> : <PlayIcon />}
          <span>{p.playing ? "Pause" : n >= count && count > 0 ? "Replay" : "Play"}</span>
        </button>
      )}

      <div className="seg speed" role="radiogroup" aria-label="Replay speed">
        {SPEEDS.map((s, k) => (
          <button key={s} role="radio" aria-checked={p.speed === s} className={p.speed === s ? "on" : ""} onClick={() => p.setSpeed(s)} title={`${s}× (key ${k + 1})`} disabled={isLive && p.following}>
            {s}×
          </button>
        ))}
      </div>

      <div className="scrub">
        <div
          ref={rail}
          className="scrub-rail"
          role="slider"
          tabIndex={0}
          aria-label="Playhead"
          aria-valuemin={0}
          aria-valuemax={count}
          aria-valuenow={n}
          aria-valuetext={`Round ${currentRound}, event ${n} of ${count}`}
          onPointerDown={(ev) => {
            (ev.target as HTMLElement).setPointerCapture?.(ev.pointerId);
            fromPointer(ev);
          }}
          onPointerMove={(ev) => ev.buttons === 1 && fromPointer(ev)}
          onKeyDown={onKey}
        >
          {segments.map((s) => (
            <div
              key={s.r}
              className={`scrub-seg ${s.r === currentRound ? "now" : ""}`}
              style={{ left: `${s.left * 100}%`, width: `${s.width * 100}%` }}
            >
              <button
                className="scrub-seg-label"
                tabIndex={-1}
                onPointerDown={(ev) => ev.stopPropagation()}
                onClick={() => p.seek(s.start + 1)}
                title={`Jump to round ${s.r}`}
              >
                {s.r === 0 ? "R0 baseline" : `R${s.r}`}
              </button>
            </div>
          ))}
          <div className="scrub-fill" style={{ width: `${pos * 100}%` }} />
          {p.markers
            .filter((m) => m.i < count)
            .map((m) => (
              <span
                key={m.i}
                className={`scrub-mark mk-${m.kind} ${m.i < n ? "passed" : ""}`}
                style={{ left: `${(index.ct[m.i] / total) * 100}%` }}
                title={m.label}
              />
            ))}
          <span className="scrub-head" style={{ left: `${pos * 100}%` }} />
        </div>
      </div>

      <output className="clock" aria-live="off">
        <span className="clock-time">{p.clock}</span>
        <span className="clock-n">
          {n.toLocaleString()}
          <span className="of">/{count.toLocaleString()}</span>
        </span>
      </output>
    </div>
  );
}

const PlayIcon = () => (
  <svg viewBox="0 0 16 16" aria-hidden="true">
    <path d="M4 2.5v11l9-5.5z" fill="currentColor" />
  </svg>
);
const PauseIcon = () => (
  <svg viewBox="0 0 16 16" aria-hidden="true">
    <path d="M4 2.5h3v11H4zM9 2.5h3v11H9z" fill="currentColor" />
  </svg>
);
const LiveIcon = () => (
  <svg viewBox="0 0 16 16" aria-hidden="true">
    <path d="M2 2.5v11l6-5.5zM8 2.5v11l6-5.5z" fill="currentColor" />
  </svg>
);
