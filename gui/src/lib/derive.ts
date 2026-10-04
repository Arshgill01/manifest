import type {
  EvalHeldout, GateResult, GrowthProposal, ManifestEvent, ModelCall, RunEnd, RunStart, Split, TaskEnd,
  TaskStart, WardenBlock, WardenManifest, GrowthStep, GrowthRepair,
} from "./types";

export const SPLITS: Split[] = ["train", "gate", "heldout"];

/** Replay compresses idle time: a gap longer than this plays as this long (at 1×). */
export const GAP_CAP_MS = 900;
/** ...and every event gets at least this much screen time, so bursts stay readable. */
export const GAP_MIN_MS = 45;

export interface TaskInfo {
  id: string;
  split: Split;
  domain: string;
  bugShape: string;
  num: string;
}

/** Facts about the whole file (or everything received so far, when live). */
export interface RunIndex {
  tasks: Map<string, TaskInfo>;
  bySplit: Record<Split, string[]>;
  maxRound: number;
  /** event index where each round begins (a round absent from the file shares the next one's start) */
  roundStart: number[];
  /** rounds that actually have events in this file (a resumed run can start at R3) */
  seen: Set<number>;
  /** `${round}|${taskId}` → event indices for that attempt */
  attempts: Map<string, number[]>;
  /** compressed replay time for each event (ms at 1×) */
  ct: number[];
}

export const attemptKey = (round: number, taskId: string) => `${round}|${taskId}`;

export function buildIndex(events: ManifestEvent[], prev?: RunIndex): RunIndex {
  // Incremental when `prev` covers a prefix of `events` (live tail appends only).
  const idx: RunIndex = prev ?? {
    tasks: new Map(),
    bySplit: { train: [], gate: [], heldout: [] },
    maxRound: 0,
    roundStart: [],
    seen: new Set(),
    attempts: new Map(),
    ct: [],
  };
  for (let i = idx.ct.length; i < events.length; i++) {
    const e = events[i];
    const gap = i === 0 ? 0 : e.t - events[i - 1].t;
    idx.ct.push(i === 0 ? 0 : idx.ct[i - 1] + Math.max(GAP_MIN_MS, Math.min(gap, GAP_CAP_MS)));
    if (e.round > idx.maxRound) idx.maxRound = e.round;
    idx.seen.add(e.round);
    while (idx.roundStart.length <= e.round) idx.roundStart.push(i);
    if (e.taskId) {
      if (!idx.tasks.has(e.taskId) && e.split) {
        const ts = e.type === "task.start" ? (e as TaskStart) : null;
        const num = e.taskId.match(/(\d+)$/)?.[1] ?? "";
        const domain = ts?.domain ?? e.taskId.replace(/-?\d+$/, "");
        idx.tasks.set(e.taskId, { id: e.taskId, split: e.split, domain, bugShape: ts?.bugShape ?? "", num });
        idx.bySplit[e.split].push(e.taskId);
      } else if (e.type === "task.start") {
        const info = idx.tasks.get(e.taskId);
        if (info && !info.bugShape) info.bugShape = (e as TaskStart).bugShape;
      }
      const k = attemptKey(e.round, e.taskId);
      const list = idx.attempts.get(k);
      if (list) list.push(i);
      else idx.attempts.set(k, [i]);
    }
  }
  for (const s of SPLITS) idx.bySplit[s].sort(byDomainThenNum(idx.tasks));
  return idx;
}

const byDomainThenNum = (tasks: Map<string, TaskInfo>) => (a: string, b: string) => {
  const ta = tasks.get(a)!, tb = tasks.get(b)!;
  return ta.domain === tb.domain ? ta.num.localeCompare(tb.num, undefined, { numeric: true }) : ta.domain.localeCompare(tb.domain);
};

export type CellStatus = "running" | "pass" | "fail";
export interface Cell {
  status: CellStatus;
  end?: TaskEnd;
}

export type Phase = "train" | "proposal" | "warden" | "gate" | "heldout" | "done";

export interface RoundState {
  round: number;
  proposal?: GrowthProposal;
  manifest?: WardenManifest;
  gate?: GateResult;
  /** v2: the step's final outcome (also for candidates rejected before the gate) and the window re-run */
  step?: GrowthStep;
  repair?: GrowthRepair;
  heldout?: EvalHeldout;
  teacher: ModelCall[];
  gateRun: { done: number; passed: number; running: boolean };
  phase: Phase;
}

