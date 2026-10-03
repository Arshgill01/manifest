/**
 * Tiny read-only file API for the viewer (dev + preview servers). Never writes.
 *   GET /api/runs                       -> { runsDir, runs: [{ id, name, source, size, mtimeMs }] }  newest first
 *   GET /api/runs/:source/:name?from=N  -> bytes [N, EOF) as text; header x-size = file size (for tailing)
 */
import fs from "node:fs";
import path from "node:path";
import type { Connect, Plugin } from "vite";
import { isLive, launchHandler } from "./launch.ts";

const GUI_DIR = path.resolve(import.meta.dirname, "..");
const SOURCES: Record<string, string> = {
  runs: path.resolve(GUI_DIR, process.env.MANIFEST_RUNS_DIR ?? "../.manifest/runs"),
  fixture: path.resolve(GUI_DIR, "fixtures"),
};
const NAME = /^[\w.-]+\.jsonl$/;

function list() {
  const runs = [];
  for (const [source, dir] of Object.entries(SOURCES)) {
    let names: string[] = [];
    try {
      names = fs.readdirSync(dir).filter((n) => NAME.test(n));
    } catch {
      continue;
    }
    for (const name of names) {
      const file = path.join(dir, name);
      const st = fs.statSync(file);
      runs.push({ id: `${source}/${name}`, name, source, size: st.size, mtimeMs: st.mtimeMs, live: source === "runs" && isLive(file) });
    }
  }
  // real runs first, newest first; fixtures last
  return runs.sort((a, b) => (a.source === b.source ? b.mtimeMs - a.mtimeMs : a.source === "runs" ? -1 : 1));
}

const handler: Connect.NextHandleFunction = (req, res, next) => {
  const url = new URL(req.url ?? "/", "http://x");
  if (!url.pathname.startsWith("/api/runs")) return next();
  res.setHeader("cache-control", "no-store");
  if (url.pathname === "/api/runs" || url.pathname === "/api/runs/") {
    res.setHeader("content-type", "application/json");
    res.end(JSON.stringify({ runsDir: SOURCES.runs, runs: list() }));
    return;
  }
  const [, , , source, name] = url.pathname.split("/");
  const dir = SOURCES[source ?? ""];
  if (!dir || !name || !NAME.test(name)) {
    res.statusCode = 404;
    res.end("not found");
    return;
  }
  const file = path.join(dir, name);
  let fd: number | undefined;
  try {
    fd = fs.openSync(file, "r");
    const size = fs.fstatSync(fd).size;
    const from = Math.max(0, Math.min(Number(url.searchParams.get("from") ?? 0) || 0, size));
    const buf = Buffer.alloc(size - from);
    if (buf.length) fs.readSync(fd, buf, 0, buf.length, from);
    res.setHeader("content-type", "text/plain; charset=utf-8");
    res.setHeader("x-size", String(size));
    res.end(buf);
  } catch {
    res.statusCode = 404;
    res.end("not found");
  } finally {
    if (fd !== undefined) fs.closeSync(fd);
  }
};

export function runsPlugin(): Plugin {
  return {
    name: "manifest-runs",
    configureServer(server) {
      server.middlewares.use(launchHandler(SOURCES.runs));
      server.middlewares.use(handler);
    },
    configurePreviewServer(server) {
      server.middlewares.use(launchHandler(SOURCES.runs));
      server.middlewares.use(handler);
    },
  };
}
