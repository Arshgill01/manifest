import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { attemptEvents, attemptKey, type Derived, type RunIndex } from "../lib/derive";
import type { EvalHeldout, GateResult, GrowthProposal, ManifestEvent, ModelCall, RunEnd, RunStart, Split, TaskEnd, TaskStart, WardenManifest, GrowthStep, GrowthRepair } from "../lib/types";
import { AttemptTrace } from "./Trace";
import { Check, Cross } from "./TaskBoard";
import { GateLine, Stamp, WardenCard } from "./Growth";
import { fmtInt, fmtMs, fmtUsd } from "../lib/format";
import { prettyModel } from "../lib/derive";

type Block =
  | { k: "start"; ev: RunStart }
  | { k: "round"; round: number; growth: boolean }
  | { k: "split"; round: number; split: Split }
  | { k: "task"; round: number; taskId: string; start: TaskStart; end?: TaskEnd; blocked: number }
  | { k: "teacher"; round: number; calls: ModelCall[]; proposal?: GrowthProposal; manifest?: WardenManifest; gate?: GateResult;
      step?: GrowthStep; repair?: GrowthRepair }
  | { k: "heldout"; ev: EvalHeldout }
  | { k: "end"; ev: RunEnd };

const SPLIT_NAME: Record<Split, string> = { train: "Train", gate: "Gate", heldout: "Held-out" };
const SPLIT_NOTE: Record<Split, string> = {
  train: "practice tasks · failures go to the teacher",
  gate: "unseen · decides keep or drop",
  heldout: "never seen by the teacher",
};

/** The run as a conversation: rounds, one line per task, the teacher's proposals as messages. */
function blocksOf(events: ManifestEvent[], n: number): Block[] {
  const out: Block[] = [];
  const tasks = new Map<string, Extract<Block, { k: "task" }>>();
  const teacher = new Map<number, Extract<Block, { k: "teacher" }>>();
  let round = -1;
  let split: Split | null = null;
  let growth = false;
  const teacherFor = (r: number) => {
    let b = teacher.get(r);
    if (!b) {
      b = { k: "teacher", round: r, calls: [] };
      teacher.set(r, b);
      out.push(b);
      split = null;
    }
    return b;
  };
  for (let i = 0; i < Math.min(n, events.length); i++) {
    const e = events[i];
    if (e.type === "run.start") {
      growth = e.mode === "growth" || e.mode === "growth-stream";
      out.push({ k: "start", ev: e });
      continue;
    }
    if (e.round !== round && e.type !== "run.end") {
      round = e.round;
      split = null;
      if (growth || round > 0) out.push({ k: "round", round, growth });
    }
    switch (e.type) {
      case "task.start": {
        if (!e.taskId) break;
        if (e.split && e.split !== split) {
          split = e.split;
          out.push({ k: "split", round, split });
        }
        const b: Extract<Block, { k: "task" }> = { k: "task", round: e.round, taskId: e.taskId, start: e, blocked: 0 };
        tasks.set(attemptKey(e.round, e.taskId), b);
        out.push(b);
        break;
      }
      case "task.end": {
        const b = e.taskId ? tasks.get(attemptKey(e.round, e.taskId)) : undefined;
        if (b) b.end = e;
        break;
      }
      case "warden.block": {
        const b = e.taskId ? tasks.get(attemptKey(e.round, e.taskId)) : undefined;
        if (b) b.blocked++;
        break;
      }
      case "model.call":
        if (e.role === "teacher") teacherFor(e.round).calls.push(e);
        break;
      case "growth.proposal":
        teacherFor(e.round).proposal = e;
        break;
      case "warden.manifest":
        teacherFor(e.round).manifest = e;
        break;
      case "gate.result":
        teacherFor(e.round).gate = e;
        break;
      case "growth.repair":
        teacherFor(e.round).repair = e;
        break;
      case "growth.step":
        teacherFor(e.round).step = e;
        break;
      case "eval.heldout":
        out.push({ k: "heldout", ev: e });
        split = null;
        break;
      case "run.end":
        out.push({ k: "end", ev: e });
        break;
    }
  }
  return out;
}

interface Props {
  events: ManifestEvent[];
  index: RunIndex;
  d: Derived;
  n: number;
  version: number;
  following: boolean;
  /** an attempt to open and scroll to (board click, ?pin=, Warden "view") */
  focus: { taskId: string; round: number; nonce: number } | null;
}

