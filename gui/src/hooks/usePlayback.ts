import { useCallback, useEffect, useRef, useState } from "react";
import { indexAtTime } from "../lib/derive";

export const SPEEDS = [1, 2, 5, 10, 20] as const;
export type Speed = (typeof SPEEDS)[number];

/**
 * Replay clock over compressed event times. `n` = number of events applied (the playhead).
 * In follow mode (live) the playhead sticks to the newest event until the user scrubs away.
 */
export function usePlayback(ct: number[], count: number, opts: { follow: boolean }) {
  const [n, setN] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<Speed>(10);
  const [following, setFollowing] = useState(opts.follow);
  const vt = useRef(0);
  const ctRef = useRef(ct);
  ctRef.current = ct;

  // entering/leaving live mode
  useEffect(() => setFollowing(opts.follow), [opts.follow]);

  useEffect(() => {
    if (following) {
      setN(count);
      vt.current = count ? ctRef.current[count - 1] : 0;
    }
  }, [following, count]);

  // clamp when the run is swapped
  useEffect(() => {
    setN((x) => Math.min(x, count));
  }, [count]);

  useEffect(() => {
    if (!playing || following) return;
    let raf = 0;
    let last = performance.now();
    const loop = (now: number) => {
      const dt = Math.min(now - last, 100);
      last = now;
      vt.current += dt * speed;
      const c = ctRef.current;
      const next = Math.min(indexAtTime(c, vt.current), count);
      setN((prev) => (prev === next ? prev : next));
      if (next >= count) {
        setPlaying(false);
        return;
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [playing, following, speed, count]);

  const seek = useCallback(
    (to: number) => {
      const x = Math.max(0, Math.min(count, Math.round(to)));
      vt.current = x > 0 ? ctRef.current[x - 1] : 0;
      setN(x);
      if (opts.follow) setFollowing(x >= count);
    },
    [count, opts.follow],
  );

  const toggle = useCallback(() => {
    if (following) {
      setFollowing(false);
      setPlaying(false);
      return;
    }
    setPlaying((p) => {
      if (!p && n >= count) {
        vt.current = 0;
        setN(0);
      }
      return !p;
    });
  }, [following, n, count]);

  return { n, playing, speed, setSpeed, seek, toggle, setPlaying, following, setFollowing };
}
