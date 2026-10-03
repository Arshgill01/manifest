import { useCallback, useEffect, useRef, useState } from "react";
import { buildIndex, type RunIndex } from "../lib/derive";
import { JsonlParser } from "../lib/parse";
import type { ManifestEvent } from "../lib/types";

export interface RunEntry {
  id: string;
  name: string;
  source: "runs" | "fixture" | "bundled" | "file";
  size?: number;
  mtimeMs?: number;
}

export type Mode = "replay" | "live";
export type LoadState = "idle" | "loading" | "ready" | "error";

const BUNDLED: RunEntry = { id: "bundled/demo-run.jsonl", name: "demo-run.jsonl", source: "bundled" };
const POLL_MS = 500;
const LIST_MS = 2500;

async function fetchList(): Promise<{ runs: RunEntry[]; runsDir: string } | null> {
  try {
    const r = await fetch("/api/runs");
    if (!r.ok || !r.headers.get("content-type")?.includes("json")) return null;
    return await r.json();
  } catch {
    return null;
  }
}

async function fetchChunk(id: string, from: number) {
  const r = await fetch(`/api/runs/${id}?from=${from}`);
  if (!r.ok) throw new Error(`${r.status} reading ${id}`);
  const buf = await r.arrayBuffer();
  return { bytes: buf.byteLength, text: new TextDecoder().decode(buf), size: Number(r.headers.get("x-size") ?? from + buf.byteLength) };
}

/**
 * Where events come from. Replay loads a whole file; Live tails the newest file in .manifest/runs and hops to
 * a newer file when one appears. With no dev/preview server (static hosting) the bundled fixture still works.
 */
export function useRunSource() {
  const [mode, setMode] = useState<Mode>("replay");
  const [runs, setRuns] = useState<RunEntry[]>([]);
  const [runsDir, setRunsDir] = useState<string | null>(null);
  const [serverless, setServerless] = useState(false);
  const [selected, setSelected] = useState<RunEntry | null>(null);
  const [load, setLoad] = useState<LoadState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const parser = useRef(new JsonlParser());
  const index = useRef<RunIndex>(buildIndex([]));
  const offset = useRef(0);

  const reset = () => {
    parser.current = new JsonlParser();
    index.current = buildIndex([]);
    offset.current = 0;
  };
  const ingest = (text: string, final: boolean) => {
    const added = parser.current.push(text);
    const tail = final ? parser.current.end() : [];
    if (added.length || tail.length || final) {
      index.current = buildIndex(parser.current.events, index.current);
      setVersion((v) => v + 1);
    }
  };

  // run list (and keep it fresh so Live can hop to a newer file)
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      const res = await fetchList();
      if (!alive) return;
      if (!res) {
        setServerless(true);
        setRuns((prev) => (prev.some((r) => r.source === "bundled") ? prev : [BUNDLED, ...prev.filter((r) => r.source === "file")]));
        return;
      }
      setServerless(false);
      setRunsDir(res.runsDir);
      setRuns((prev) => [...res.runs, ...prev.filter((r) => r.source === "file")]);
    };
    tick();
    const t = setInterval(tick, LIST_MS);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  const real = runs.filter((r) => r.source === "runs");
  const newestReal = real.length ? real.reduce((a, b) => ((b.mtimeMs ?? 0) > (a.mtimeMs ?? 0) ? b : a)) : null;

  // default selection: newest real run, else the fixture
  useEffect(() => {
    if (selected || !runs.length) return;
    setSelected(newestReal ?? runs.find((r) => r.source === "fixture") ?? runs[0]);
  }, [runs, selected, newestReal]);

  // live: follow the newest real file
  useEffect(() => {
    if (mode === "live" && newestReal && newestReal.id !== selected?.id) setSelected(newestReal);
  }, [mode, newestReal, selected?.id]);

  // load / tail the selected run
  useEffect(() => {
    if (!selected || selected.source === "file") return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    reset();
    setLoad("loading");
    setError(null);
    setVersion((v) => v + 1);

    if (selected.source === "bundled") {
      import("../../fixtures/demo-run.jsonl?raw")
        .then((m) => {
          if (!alive) return;
          ingest(m.default, true);
          setLoad("ready");
        })
        .catch((e) => alive && (setLoad("error"), setError(String(e))));
      return () => {
        alive = false;
      };
    }

    const poll = async () => {
      try {
        const { text, bytes, size } = await fetchChunk(selected.id, offset.current);
        if (!alive) return;
        if (size < offset.current) {
          // file was truncated/rewritten: start over
          reset();
          setVersion((v) => v + 1);
        } else {
          offset.current += bytes;
          ingest(text, mode === "replay");
        }
        setLoad("ready");
      } catch (e) {
        if (!alive) return;
        setLoad("error");
        setError(e instanceof Error ? e.message : String(e));
      }
      if (alive && mode === "live") timer = setTimeout(poll, POLL_MS);
    };
    poll();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [selected, mode]);

  /** A .jsonl dropped onto the window or picked from disk (works with no server at all). */
  const openFile = useCallback(async (file: File) => {
    const text = await file.text();
    const entry: RunEntry = { id: `file/${file.name}`, name: file.name, source: "file", size: file.size };
    setMode("replay");
    setRuns((prev) => [entry, ...prev.filter((r) => r.id !== entry.id)]);
    setSelected(entry);
    reset();
    ingest(text, true);
    setLoad("ready");
    setError(null);
  }, []);

  const events: ManifestEvent[] = parser.current.events;
  return {
    mode, setMode, runs, runsDir, serverless, selected, setSelected, load, error, version, events,
    index: index.current, skipped: parser.current.skipped, openFile, hasRealRuns: real.length > 0,
  };
}