export function Transcript({ events, index, d, n, version, following, focus }: Props) {
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const blocks = useMemo(() => blocksOf(events, n), [version, n]);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [closed, setClosed] = useState<Set<string>>(new Set());
  const body = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const running = d.active && !d.cells.get(d.active.taskId)?.[d.active.round]?.end ? attemptKey(d.active.round, d.active.taskId) : null;

  useEffect(() => {
    setOpen(new Set());
    setClosed(new Set());
  }, [events]);

  // open + reveal a requested attempt
  useEffect(() => {
    if (!focus) return;
    const k = attemptKey(focus.round, focus.taskId);
    setOpen((s) => new Set(s).add(k));
    setClosed((s) => {
      const x = new Set(s);
      x.delete(k);
      return x;
    });
    stick.current = false;
    requestAnimationFrame(() =>
      body.current?.querySelector(`[data-attempt="${CSS.escape(k)}"]`)?.scrollIntoView({ block: "start", behavior: "smooth" }),
    );
  }, [focus]);

  // follow the newest line while playing / live, unless the reader scrolled up
  useLayoutEffect(() => {
    if (following) stick.current = true;
  }, [following]);
  useLayoutEffect(() => {
    const el = body.current;
    if (el && stick.current && following) el.scrollTop = el.scrollHeight;
  }, [n, following]);

  const isOpen = (k: string) => (open.has(k) || k === running) && !closed.has(k);
  const toggle = (k: string) => {
    const now = isOpen(k);
    setOpen((s) => {
      const x = new Set(s);
      if (now) x.delete(k);
      else x.add(k);
      return x;
    });
    setClosed((s) => {
      const x = new Set(s);
      if (now) x.add(k);
      else x.delete(k);
      return x;
    });
  };

  return (
    <div
      className="transcript"
      ref={body}
      onScroll={(e) => {
        const el = e.currentTarget;
        stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
      }}
    >
      <div className="tx-col">
        {blocks.length === 0 && <p className="tx-empty">Waiting for the first event…</p>}
        {blocks.map((b, k) => {
          switch (b.k) {
            case "start":
              return <StartMsg key={`s${k}`} ev={b.ev} />;
            case "round":
              return (
                <div key={`r${b.round}`} className="tx-round" role="separator">
                  <span>{b.round === 0 ? "Round 0 · baseline, the student alone" : `Round ${b.round}`}</span>
                </div>
              );
            case "split":
              return (
                <p key={`p${b.round}${b.split}${k}`} className="tx-split">
                  {SPLIT_NAME[b.split]} <span>{SPLIT_NOTE[b.split]}</span>
                </p>
              );
            case "task": {
              const key = attemptKey(b.round, b.taskId);
              const o = isOpen(key);
              return (
                <TaskLine
                  key={key}
                  b={b}
                  attempt={key}
                  open={o}
                  running={key === running}
                  onToggle={() => toggle(key)}
                  evs={o ? attemptEvents(events, index, b.round, b.taskId, n) : null}
                />
              );
            }
            case "teacher":
              return <TeacherMsg key={`t${b.round}`} b={b} gateTotal={index.bySplit.gate.length} />;
            case "heldout":
              return (
                <p key={`h${b.ev.i}`} className="tx-note">
                  Held-out after {b.ev.round === 0 ? "the baseline" : `round ${b.ev.round}`}: <b>{b.ev.passed}/{b.ev.total}</b> passed ·{" "}
                  <b>{b.ev.avgModelCalls.toFixed(1)}</b> student calls per task
                </p>
              );
            case "end":
              return <EndMsg key={`e${b.ev.i}`} d={d} />;
          }
        })}
      </div>
    </div>
  );
}

function StartMsg({ ev }: { ev: RunStart }) {
  const what =
    ev.mode === "growth" ? "Growth run" : ev.mode === "baseline" ? "Baseline run: the student alone" : ev.mode === "manifest" ? "Grown harness run" : `${ev.mode} run`;
  return (
    <div className="tx-start">
      <p className="tx-start-what">{what}</p>
      <p className="tx-start-who">
        <span className="key key-model" aria-hidden="true" /> <span className="mono">{ev.student}</span> local
        {ev.mode === "growth" && (
          <>
            <span className="tx-dot">·</span>
            <span className="key key-teacher" aria-hidden="true" /> {prettyModel(ev.teacher)}
          </>
        )}
        <span className="tx-dot">·</span>
        {ev.online ? "online" : "offline"}
        <span className="tx-dot">·</span>
        <time className="mono">{new Date(ev.ts).toLocaleTimeString("en-GB", { hour12: false })}</time>
      </p>
    </div>
  );
}

