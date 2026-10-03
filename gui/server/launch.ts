/**
 * Start a harness run from the GUI. The GUI never becomes the harness: it spawns the same CLIs you'd type
 * (CONTRACT 2.2 `growth.eval`, track C `growth.grow`) and then live-tails the event log they write.
 *
 *   GET  /api/tasks          -> splits.json profiles (for the composer)
 *   GET  /api/launch         -> { active, last, busy }  (busy = some other run file is still being written)
 *   POST /api/launch         -> start one run            { kind, mode, split, tasks[], profile, rounds, dry }
 *   POST /api/launch/stop    -> SIGINT the active run (the harness writes run.end on the way out)
 *
 * Guard rails: arguments are whitelisted and passed as argv (no shell); one run at a time; and nothing starts while
 * another run file is still growing, because two Ollama-backed suites on an 8 GB laptop is a crash (CLAUDE.md).
 */
import { execFileSync, spawn, type ChildProcess } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import type { Connect } from "vite";

export const ROOT = path.resolve(import.meta.dirname, "..", "..");
const PY = (process.env.MANIFEST_PYTHON ?? "uv run python").split(" ");
const BUSY_WINDOW_MS = 90_000;
const ID = /^[a-z]+-\d{2}$/;

interface Active {
  id: string;
  argv: string[];
  pid: number;
  startedAt: number;
  child: ChildProcess;
  out: string[];
  exit?: { code: number | null; signal: string | null; at: number };
}
let active: Active | null = null;
let last: Omit<Active, "child"> | null = null;

type Body = {
  kind?: "eval" | "grow";
  mode?: string;
  split?: string;
  tasks?: string[];
  profile?: string;
  rounds?: number;
  dry?: boolean;
};

function knownProfiles(): string[] {
  try {
    const s = JSON.parse(fs.readFileSync(path.join(ROOT, "tasks", "splits.json"), "utf8"));
    return Object.keys(s.profiles ?? {});
  } catch {
    return ["core", "full"];
  }
}

export function buildArgv(b: Body): string[] | string {
  const profile = b.profile ?? "core";
  if (!knownProfiles().includes(profile)) return `unknown task profile ${profile}`;
  const tasks = (b.tasks ?? []).filter((t) => ID.test(t));
  if ((b.tasks ?? []).length !== tasks.length) return "task ids look like ledgerly-07";
  if (b.kind === "grow") {
    const rounds = Math.max(1, Math.min(4, Math.round(Number(b.rounds) || 3)));
    const argv = ["-m", "growth.grow", "--rounds", String(rounds), "--profile", profile];
    if (b.dry) argv.push("--fake-teacher", "--stub-runner"); // no network, no Ollama: a rehearsal
    return argv;
  }
  const mode = b.mode ?? "";
  if (!["baseline", "manifest", "oracle", "noop"].includes(mode)) return `unknown mode ${mode}`;
  const split = b.split ?? "";
  if (!["train", "gate", "heldout"].includes(split)) return `unknown split ${split}`;
  // 240 s per task: the student on an 8 GB laptop needs it (the runner defaults to 120)
  const argv = ["-m", "growth.eval", "--split", split, "--mode", mode, "--profile", profile, "--max-seconds", "240", "--label", `gui-${mode}-${split}`];
  // a run started here is something you want to watch: baseline skips the round-0 cache; manifest = the grown harness
  if (mode === "baseline") argv.push("--round", "0", "--force");
  if (mode === "manifest") argv.push("--round", "2"); // the harness as grown (matches the integrator's demo command)
  if (tasks.length) argv.push("--tasks", tasks.join(","));
  return argv;
}

/** A run file is live if it changed recently and its last line isn't run.end. */
export function isLive(file: string): boolean {
  try {
    const st = fs.statSync(file);
    if (Date.now() - st.mtimeMs > BUSY_WINDOW_MS || st.size === 0) return false;
    const fd = fs.openSync(file, "r");
    const len = Math.min(st.size, 4096);
    const buf = Buffer.alloc(len);
    fs.readSync(fd, buf, 0, len, st.size - len);
    fs.closeSync(fd);
    const lastLine = buf.toString("utf8").trimEnd().split("\n").pop() ?? "";
    return !lastLine.includes('"run.end"');
  } catch {
    return false;
  }
}

/** Every worktree of this repo shares one laptop and one Ollama, so look at all their runs dirs, not just ours. */
let dirsCache: { at: number; dirs: string[] } | null = null;
function allRunsDirs(own: string): string[] {
  if (dirsCache && Date.now() - dirsCache.at < 20_000) return dirsCache.dirs;
  const dirs = new Set([own]);
  try {
    const out = execFileSync("git", ["worktree", "list", "--porcelain"], { cwd: ROOT, encoding: "utf8", timeout: 3000 });
    for (const line of out.split("\n")) if (line.startsWith("worktree ")) dirs.add(path.join(line.slice(9).trim(), ".manifest", "runs"));
  } catch {
    /* not a git checkout: our own dir is all we can see */
  }
  dirsCache = { at: Date.now(), dirs: [...dirs] };
  return dirsCache.dirs;
}

