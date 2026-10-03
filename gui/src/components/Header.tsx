import { useEffect, useRef, useState } from "react";
import type { RunStart } from "../lib/types";
export type Tab = "session" | "board" | "growth" | "results";
const TABS: { id: Tab; label: string }[] = [
  { id: "session", label: "Session" },
  { id: "board", label: "Board" },
  { id: "growth", label: "Growth" },
  { id: "results", label: "Results" },
];

interface Props {
  title: string;
  isFixture: boolean;
  live: boolean;
  canStop: boolean;
  onStop: () => void;
  showTabs: boolean;
  run: RunStart | null;
  round: number;
  maxRound: number;
  netOnline: boolean;
  tab: Tab;
  setTab: (t: Tab) => void;
  theme: "dark" | "light";
  toggleTheme: () => void;
}

export function Header(p: Props) {
  const runOffline = p.run?.online === false;
  const offline = !p.netOnline || runOffline;
  const why = !p.netOnline
    ? "no network · everything runs on this laptop"
    : runOffline
      ? "run started without a teacher"
      : p.live
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
        {p.showTabs && (
          <span className="hchip">
            {p.live ? <span className="live-dot on" aria-hidden="true" /> : null}
            {p.live ? "Live" : p.isFixture ? "Demo replay" : "Replay"}
          </span>
        )}
        {p.showTabs && p.run?.mode === "growth" && (
          <span className="hchip" aria-label={`Round ${p.round} of ${p.maxRound}`}>
            Round <b className="mono">{p.round}</b>
            <span className="faint">/{p.maxRound}</span>
          </span>
        )}
        {p.canStop && (
          <button className="btn-quiet btn-stop" onClick={p.onStop} title="Stop the run (the harness writes run.end on the way out)">
            Stop run
          </button>
        )}

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
        <button className="icon-btn" popoverTarget="keys" aria-label="Keyboard shortcuts" title="Keyboard shortcuts (?)">
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <rect x="1.5" y="4" width="13" height="8.5" rx="1.8" fill="none" stroke="currentColor" strokeWidth="1.3" />
            <path d="M4 7h1M7.5 7h1M11 7h1M5 10h6" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
          </svg>
        </button>
        <div id="keys" popover="auto" className="keys-pop">
          <p className="keys-h">Keyboard</p>
          <dl>
            {[
              ["Space", "play / pause"],
              ["← →", "previous / next round"],
              ["1 – 5", "speed 1× · 2× · 5× · 10× · 20×"],
              ["L", "live tail ↔ replay"],
              ["G", "growth panel"],
              ["Esc", "stop pinning a task, follow the run"],
            ].map(([k, v]) => (
              <div key={k}>
                <dt>
                  <kbd>{k}</kbd>
                </dt>
                <dd>{v}</dd>
              </div>
            ))}
          </dl>
          <p className="keys-foot">
            Deep links: <span className="mono">?pin=ledgerly-07:3</span> · <span className="mono">?at=1200</span> · <span className="mono">?play</span>
          </p>
        </div>

      </div>

      {p.showTabs && (
        <nav className="tabs" role="tablist" aria-label="View">
          {TABS.map((t) => (
            <button key={t.id} role="tab" aria-selected={p.tab === t.id} className={p.tab === t.id ? "on" : ""} onClick={() => p.setTab(t.id)}>
              {t.label}
            </button>
          ))}
        </nav>
      )}
    </header>
  );
}
