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
  /** still being written (server: changed recently and no run.end yet) */
  live?: boolean;
}

export type LoadState = "idle" | "loading" | "ready" | "error";

const BUNDLED: RunEntry = { id: "bundled/demo-run.jsonl", name: "demo-run.jsonl", source: "bundled" };
const POLL_MS = 500;
const LIST_MS = 2000;

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
 * Where events come from. Selecting a run loads it; if that run is still being written it keeps tailing until
 * run.end arrives (live is a property of the run, not a mode). With no dev/preview server, the bundled fixture and
 * dropped files still work.
 */
export function useRunSource() {
  const [runs, setRuns] = useState<RunEntry[]>([]);
  const [serverless, setServerless] = useState(false);
  const [selected, setSelected] = useState<RunEntry | null>(null);
  const [load, setLoad] = useState<LoadState>("idle");
  /** id of the run whose first load finished (guards against acting on the previous run's "ready") */
  const [loadedId, setLoadedId] = useState<string | null>(null);
  const [tailing, setTailing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const parser = useRef(new JsonlParser());
  const index = useRef<RunIndex>(buildIndex([]));
  const offset = useRef(0);
  const liveIds = useRef(new Set<string>());

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

  const refreshList = useCallback(async () => {
    const res = await fetchList();
    if (!res) {
      setServerless(true);
      setRuns((prev) => (prev.some((r) => r.source === "bundled") ? prev : [BUNDLED, ...prev.filter((r) => r.source === "file")]));
      return null;
    }
    setServerless(false);
    liveIds.current = new Set(res.runs.filter((r) => r.live).map((r) => r.id));
    setRuns((prev) => [...res.runs, ...prev.filter((r) => r.source === "file")]);
    return res.runs;
  }, []);

  useEffect(() => {
    refreshList();
    const t = setInterval(refreshList, LIST_MS);
    return () => clearInterval(t);
  }, [refreshList]);

  // load the selected run; keep tailing while it's live
  useEffect(() => {
    if (!selected || selected.source === "file") return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    reset();
    setLoad("loading");
    setLoadedId(null);
    setError(null);
    setTailing(false);
    setVersion((v) => v + 1);

    if (selected.source === "bundled") {
      import("../../fixtures/demo-run.jsonl?raw")
        .then((m) => {
          if (!alive) return;
          ingest(m.default, true);
          setLoad("ready");
          setLoadedId(selected.id);
        })
        .catch((e) => alive && (setLoad("error"), setError(String(e))));
      return () => {
        alive = false;
      };
    }

    let quiet = 0;
    const poll = async () => {
      try {
        const { text, bytes, size } = await fetchChunk(selected.id, offset.current);
        if (!alive) return;
        if (size < offset.current) {
          reset(); // truncated/rewritten: start over
          setVersion((v) => v + 1);
        } else {
          offset.current += bytes;
          ingest(text, false);
        }
        quiet = bytes ? 0 : quiet + 1;
        setLoad("ready");
        setLoadedId(selected.id);
      } catch (e) {
        if (!alive) return;
        setLoad("error");
        setError(e instanceof Error ? e.message : String(e));
        return;
      }
      const ended = parser.current.events.some((e) => e.type === "run.end");
      const live = !ended && (liveIds.current.has(selected.id) || quiet < 6);
      setTailing(live);
      if (alive && live) timer = setTimeout(poll, POLL_MS);
      else if (alive) ingest("", true);
    };
    poll();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [selected]);

  /** A .jsonl dropped onto the window or picked from disk (works with no server at all). */
  const openFile = useCallback(async (file: File) => {
    const text = await file.text();
    const entry: RunEntry = { id: `file/${file.name}`, name: file.name, source: "file", size: file.size };
    setRuns((prev) => [entry, ...prev.filter((r) => r.id !== entry.id)]);
    setSelected(entry);
    reset();
    ingest(text, true);
    setTailing(false);
    setLoad("ready");
    setLoadedId(entry.id);
    setError(null);
  }, []);

  const events: ManifestEvent[] = parser.current.events;
  return {
    runs, serverless, selected, setSelected, load, loadedId, tailing, error, version, events,
    index: index.current, skipped: parser.current.skipped, openFile, refreshList,
  };
}