function TaskLine({
  b, attempt, open, running, onToggle, evs,
}: {
  b: Extract<Block, { k: "task" }>;
  attempt: string;
  open: boolean;
  running: boolean;
  onToggle: () => void;
  evs: ManifestEvent[] | null;
}) {
  const e = b.end;
  const status = e ? (e.pass ? "pass" : "fail") : "running";
  return (
    <div className={`tx-task is-${status} ${open ? "is-open" : ""}`} data-attempt={attempt}>
      <button className="tx-task-line" onClick={onToggle} aria-expanded={open}>
        <span className={`tx-glyph g-${status}`} aria-label={status}>
          {status === "pass" ? <Check /> : status === "fail" ? <Cross /> : <span className="spin" />}
        </span>
        <span className="tx-task-id mono">{b.taskId}</span>
        <span className="tx-task-shape">{b.start.bugShape.replaceAll("-", " ").replaceAll("+", " + ")}</span>
        {b.blocked > 0 && <span className="tx-blocked">Warden blocked {b.blocked}</span>}
        <span className="tx-task-meta">
          {e ? (
            <>
              <b>{e.modelCalls}</b> student call{e.modelCalls === 1 ? "" : "s"}
              {e.routineCalls > 0 && (
                <>
                  {" "}
                  · <b>{e.routineCalls}</b> routine{e.routineCalls === 1 ? "" : "s"}
                </>
              )}{" "}
              · {fmtMs(e.ms)}
            </>
          ) : (
            "running…"
          )}
        </span>
        <svg className="tx-chev" viewBox="0 0 10 6" aria-hidden="true">
          <path d="M1 1l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
        </svg>
      </button>
      {open && evs && <AttemptTrace evs={evs} round={b.round} running={running} />}
    </div>
  );
}

function TeacherMsg({ b, gateTotal }: { b: Extract<Block, { k: "teacher" }>; gateTotal: number }) {
  const cost = b.calls.reduce((s, m) => s + (m.costUsd ?? 0), 0);
  const tok = b.calls.reduce((s, m) => s + m.promptTokens + m.outTokens, 0);
  return (
    <article className="tx-teacher">
      <header className="tx-teacher-h">
        <span className="tx-avatar" aria-hidden="true">
          ◆
        </span>
        <span className="tx-teacher-who">Teacher</span>
        <span className="faint">
          {prettyModel(b.calls[0]?.model)} · {b.calls.length} call{b.calls.length === 1 ? "" : "s"} · {fmtInt(tok)} tok · {fmtUsd(cost)}
        </span>
      </header>
      {b.proposal ? (
        <>
          <p className="tx-teacher-lede">
            Proposed a new routine, <span className="mono tx-routine">{b.proposal.routine}</span>
          </p>
          <p className="voice tx-rationale">“{b.proposal.rationale}”</p>
          <p className="tx-trigger">
            <span className="faint">runs when</span> <span className="mono">{b.proposal.triggerDescription}</span>
          </p>
        </>
      ) : (
        <p className="tx-teacher-lede faint">reading the failed traces…</p>
      )}
      {b.manifest && <WardenCard m={b.manifest} />}
      {b.repair && (
        <p className="tx-trigger">
          <span className="faint">re-run on the failure window</span>{" "}
          <span className="mono">{b.repair.solved.length}/{b.repair.solved.length + b.repair.unsolved.length} solved</span>
          {b.repair.solved.length > 0 && <span className="faint"> ({b.repair.solved.join(", ")})</span>}
        </p>
      )}
      {b.manifest && !b.gate && !b.step && <p className="tx-trigger faint">Checking the candidate…</p>}
      {(b.gate || b.step) && (
        <div className="tx-gate">
          {b.gate && <GateLine gate={b.gate} gateTotal={gateTotal} />}
          {b.step && b.step.outcome === "rejected" && !b.gate && (
            <p className="tx-trigger"><span className="faint">rejected at {b.step.stage}:</span> {b.step.reason}</p>
          )}
          <Stamp accepted={b.step ? b.step.outcome === "accepted" : !!b.gate?.accepted} />
        </div>
      )}
    </article>
  );
}

function EndMsg({ d }: { d: Derived }) {
  const held = d.rounds.map((r) => r.heldout).filter(Boolean) as EvalHeldout[];
  const a = held[0], z = held[held.length - 1];
  const ends = [...d.cells.values()].flatMap((row) => row.filter((c) => c?.end).map((c) => c!.end!));
  const passed = ends.filter((e) => e.pass).length;
  const calls = ends.length ? ends.reduce((s, e) => s + e.modelCalls, 0) / ends.length : 0;
  return (
    <div className="tx-end">
      <p className="tx-end-h">Run complete</p>
      {!z && ends.length > 0 && (
        <p>
          <b>{passed}/{ends.length}</b> tasks passed · <b>{calls.toFixed(1)}</b> student calls per task
        </p>
      )}
      {z && (
        <p>
          Held-out <b>{a && a !== z ? `${a.passed}/${a.total} → ` : ""}{z.passed}/{z.total}</b> · student calls per task{" "}
          <b>{a && a !== z ? `${a.avgModelCalls.toFixed(1)} → ` : ""}{z.avgModelCalls.toFixed(1)}</b>
          {d.accepted.length + d.rejected.length > 0 && (
            <>
              {" "}
              · <b>{d.accepted.length}</b> routine{d.accepted.length === 1 ? "" : "s"} kept, <b>{d.rejected.length}</b> rejected · teacher{" "}
              <b>{fmtUsd(d.teacherCost)}</b>
            </>
          )}
        </p>
      )}
    </div>
  );
}