export interface Derived {
  n: number;
  last: ManifestEvent | null;
  run: RunStart | null;
  end: RunEnd | null;
  round: number;
  /** taskId → per-round cell */
  cells: Map<string, (Cell | undefined)[]>;
  /** the attempt the trace should follow */
  active: { taskId: string; round: number } | null;
  rounds: RoundState[];
  teacherCost: number;
  blocks: WardenBlock[];
  accepted: string[];
  rejected: string[];
}

function newRound(round: number): RoundState {
  return { round, teacher: [], gateRun: { done: 0, passed: 0, running: false }, phase: round === 0 ? "train" : "train" };
}

/** State after applying events[0..n). Cheap enough (<1 ms for a few thousand events) to recompute per frame. */
export function derive(events: ManifestEvent[], n: number): Derived {
  n = Math.min(n, events.length);
  const d: Derived = {
    n, last: n > 0 ? events[n - 1] : null, run: null, end: null, round: 0, cells: new Map(), active: null,
    rounds: [], teacherCost: 0, blocks: [], accepted: [], rejected: [],
  };
  const R = (r: number) => {
    while (d.rounds.length <= r) d.rounds.push(newRound(d.rounds.length));
    return d.rounds[r];
  };
  const setCell = (taskId: string, round: number, cell: Cell) => {
    let row = d.cells.get(taskId);
    if (!row) d.cells.set(taskId, (row = []));
    row[round] = cell;
  };
  let openTask: { taskId: string; round: number } | null = null;

  for (let i = 0; i < n; i++) {
    const e = events[i];
    d.round = e.round;
    const rs = R(e.round);
    switch (e.type) {
      case "run.start":
        d.run = e;
        break;
      case "run.end":
        d.end = e;
        rs.phase = "done";
        break;
      case "task.start":
        if (e.taskId) {
          setCell(e.taskId, e.round, { status: "running" });
          openTask = { taskId: e.taskId, round: e.round };
          d.active = openTask;
          if (e.split === "gate") rs.gateRun.running = true;
          if (e.split) rs.phase = e.split === "train" ? "train" : e.split;
        }
        break;
      case "task.end":
        if (e.taskId) {
          setCell(e.taskId, e.round, { status: e.pass ? "pass" : "fail", end: e });
          d.active = { taskId: e.taskId, round: e.round };
          openTask = null;
          if (e.split === "gate") {
            rs.gateRun.done++;
            if (e.pass) rs.gateRun.passed++;
          }
        }
        break;
      case "model.call":
        if (e.role === "teacher") {
          rs.teacher.push(e);
          d.teacherCost += e.costUsd ?? 0;
          if (rs.phase === "train") rs.phase = "proposal";
        }
        break;
      case "growth.proposal":
        rs.proposal = e;
        rs.phase = "proposal";
        break;
      case "warden.manifest":
        rs.manifest = e;
        rs.phase = "warden";
        break;
      case "warden.block":
        d.blocks.push(e);
        break;
      case "gate.result":
        rs.gate = e;
        rs.gateRun.running = false;
        // v2 runs count outcomes from growth.step (a candidate can be rejected before any gate)
        if (d.run?.mode !== "growth-stream") (e.accepted ? d.accepted : d.rejected).push(e.routine);
        break;
      case "growth.repair":
        rs.repair = e;
        break;
      case "growth.step":
        rs.step = e;
        (e.outcome === "accepted" ? d.accepted : d.rejected).push((e.changes ?? []).join(", ") || "(no change)");
        break;
      case "eval.heldout":
        rs.heldout = e;
        break;
    }
  }
  if (openTask) d.active = openTask;
  return d;
}

/** Events of one task attempt, up to the playhead. */
export function attemptEvents(events: ManifestEvent[], index: RunIndex, round: number, taskId: string, n: number) {
  const ids = index.attempts.get(attemptKey(round, taskId)) ?? [];
  const out: ManifestEvent[] = [];
  for (const i of ids) {
    if (i >= n) break;
    out.push(events[i]);
  }
  return out;
}

/** Find the playhead index for a compressed time. */
export function indexAtTime(ct: number[], time: number): number {
  let lo = 0, hi = ct.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (ct[mid] <= time) lo = mid + 1;
    else hi = mid;
  }
  return lo; // number of events with ct <= time
}

/** Display name for a model id. The spec pins the teacher to DeepSeek V4.1 Flash; the raw id is shown beside it. */
export const prettyModel = (id: string | undefined | null) => {
  if (!id) return "—";
  return /deepseek/i.test(id) ? "DeepSeek V4.1 Flash" : id;
};
