import { useMemo, useRef, type KeyboardEvent, type PointerEvent } from "react";
import type { Derived, RunIndex } from "../lib/derive";
import { indexAtTime } from "../lib/derive";
import type { ManifestEvent } from "../lib/types";
import type { Mode } from "../hooks/useRunSource";
import { SPEEDS, type Speed } from "../hooks/usePlayback";
import { fmtPct, fmtUsd } from "../lib/format";

export interface Marker {
  i: number;
  kind: "proposal" | "accepted" | "rejected" | "block";
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
  hasRealRuns: boolean;
  onOpenFile: (f: File) => void;
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
  d: Derived;
}

/** The replay transport, shaped like a chat composer: scrubber on top, controls below, send = play. */
export function Composer(p: Props) {
  const { index, count, n } = p;
  const total = count ? index.ct[count - 1] || 1 : 1;
  const pos = n > 0 && count ? index.ct[n - 1] / total : 0;
  const rail = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const isLive = p.mode === "live";

  const segments = useMemo(() => {
    const starts = index.roundStart.filter((x) => x < count);
    return starts.map((s, r) => {
      const a = index.ct[s] / total;
      const end = r + 1 < starts.length ? index.ct[starts[r + 1]] / total : 1;
      return { r, start: s, left: a, width: Math.max(0, end - a) };
    });
  }, [index, count, total]);
  const currentRound = segments.reduce((acc, s) => (n > s.start ? s.r : acc), 0);

  const fromPointer = (ev: PointerEvent) => {
    const el = rail.current;
    if (!el || !count) return;
    const box = el.getBoundingClientRect();
    const x = Math.min(1, Math.max(0, (ev.clientX - box.left) / box.width));
    p.seek(x >= 0.999 ? count : Math.min(count, indexAtTime(index.ct, x * total)));
  };
  const onKey = (ev: KeyboardEvent) => {
    const step = ev.shiftKey ? 50 : 1;
    if (ev.key === "ArrowRight") p.seek(n + step);
    else if (ev.key === "ArrowLeft") p.seek(n - step);
    else if (ev.key === "Home") p.seek(0);
    else if (ev.key === "End") p.seek(count);
    else if (ev.key === "PageDown") p.seek((segments[currentRound + 1]?.start ?? count) + 1);
    else if (ev.key === "PageUp") {
      const segStart = segments[currentRound]?.start ?? 0;
      p.seek((n > segStart + 1 ? segStart : segments[Math.max(0, currentRound - 1)]?.start ?? 0) + 1);
    } else return;
    ev.preventDefault();
    ev.stopPropagation();
  };

  const playLabel = isLive ? (p.following ? "Pause following" : "Jump to live") : p.playing ? "Pause" : n >= count && count > 0 ? "Replay from the start" : "Play";

  // status line: the numbers a judge should leave with
  const held = p.d.rounds.map((r) => r.heldout).filter(Boolean);
  const h0 = held[0], h1 = held[held.length - 1];

  return (
    <div className="composer-wrap">
      <div className="composer">
        <div
          ref={rail}
          className="scrub"
          role="slider"
          tabIndex={0}
          aria-label="Playhead"
          aria-valuemin={0}
          aria-valuemax={count}
          aria-valuenow={n}
          aria-valuetext={`Round ${currentRound}, event ${n} of ${count}`}
          onPointerDown={(ev) => {
            (ev.currentTarget as HTMLElement).setPointerCapture?.(ev.pointerId);
            fromPointer(ev);
          }}
          onPointerMove={(ev) => ev.buttons === 1 && fromPointer(ev)}
          onKeyDown={onKey}
        >
          <div className="scrub-track">
            {segments.map((s) => (
              <div key={s.r} className={`scrub-seg ${s.r === currentRound ? "now" : ""} ${s.start < n ? "reached" : ""}`} style={{ left: `${s.left * 100}%`, width: `${s.width * 100}%` }} />
            ))}
            <div className="scrub-fill" style={{ width: `${pos * 100}%` }} />
            {p.markers
              .filter((m) => m.i < count)
              .map((m) => (
                <span key={m.i} className={`scrub-mark mk-${m.kind} ${m.i < n ? "passed" : ""}`} style={{ left: `${(index.ct[m.i] / total) * 100}%` }} title={m.label} />
              ))}
            <span className="scrub-head" style={{ left: `${pos * 100}%` }} />
          </div>
          <div className="scrub-labels">
            {segments.map((s) => (
              <button
                key={s.r}
                className={`scrub-label ${s.r === currentRound ? "now" : ""}`}
                style={{ left: `${s.left * 100}%`, maxWidth: `${s.width * 100}%` }}
                tabIndex={-1}
                onPointerDown={(ev) => ev.stopPropagation()}
                onClick={() => p.seek(s.start + 1)}
                title={`Jump to round ${s.r}`}
              >
                {s.r === 0 ? "R0 baseline" : `R${s.r}`}
              </button>
            ))}
          </div>
        </div>

        <div className="composer-row">
          <button className="icon-btn" onClick={() => fileInput.current?.click()} title="Open a .jsonl run from disk (or drop one anywhere)" aria-label="Open a run file">
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path d="M8 3v10M3 8h10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" fill="none" />
            </svg>
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
          <label className="chip-select" title={!p.hasRealRuns ? "Live needs a run in .manifest/runs" : "Replay a recorded run, or tail the newest one (L)"}>
            {isLive ? <span className="live-dot on" aria-hidden="true" /> : <ReplayIcon />}
            <span className="sr-only">Mode</span>
            <select value={p.mode} onChange={(e) => p.setMode(e.target.value as Mode)}>
              <option value="replay">Replay</option>
              <option value="live" disabled={!p.hasRealRuns}>
                Live tail
              </option>
            </select>
            <Chevron />
          </label>
          <span className="composer-clock mono">
            {p.clock}
            <span className="faint">
              {" "}
              · {n.toLocaleString()}/{count.toLocaleString()}
            </span>
          </span>

          <span className="composer-spacer" />

          <label className="chip-select" title="Replay speed (keys 1–5)">
            <span className="sr-only">Speed</span>
            <select value={p.speed} onChange={(e) => p.setSpeed(Number(e.target.value) as Speed)} disabled={isLive && p.following}>
              {SPEEDS.map((s) => (
                <option key={s} value={s}>
                  {s}× speed
                </option>
              ))}
            </select>
            <Chevron />
          </label>
          <button
            className={`send ${isLive && p.following ? "is-live" : ""} ${p.playing ? "is-playing" : ""}`}
            onClick={isLive && !p.following ? p.goLive : p.toggle}
            aria-label={`${playLabel} (space)`}
            title={`${playLabel} (space)`}
            disabled={!count && !isLive}
          >
            {p.playing || (isLive && p.following) ? <PauseIcon /> : <PlayIcon />}
          </button>
        </div>
      </div>

      <p className="statusline" aria-label="Run summary">
        <span>
          <span className="key key-code" aria-hidden="true" /> held-out{" "}
          <b className="mono">{h0 && h1 && h0 !== h1 ? `${fmtPct(h0.passed / h0.total)} → ${fmtPct(h1.passed / h1.total)}` : h1 ? fmtPct(h1.passed / h1.total) : "–"}</b>
        </span>
        <span>
          <span className="key key-model" aria-hidden="true" /> model calls / task{" "}
          <b className="mono">{h0 && h1 && h0 !== h1 ? `${h0.avgModelCalls.toFixed(1)} → ${h1.avgModelCalls.toFixed(1)}` : h1 ? h1.avgModelCalls.toFixed(1) : "–"}</b>
        </span>
        <span>
          <span className="key key-teacher" aria-hidden="true" /> teacher <b className="mono">{fmtUsd(p.d.teacherCost)}</b>
        </span>
        <span>
          <b className="mono">{p.d.accepted.length}</b> kept · <b className="mono">{p.d.rejected.length}</b> rejected
        </span>
      </p>
    </div>
  );
}

const PlayIcon = () => (
  <svg viewBox="0 0 16 16" aria-hidden="true">
    <path d="M5 3v10l8-5z" fill="currentColor" />
  </svg>
);
const PauseIcon = () => (
  <svg viewBox="0 0 16 16" aria-hidden="true">
    <path d="M4.5 3h2.5v10H4.5zM9 3h2.5v10H9z" fill="currentColor" />
  </svg>
);
const ReplayIcon = () => (
  <svg className="chip-ico" viewBox="0 0 16 16" aria-hidden="true">
    <path d="M3 8a5 5 0 1 0 1.5-3.5M3 2.5V5h2.5" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
export const Chevron = () => (
  <svg className="chev" viewBox="0 0 10 6" aria-hidden="true">
    <path d="M1 1l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
  </svg>
);
