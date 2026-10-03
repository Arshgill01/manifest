import type { ManifestEvent, ModelCall, RoutineCall, TaskEnd, TaskStart, WardenBlock } from "./types";

export type TraceItem =
  | { kind: "start"; ev: TaskStart }
  /** manifest mode: a code routine and everything it did (tool calls, student asks). `ev` null = still running */
  | { kind: "routine"; ev: RoutineCall | null; children: ManifestEvent[]; key: number }
  /** baseline mode: the student picks the next move; the tool calls it chose hang off it */
  | { kind: "step"; model: ModelCall | null; children: ManifestEvent[]; key: number; n: number }
  /** manifest mode, seed fallback: no routine applied, so ask-student hands the student the wheel */
  | { kind: "fallback"; ev: RoutineCall | null; children: ManifestEvent[]; key: number }
  | { kind: "end"; ev: TaskEnd };

export interface Trace {
  items: TraceItem[];
  mode: "baseline" | "manifest";
  codeDecisions: number;
  modelCalls: number;
  blocks: WardenBlock[];
}

export function buildTrace(evs: ManifestEvent[], round: number): Trace {
  const start = evs.find((e): e is TaskStart => e.type === "task.start");
  const mode: Trace["mode"] =
    start?.mode === "baseline" || start?.mode === "manifest"
      ? start.mode
      : round === 0 && !evs.some((e) => e.type === "routine.call") ? "baseline" : "manifest";
  const items: TraceItem[] = [];
  let pending: ManifestEvent[] = [];
  let step: Extract<TraceItem, { kind: "step" }> | null = null;
  let codeDecisions = 0, modelCalls = 0, steps = 0;
  const blocks: WardenBlock[] = [];

  for (const e of evs) {
    if (e.type === "warden.block") blocks.push(e);
    if (e.type === "model.call" && e.role === "student") modelCalls++;
    switch (e.type) {
      case "task.start":
        items.push({ kind: "start", ev: e });
        continue;
      case "task.end":
        if (mode === "manifest" && pending.length) items.push({ kind: "routine", ev: null, children: pending, key: pending[0].i });
        pending = [];
        items.push({ kind: "end", ev: e });
        continue;
    }
    if (mode === "manifest") {
      if (e.type === "routine.call") {
        // ask-student is the fallback where the student picks the move; it's not code deciding
        if (e.routine === "ask-student") items.push({ kind: "fallback", ev: e, children: pending, key: pending[0]?.i ?? e.i });
        else {
          codeDecisions++;
          items.push({ kind: "routine", ev: e, children: pending, key: pending[0]?.i ?? e.i });
        }
        pending = [];
      } else {
        pending.push(e);
      }
    } else {
      if (e.type === "model.call") {
        step = { kind: "step", model: e, children: [], key: e.i, n: ++steps };
        items.push(step);
      } else if (e.type === "routine.call") {
        if (e.routine !== "ask-student") codeDecisions++;
        items.push({ kind: "routine", ev: e, children: [], key: e.i });
      } else if (step) {
        step.children.push(e);
      } else {
        step = { kind: "step", model: null, children: [e], key: e.i, n: ++steps };
        items.push(step);
      }
    }
  }
  if (mode === "manifest" && pending.length) {
    const endIdx = items.findIndex((it) => it.kind === "end");
    // a student "step" inside an unfinished group means the fallback is running: the student is driving
    const studentDriving = pending.some((e) => e.type === "model.call" && e.role === "student" && (e.purpose === "step" || e.purpose === "chat"));
    const it: TraceItem = studentDriving
      ? { kind: "fallback", ev: null, children: pending, key: pending[0].i }
      : { kind: "routine", ev: null, children: pending, key: pending[0].i };
    if (endIdx >= 0) items.splice(endIdx, 0, it);
    else items.push(it);
  }
  return { items, mode, codeDecisions, modelCalls, blocks };
}
