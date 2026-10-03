import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { TopBar } from "./components/TopBar";
import { Transport, markersOf } from "./components/Transport";
import { TaskBoard } from "./components/TaskBoard";
import { Trace } from "./components/Trace";
import { Growth } from "./components/Growth";
import { Results } from "./components/Results";
import { useRunSource } from "./hooks/useRunSource";
import { SPEEDS, usePlayback } from "./hooks/usePlayback";
import { useNetworkOnline } from "./hooks/useOnline";
import { derive } from "./lib/derive";
import { fmtClock } from "./lib/format";

export default function App() {
  const src = useRunSource();
  const { events, index, version } = src;
  const count = events.length;
  const pb = usePlayback(index.ct, count, { follow: src.mode === "live" });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const d = useMemo(() => derive(events, pb.n), [version, pb.n]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const markers = useMemo(() => markersOf(events), [version]);
  const netOnline = useNetworkOnline();
  const [pin, setPin] = useState<{ taskId: string; round: number } | null>(null);
  const focus = pin ?? d.active;

  // a freshly opened replay shows the whole story; press play to watch it unfold from the start
  const shownFor = useRef<string | null>(null);
  useEffect(() => {
    const id = src.selected?.id ?? null;
    if (src.mode !== "replay" || src.load !== "ready" || !id || shownFor.current === id) return;
    shownFor.current = id;
    setPin(null);
    pb.setPlaying(false);
    pb.seek(count);
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

  // keyboard: space play/pause · ←/→ round · 1–5 speed · L live · Esc unpin
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.closest("input, select, textarea, [role=slider]") || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === " " && !t.closest("button")) {
        e.preventDefault();
        pb.toggle();
      } else if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
        e.preventDefault();
        const next = e.key === "ArrowRight" ? d.round + 1 : pb.n > (index.roundStart[d.round] ?? 0) + 1 ? d.round : d.round - 1;
        if (next > index.maxRound) pb.seek(count);
        else seekRound(Math.max(0, next));
      } else if (/^[1-5]$/.test(e.key)) {
        pb.setSpeed(SPEEDS[Number(e.key) - 1]);
      } else if (e.key.toLowerCase() === "l" && src.hasRealRuns) {
        src.setMode(src.mode === "live" ? "replay" : "live");
      } else if (e.key === "Escape") {
        setPin(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pb, d.round, index, count, seekRound, src]);

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
      if (f) src.openFile(f);
    };
    window.addEventListener("dragover", over);
    window.addEventListener("dragleave", leave);
    window.addEventListener("drop", drop);
    return () => {
      window.removeEventListener("dragover", over);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("drop", drop);
    };
  }, [src]);

  const isFixture = src.selected?.source === "fixture" || src.selected?.source === "bundled";

  return (
    <div className="app" data-mode={src.mode}>
      <TopBar run={d.run} round={d.round} maxRound={index.maxRound} netOnline={netOnline} mode={src.mode} />
      <Transport
        mode={src.mode}
        setMode={src.setMode}
        runs={src.runs}
        selected={src.selected}
        onSelect={(r) => {
          shownFor.current = null;
          src.setSelected(r);
        }}
        onOpenFile={(f) => {
          shownFor.current = null;
          src.openFile(f);
        }}
        hasRealRuns={src.hasRealRuns}
        index={index}
        count={count}
        n={pb.n}
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
      />

      {(isFixture || src.skipped > 0 || src.load === "error" || (src.mode === "live" && count === 0)) && (
        <div className="notices" role="status">
          {isFixture && (
            <p className="notice">
              <b>Fixture run.</b> Realistic fake data for building the viewer. Real runs land in <span className="mono">.manifest/runs/</span> and show up in the run picker.
            </p>
          )}
          {src.mode === "live" && count === 0 && src.load !== "error" && (
            <p className="notice">
              <b>Waiting for events…</b> tailing <span className="mono">{src.selected?.name ?? "the newest run"}</span>
            </p>
          )}
          {src.skipped > 0 && (
            <p className="notice notice-warn">
              Skipped <b>{src.skipped}</b> malformed line{src.skipped === 1 ? "" : "s"}. The rest of the run is shown.
            </p>
          )}
          {src.load === "error" && (
            <p className="notice notice-warn">
              Couldn't read <span className="mono">{src.selected?.name}</span>: {src.error}
            </p>
          )}
        </div>
      )}

      <main className="grid">
        <TaskBoard index={index} d={d} focus={focus} onPick={(taskId, round) => setPin({ taskId, round })} />
        <Trace events={events} index={index} n={pb.n} focus={focus} pinned={!!pin} onUnpin={() => setPin(null)} version={version} />
        <Growth d={d} index={index} onJumpRound={seekRound} />
        <Results d={d} index={index} />
      </main>

      {dragging && (
        <div className="dropzone" aria-hidden="true">
          <p>Drop a run (.jsonl) to replay it</p>
        </div>
      )}
    </div>
  );
}
