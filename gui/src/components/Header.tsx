import { useEffect, useRef, useState } from "react";
import type { RunStart } from "../lib/types";
import type { Mode } from "../hooks/useRunSource";

export type Tab = "trace" | "results";

interface Props {
  title: string;
  isFixture: boolean;
  mode: Mode;
  run: RunStart | null;
  round: number;
  maxRound: number;
  netOnline: boolean;
  tab: Tab;
  setTab: (t: Tab) => void;
  theme: "dark" | "light";
  toggleTheme: () => void;
  inspector: boolean;
  toggleInspector: () => void;
}

export function Header(p: Props) {
  const runOffline = p.run?.online === false;
  const offline = !p.netOnline || runOffline;
  const why = !p.netOnline
    ? "no network · everything runs on this laptop"
    : runOffline
      ? "run started without a teacher"
      : p.mode === "live"
        ? "teacher reachable · only synthetic tasks leave"
        : "recorded with the teacher online";

  // brief emphasis when the badge flips, so the moment registers from the back of the room
  const [flip, setFlip] = useState(false);
  const prev = useRef(offline);
  useEffect(() => {
    if (prev.current === offline) return;
    prev.current = offline;
    setFlip(true);
    const t = setTimeout(() => setFlip(false), 700);
    return () => clearTimeout(t);
  }, [offline]);

  return (
    <header className="header">
      <div className="header-row">
        <h1 className="header-title">{p.title}</h1>
        <span className="hchip">
          {p.mode === "live" ? <span className="live-dot on" aria-hidden="true" /> : null}
          {p.mode === "live" ? "Live tail" : p.isFixture ? "Replay · fixture" : "Replay"}
        </span>
        <span className="hchip" aria-label={`Round ${p.round} of ${p.maxRound}`}>
          Round <b className="mono">{p.round}</b>
          <span className="faint">/{p.maxRound}</span>
          <span className="round-pips" aria-hidden="true">
            {Array.from({ length: p.maxRound + 1 }, (_, r) => (
              <i key={r} className={r < p.round ? "done" : r === p.round ? "now" : ""} />
            ))}
          </span>
        </span>

        <span className="header-spacer" />

        <div className={`net ${offline ? "net-off" : "net-on"} ${flip ? "net-flip" : ""}`} role="status" aria-live="polite" title={why}>
          <span className="net-dot" aria-hidden="true" />
          <span className="net-word">{offline ? "OFFLINE" : "ONLINE"}</span>
          <span className="net-why">{why}</span>
        </div>

        <button className="icon-btn" onClick={p.toggleTheme} aria-label={`Switch to ${p.theme === "dark" ? "light (projector)" : "dark"} theme`} title={p.theme === "dark" ? "Light theme (better on projectors)" : "Dark theme"}>
          {p.theme === "dark" ? (
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <circle cx="8" cy="8" r="3" fill="none" stroke="currentColor" strokeWidth="1.4" />
              <path d="M8 1.5v1.6M8 12.9v1.6M1.5 8h1.6M12.9 8h1.6M3.4 3.4l1.1 1.1M11.5 11.5l1.1 1.1M3.4 12.6l1.1-1.1M11.5 4.5l1.1-1.1" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
            </svg>
          ) : (
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path d="M13 9.5A5.5 5.5 0 016.5 3a5.5 5.5 0 106.5 6.5z" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
            </svg>
          )}
        </button>
        <button className={`icon-btn ${p.inspector ? "on" : ""}`} onClick={p.toggleInspector} aria-pressed={p.inspector} aria-label="Toggle growth panel" title="Growth panel (G)">
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <rect x="1.75" y="2.75" width="12.5" height="10.5" rx="2" fill="none" stroke="currentColor" strokeWidth="1.3" />
            <path d="M10 3v10" stroke="currentColor" strokeWidth="1.3" />
          </svg>
        </button>
      </div>

      <nav className="tabs" role="tablist" aria-label="View">
        {(["trace", "results"] as const).map((t) => (
          <button key={t} role="tab" aria-selected={p.tab === t} className={p.tab === t ? "on" : ""} onClick={() => p.setTab(t)}>
            {t === "trace" ? "Trace" : "Results"}
          </button>
        ))}
      </nav>
    </header>
  );
}
