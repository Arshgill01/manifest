import { Component, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Sidebar, runTitle } from "./components/Sidebar";
import { Header, type Tab } from "./components/Header";
import { Composer, markersOf } from "./components/Composer";
import { TaskBoard } from "./components/TaskBoard";
import { Trace } from "./components/Trace";
import { Growth } from "./components/Growth";
import { Results } from "./components/Results";
import { useRunSource } from "./hooks/useRunSource";
import { SPEEDS, usePlayback } from "./hooks/usePlayback";
import { useNetworkOnline } from "./hooks/useOnline";
import { derive } from "./lib/derive";
import { fmtClock } from "./lib/format";

type Theme = "dark" | "light";
const store = {
  get: (k: string) => {
    try {
      return localStorage.getItem(k);
    } catch {
      return null;
    }
  },
  set: (k: string, v: string) => {
    try {
      localStorage.setItem(k, v);
    } catch {
      /* private mode: the preference just isn't remembered */
    }
  },
};

export default function App() {
  return (
    <Boundary>
      <Viewer />
    </Boundary>
  );
}

function Viewer() {
  const src = useRunSource();
  const { events, index, version } = src;
  const count = events.length;
  const pb = usePlayback(index.ct, count, { follow: src.mode === "live" });
  const n = Math.min(pb.n, count); // usePlayback's own clamp lands a render late when a shorter run loads
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const d = useMemo(() => derive(events, n), [version, n]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const markers = useMemo(() => markersOf(events), [version]);
  const netOnline = useNetworkOnline();

  const [tab, setTab] = useState<Tab>("trace");
  const [theme, setTheme] = useState<Theme>(() => (store.get("manifest.theme") as Theme) || "dark");
  const [inspector, setInspector] = useState(() => store.get("manifest.inspector") !== "0");
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    store.set("manifest.theme", theme);
  }, [theme]);
  useEffect(() => store.set("manifest.inspector", inspector ? "1" : "0"), [inspector]);

  // ?pin=ledgerly-07:3 opens straight onto one attempt (handy for the presenter)
  const [pin, setPin] = useState<{ taskId: string; round: number } | null>(() => {
    const m = new URLSearchParams(location.search).get("pin")?.match(/^([\w.-]+):(\d+)$/);
    return m ? { taskId: m[1], round: Number(m[2]) } : null;
  });
  const urlPin = useRef(pin);
  const focus = pin ?? d.active;

  // a freshly opened replay shows the whole story; press play to watch it unfold from the start
  const shownFor = useRef<string | null>(null);
  useEffect(() => {
    const id = src.selected?.id ?? null;
    if (src.mode !== "replay" || src.load !== "ready" || !id || shownFor.current === id) return;
    shownFor.current = id;
    setPin(urlPin.current);
    urlPin.current = null;
    // ?at=<event#> opens at a point in the run; ?play starts playback (presenter shortcuts)
    const q = new URLSearchParams(location.search);
    const at = Number(q.get("at"));
    pb.seek(q.has("at") && Number.isFinite(at) ? at : count);
    pb.setPlaying(q.has("play"));
  }, [src.mode, src.load, src.selected?.id, count, pb]);
  useEffect(() => {
    if (src.mode === "live") {
      shownFor.current = null;
      setPin(null);
    }
  }, [src.mode]);

  const seekRound = useCallback(
    (r: number) => {
      const start = index.roundStart[r];
      if (start === undefined) return;
      pb.setFollowing(false);
      pb.seek(start + 1);
      setPin(null);
    },
    [index, pb],
  );
  const { setMode, mode, hasRealRuns, openFile } = src;
  const toggleLive = useCallback(() => setMode(mode === "live" ? "replay" : "live"), [setMode, mode]);

  // keyboard: space play/pause · ←/→ round · 1–5 speed · L live · G growth panel · Esc unpin
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.closest("input, select, textarea, [role=slider]") || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === " " && !t.closest("button")) {
        e.preventDefault();
        pb.toggle();
      } else if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
        e.preventDefault();
        const next = e.key === "ArrowRight" ? d.round + 1 : n > (index.roundStart[d.round] ?? 0) + 1 ? d.round : d.round - 1;
        if (next > index.maxRound) pb.seek(count);
        else seekRound(Math.max(0, next));
      } else if (/^[1-5]$/.test(e.key)) {
        pb.setSpeed(SPEEDS[Number(e.key) - 1]);
      } else if (e.key.toLowerCase() === "l" && hasRealRuns) {
        toggleLive();
      } else if (e.key.toLowerCase() === "g") {
        setInspector((x) => !x);
      } else if (e.key === "Escape") {
        setPin(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pb, d.round, n, index, count, seekRound, hasRealRuns, toggleLive]);

  // drop a .jsonl anywhere
  const [dragging, setDragging] = useState(false);
  useEffect(() => {
    const over = (e: DragEvent) => {
      if (e.dataTransfer?.types.includes("Files")) {
        e.preventDefault();
        setDragging(true);
      }
    };
    const leave = (e: DragEvent) => {
      if (!e.relatedTarget) setDragging(false);
    };
    const drop = (e: DragEvent) => {
      e.preventDefault();
      setDragging(false);
      const f = e.dataTransfer?.files[0];
      if (f) {
        shownFor.current = null;
        openFile(f);
      }
    };
    window.addEventListener("dragover", over);
    window.addEventListener("dragleave", leave);
    window.addEventListener("drop", drop);
    return () => {
      window.removeEventListener("dragover", over);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("drop", drop);
    };
  }, [openFile]);

  const isFixture = src.selected?.source === "fixture" || src.selected?.source === "bundled";

  return (
    <div className={`app ${inspector ? "with-inspector" : ""}`} data-mode={mode}>
      <Sidebar
        runs={src.runs}
        selected={src.selected}
        onSelect={(r) => {
          shownFor.current = null;
          src.setSelected(r);
        }}
        mode={mode}
        onGoLive={toggleLive}
        hasRealRuns={hasRealRuns}
        run={d.run}
        board={<TaskBoard index={index} d={d} focus={focus} onPick={(taskId, round) => setPin({ taskId, round })} />}
      />

      <main className="main">
        <Header
          title={runTitle(src.selected)}
          isFixture={isFixture}
          mode={mode}
          run={d.run}
          round={d.round}
          maxRound={index.maxRound}
          netOnline={netOnline}
          tab={tab}
          setTab={setTab}
          theme={theme}
          toggleTheme={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
          inspector={inspector}
          toggleInspector={() => setInspector((x) => !x)}
        />
        {(src.skipped > 0 || src.load === "error" || (mode === "live" && count === 0)) && (
          <div className="notices" role="status">
            {mode === "live" && count === 0 && src.load !== "error" && (
              <p className="notice">
                <span className="wait-dot" aria-hidden="true" /> Waiting for the first event in <span className="mono">{src.selected?.name ?? "the newest run"}</span>…
              </p>
            )}
            {src.skipped > 0 && (
              <p className="notice notice-warn">
                Skipped {src.skipped} malformed line{src.skipped === 1 ? "" : "s"}. Everything else is shown.
              </p>
            )}
            {src.load === "error" && (
              <p className="notice notice-warn">
                Couldn't read <span className="mono">{src.selected?.name}</span>: {src.error}
              </p>
            )}
          </div>
        )}
        <div className="stage">
          {tab === "trace" ? (
            <Trace events={events} index={index} n={n} focus={focus} pinned={!!pin} onUnpin={() => setPin(null)} version={version} />
          ) : (
            <Results d={d} index={index} />
          )}
        </div>
        <Composer
          mode={mode}
          setMode={setMode}
          hasRealRuns={hasRealRuns}
          onOpenFile={(f) => {
            shownFor.current = null;
            openFile(f);
          }}
          index={index}
          count={count}
          n={n}
          playing={pb.playing}
          following={pb.following}
          speed={pb.speed}
          setSpeed={pb.setSpeed}
          toggle={pb.toggle}
          seek={(x) => {
            pb.setFollowing(false);
            pb.seek(x);
          }}
          goLive={() => {
            setPin(null);
            pb.setFollowing(true);
          }}
          markers={markers}
          clock={fmtClock(d.last?.ts)}
          d={d}
        />
      </main>

      {inspector && (
        <aside className="inspector" aria-label="Growth timeline">
          <Growth d={d} index={index} onJumpRound={seekRound} />
        </aside>
      )}

      {dragging && (
        <div className="dropzone" aria-hidden="true">
          <p>Drop a run (.jsonl) to replay it</p>
        </div>
      )}
    </div>
  );
}

class Boundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="crash" role="alert">
        <h1>The viewer hit an event it couldn't draw.</h1>
        <p className="mono">{this.state.error.message}</p>
        <button className="sb-primary" onClick={() => location.reload()}>
          Reload
        </button>
      </div>
    );
  }
}
