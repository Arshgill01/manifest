import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { JsonlParser, parseAll } from "../parse";
import { attemptEvents, buildIndex, derive } from "../derive";
import { buildTrace } from "../trace";

const fixture = readFileSync(new URL("../../../fixtures/demo-run.jsonl", import.meta.url), "utf8");

describe("JsonlParser", () => {
  it("holds a partial trailing line until its newline arrives (live tail)", () => {
    const p = new JsonlParser();
    const line = '{"ts":"2026-10-03T08:00:00.000Z","type":"run.start","round":0,"taskId":null,"split":null,"mode":"m","student":"s","teacher":"t","online":true}';
    expect(p.push(line.slice(0, 40))).toHaveLength(0);
    expect(p.push(line.slice(40) + "\n")).toHaveLength(1);
    expect(p.events[0].i).toBe(0);
  });

  it("skips malformed and unknown lines without failing", () => {
    const p = parseAll('not json\n{"type":"mystery"}\n{"ts":"x","type":"run.end","round":0,"summary":{}}\n');
    expect(p.skipped).toBe(2);
    expect(p.events).toHaveLength(1);
  });

  it("indexes events contiguously across chunks", () => {
    const lines = fixture.split("\n").slice(0, 50).join("\n") + "\n";
    const p = new JsonlParser();
    p.push(lines.slice(0, 3000));
    p.push(lines.slice(3000));
    expect(p.events.map((e) => e.i)).toEqual([...Array(p.events.length).keys()]);
  });
});

describe("derive over the fixture", () => {
  const { events } = parseAll(fixture);
  const index = buildIndex(events);

  it("finds 26 tasks across the three splits and 3 growth rounds", () => {
    expect(index.bySplit.train).toHaveLength(12);
    expect(index.bySplit.gate).toHaveLength(6);
    expect(index.bySplit.heldout).toHaveLength(8);
    expect(index.maxRound).toBe(3);
  });

  it("tells the story at the end of the run", () => {
    const d = derive(events, events.length);
    expect(d.accepted).toEqual(["trace-to-source", "verify-and-rollback"]);
    expect(d.rejected).toEqual(["dependency-doctor"]);
    expect(d.blocks).toHaveLength(1);
    expect(d.rounds[3].heldout?.passed).toBe(6);
    expect(d.cells.get("ledgerly-07")?.map((c) => c?.status)).toEqual(["fail", "fail", "fail", "pass"]);
  });

  it("clamps a playhead past the end instead of crashing", () => {
    expect(() => derive(events, events.length + 500)).not.toThrow();
  });

  it("is incremental for live tails", () => {
    const half = buildIndex(events.slice(0, 1000));
    const full = buildIndex(events, half);
    expect(full.ct).toEqual(buildIndex(events).ct);
  });
});

describe("trace grouping", () => {
  const { events } = parseAll(fixture);
  const index = buildIndex(events);

  it("baseline: the student drives every step, zero code decisions", () => {
    const t = buildTrace(attemptEvents(events, index, 0, "ledgerly-07", events.length), 0);
    expect(t.mode).toBe("baseline");
    expect(t.codeDecisions).toBe(0);
    expect(t.modelCalls).toBe(12);
  });

  it("grown harness: code routines drive, the student is asked only for judgement", () => {
    const t = buildTrace(attemptEvents(events, index, 3, "ledgerly-07", events.length), 3);
    expect(t.mode).toBe("manifest");
    const routines = t.items.flatMap((x) => (x.kind === "routine" && x.ev ? [x.ev.routine] : []));
    expect(routines).toEqual(["start", "trace-to-source", "verify-and-rollback"]);
    expect(t.modelCalls).toBe(3);
  });

  it("ask-student fallback is rendered as the student driving, not as code", () => {
    const t = buildTrace(attemptEvents(events, index, 1, "ledgerly-02", events.length), 1);
    expect(t.items.some((x) => x.kind === "fallback")).toBe(true);
    expect(t.items.some((x) => x.kind === "routine" && x.ev?.routine === "ask-student")).toBe(false);
    expect(t.blocks).toHaveLength(1);
  });
});

describe("v2 growth (paper failure window)", () => {
  const ev = (o: Record<string, unknown>) => JSON.stringify({ ts: "2026-10-05T08:00:00.000Z", taskId: null, split: null, ...o });
  const log = [
    ev({ type: "run.start", round: 0, mode: "growth-stream", student: "s", teacher: "t", online: true }),
    ev({ type: "growth.proposal", round: 1, routine: "a", rationale: "r", triggerDescription: "t", skillPath: "x" }),
    ev({ type: "growth.repair", round: 1, step: 1, candidate: ["a"], solved: [], unsolved: ["x-1"], threshold: 1, ok: false }),
    ev({ type: "growth.step", round: 1, step: 1, outcome: "rejected", stage: "repair", reason: "solved 0", changes: ["a"], harness: 0 }),
    ev({ type: "growth.proposal", round: 2, routine: "b", rationale: "r", triggerDescription: "t", skillPath: "x" }),
    ev({ type: "gate.result", round: 2, routine: "b", accepted: true, gateBefore: 0, gateAfter: 2, regressions: [], modelCallsBefore: 1, modelCallsAfter: 1 }),
    ev({ type: "growth.step", round: 2, step: 2, outcome: "accepted", stage: "accepted", reason: "", changes: ["b"], harness: 1 }),
  ].join("\n") + "\n";

  it("counts outcomes from growth.step, including candidates rejected before any gate", () => {
    const p = parseAll(log);
    const d = derive(p.events, p.events.length);
    expect(d.accepted).toEqual(["b"]);
    expect(d.rejected).toEqual(["a"]);
    expect(d.rounds[1].step?.stage).toBe("repair");
    expect(d.rounds[1].repair?.unsolved).toEqual(["x-1"]);
  });
});
