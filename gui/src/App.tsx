import { Component, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Sidebar, runTitle } from "./components/Sidebar";
import { Header, type Tab } from "./components/Header";
import { Composer, markersOf } from "./components/Composer";
import { TaskBoard } from "./components/TaskBoard";
import { Transcript } from "./components/Transcript";
import { Growth } from "./components/Growth";
import { Results } from "./components/Results";
import { NewRun } from "./components/NewRun";
import { useRunSource, type RunEntry } from "./hooks/useRunSource";
import { useLauncher, type LaunchRequest } from "./hooks/useLauncher";
import { SPEEDS, usePlayback } from "./hooks/usePlayback";
import { useNetworkOnline } from "./hooks/useOnline";
import { derive } from "./lib/derive";
import { fmtClock } from "./lib/format";

type Theme = "dark" | "light";
type Focus = { taskId: string; round: number; nonce: number };
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
      <Shell />
    </Boundary>
  );
}

function Shell() {
  const src = useRunSource();
  const launcher = useLauncher();
  const { events, index, version, tailing } = src;
  const count = events.length;
  const pb = usePlayback(index.ct, count, { follow: tailing });
  const n = Math.min(pb.n, count); // usePlayback's own clamp lands a render late when a shorter run loads
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const d = useMemo(() => derive(events, n), [version, n]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const markers = useMemo(() => markersOf(events), [version]);
  const netOnline = useNetworkOnline();

  const [view, setView] = useState<"new" | "run">("run");
  const [tab, setTab] = useState<Tab>("session");
  const [focus, setFocus] = useState<Focus | null>(null);
  const [theme, setTheme] = useState<Theme>(() => (store.get("manifest.theme") as Theme) || "dark");
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    store.set("manifest.theme", theme);
  }, [theme]);

  const { setSelected } = src;
  const open = useCallback(
    (r: RunEntry) => {
      setSelected(r);
      setView("run");
      setTab("session");
      setFocus(null);
    },
    [setSelected],
  );
  const pick = useCallback((taskId: string, round: number) => {
    setFocus({ taskId, round, nonce: Date.now() });
    setTab("session");
  }, []);

  // first visit: open the newest real run (a live one first); with none, the new-run composer
  const booted = useRef(false);
  useEffect(() => {
    if (booted.current || !src.runs.length) return;
    booted.current = true;
    const real = src.runs.filter((r) => r.source === "runs");
    const want = new URLSearchParams(location.search).get("run");
    const first = (want && src.runs.find((r) => r.name.startsWith(want))) || real.find((r) => r.live) || real[0];
    if (first) open(first);
    else if (launcher.available) setView("new");
    else open(src.runs[0]);
  }, [src.runs, launcher.available, open]);

  // a run you just started: open its session as soon as its log file appears
  const launchedAt = useRef<number | null>(null);
  useEffect(() => {
    const t = launchedAt.current;
    if (!t) return;
    const fresh = src.runs.find((r) => r.source === "runs" && (r.mtimeMs ?? 0) >= t - 1500);
    if (fresh) {
      launchedAt.current = null;
      open(fresh);
    }
  }, [src.runs, open]);
  const launch = async (req: LaunchRequest) => {
    const started = await launcher.launch(req);
    if (started) {
      launchedAt.current = started.startedAt;
      src.refreshList();
    }
  };

  // a finished run opens on its whole story (press play to watch it from the start); ?pin=task:round opens one attempt
  const shownFor = useRef<string | null>(null);
  useEffect(() => {
    const id = src.selected?.id ?? null;
    if (src.loadedId !== id || !id || shownFor.current === id) return;
    shownFor.current = id;
    const q = new URLSearchParams(location.search);
    const m = q.get("pin")?.match(/^([\w.-]+):(\d+)$/);
    if (m) setFocus({ taskId: m[1], round: Number(m[2]), nonce: Date.now() });
    if (tailing) return;
    const at = Number(q.get("at"));
    pb.seek(q.has("at") && Number.isFinite(at) ? at : count);
    pb.setPlaying(q.has("play"));
  }, [src.loadedId, src.selected?.id, count, pb, tailing]);

  const seekRound = useCallback(
    (r: number) => {
      const start = index.roundStart[r];
      if (start === undefined) return;
      pb.setFollowing(false);
      pb.seek(start + 1);
    },
    [index, pb],
  );

  // keyboard: space play/pause · ←/→ round · 1–5 speed · N new run · ? help
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.closest("input, select, textarea, [role=slider]") || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "?") {
        document.getElementById("keys")?.togglePopover?.();
        return;
      }
      if (e.key.toLowerCase() === "n") {
        setView("new");
        return;
      }
      if (view !== "run") return;
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
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [view, pb, d.round, n, index, count, seekRound]);

  // drop a .jsonl anywhere
  const [dragging, setDragging] = useState(false);
  const openFile = src.openFile;
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
        setView("run");
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
  const activeRun = src.runs.find((r) => r.source === "runs" && r.live);

  return (
    <div className="app">
      <Sidebar runs={src.runs} selected={src.selected} view={view} onSelect={open} onNew={() => setView("new")} run={d.run} />

      <main className="main">
        <Header
          title={view === "new" ? "New run" : runTitle(src.selected)}
          isFixture={isFixture}
          live={tailing}
          canStop={!!launcher.active && view === "run" && tailing}
          onStop={launcher.stop}
          showTabs={view === "run"}
          run={view === "run" ? d.run : null}
          round={d.round}
          maxRound={index.maxRound}
          netOnline={netOnline}
          tab={tab}
          setTab={setTab}
          theme={theme}
          toggleTheme={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
        />

        {view === "new" ? (
          <NewRun
            available={launcher.available}
            profiles={launcher.profiles}
            busy={launcher.active ? null : launcher.busy}
            active={launcher.active}
            error={launcher.error}
            online={netOnline}
            onLaunch={launch}
            onOpenActive={() => activeRun && open(activeRun)}
          />
        ) : (
          <>
            {(src.skipped > 0 || src.load === "error") && (
              <div className="notices" role="status">
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
              {tab === "session" && (
                <Transcript events={events} index={index} d={d} n={n} version={version} following={pb.following || pb.playing} focus={focus} />
              )}
              {tab === "board" && (
                <div className="tab-page">
                  <TaskBoard index={index} d={d} focus={focus} onPick={pick} />
                </div>
              )}
              {tab === "growth" && (
                <div className="tab-page">
                  <Growth d={d} index={index} onJumpRound={seekRound} onPick={pick} />
                </div>
              )}
              {tab === "results" && <Results d={d} index={index} />}
            </div>
            <Composer
              live={tailing}
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
              goLive={() => pb.setFollowing(true)}
              markers={markers}
              onMarker={(m) => {
                pb.setFollowing(false);
                pb.setPlaying(false);
                pb.seek(m.i + 1);
                if (m.taskId) pick(m.taskId, m.round);
                else setTab("growth");
              }}
              clock={fmtClock(d.last?.ts)}
              d={d}
            />
          </>
        )}
      </main>

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