/** Another writer is mid-run in any worktree. Returns a short "where/what" label. */
function busyFile(runsDir: string): string | null {
  for (const dir of allRunsDirs(runsDir)) {
    try {
      const hit = fs.readdirSync(dir).find((n) => n.endsWith(".jsonl") && isLive(path.join(dir, n)));
      if (hit) return dir === runsDir ? hit : `${path.basename(path.dirname(path.dirname(dir)))}/${hit}`;
    } catch {
      /* worktree without a runs dir */
    }
  }
  return null;
}

/** Runs that load the student (or call the teacher). Self-tests and rehearsals don't touch Ollama. */
const needsModel = (b: Body) => (b.kind === "grow" ? !b.dry : b.mode === "baseline" || b.mode === "manifest");

const snapshot = (a: Omit<Active, "child"> | Active | null) =>
  a && { id: a.id, cmd: [...PY, ...a.argv].join(" "), pid: a.pid, startedAt: a.startedAt, out: a.out.slice(-40), exit: a.exit ?? null };

function json(res: Parameters<Connect.NextHandleFunction>[1], code: number, body: unknown) {
  res.statusCode = code;
  res.setHeader("content-type", "application/json");
  res.setHeader("cache-control", "no-store");
  res.end(JSON.stringify(body));
}

function readBody(req: Connect.IncomingMessage): Promise<Body> {
  return new Promise((resolve) => {
    let s = "";
    req.on("data", (c) => (s += c));
    req.on("end", () => {
      try {
        resolve(JSON.parse(s || "{}"));
      } catch {
        resolve({});
      }
    });
  });
}

export function launchHandler(runsDir: string): Connect.NextHandleFunction {
  return async (req, res, next) => {
    const url = new URL(req.url ?? "/", "http://x");
    if (url.pathname === "/api/tasks") {
      try {
        const splits = JSON.parse(fs.readFileSync(path.join(ROOT, "tasks", "splits.json"), "utf8"));
        return json(res, 200, { profiles: splits.profiles ?? { full: splits }, novelDomain: splits.novelDomain });
      } catch {
        return json(res, 404, { error: "tasks/splits.json not found: run the task generator first" });
      }
    }
    if (!url.pathname.startsWith("/api/launch")) return next();

    if (url.pathname === "/api/launch" && req.method === "GET") {
      const busy = active && !active.exit ? null : busyFile(runsDir);
      return json(res, 200, { active: snapshot(active), last: snapshot(last), busy });
    }
    if (url.pathname === "/api/launch/stop" && req.method === "POST") {
      if (!active || active.exit) return json(res, 409, { error: "nothing is running" });
      active.child.kill("SIGINT");
      const a = active;
      setTimeout(() => !a.exit && a.child.kill("SIGTERM"), 8000);
      return json(res, 202, { stopping: a.id });
    }
    if (url.pathname === "/api/launch" && req.method === "POST") {
      if (active && !active.exit) return json(res, 409, { error: "a run is already going: stop it first", active: snapshot(active) });
      const body = await readBody(req);
      const busy = needsModel(body) ? busyFile(runsDir) : null;
      if (busy) return json(res, 409, { error: `${busy} is still being written. One model run at a time on 8 GB.`, busy });
      const argv = buildArgv(body);
      if (typeof argv === "string") return json(res, 400, { error: argv });

      const child = spawn(PY[0], [...PY.slice(1), ...argv], {
        cwd: ROOT,
        env: { ...process.env, PYTHONUNBUFFERED: "1" },
        stdio: ["ignore", "pipe", "pipe"],
      });
      const a: Active = { id: `run-${Date.now()}`, argv, pid: child.pid ?? -1, startedAt: Date.now(), child, out: [] };
      const push = (chunk: Buffer) => {
        a.out.push(...chunk.toString("utf8").split("\n").filter(Boolean));
        if (a.out.length > 400) a.out.splice(0, a.out.length - 400);
      };
      child.stdout?.on("data", push);
      child.stderr?.on("data", push);
      child.on("error", (e) => {
        a.out.push(`failed to start: ${e.message}`);
        a.exit = { code: -1, signal: null, at: Date.now() };
      });
      child.on("exit", (code, signal) => {
        a.exit = { code, signal, at: Date.now() };
        const { child: _c, ...rest } = a;
        last = rest;
      });
      active = a;
      return json(res, 201, snapshot(a));
    }
    return next();
  };
}
