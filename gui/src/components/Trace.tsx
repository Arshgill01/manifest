import { useMemo, useState } from "react";
import { buildTrace, type Trace, type TraceItem } from "../lib/trace";
import type { ManifestEvent, ModelCall, ToolCall, WardenBlock } from "../lib/types";
import { Check, Cross } from "./TaskBoard";
import { fmtMs, fmtInt } from "../lib/format";

/** One task attempt, drawn inline in the session transcript: who drove, then every row. */
export function AttemptTrace({ evs, round, running }: { evs: ManifestEvent[]; round: number; running: boolean }) {
  const trace = useMemo(() => buildTrace(evs, round), [evs, round]);
  const [open, setOpen] = useState<Set<number>>(new Set());
  const toggle = (k: number) =>
    setOpen((s) => {
      const x = new Set(s);
      if (x.has(k)) x.delete(k);
      else x.add(k);
      return x;
    });
  const items = trace.items.filter((it) => it.kind !== "start" && it.kind !== "end");

  return (
    <div className="attempt">
      <Driver trace={trace} />
      <div className="attempt-items">
        {items.map((it, k) => (
          <Item key={itemKey(it)} it={it} open={open} toggle={toggle} continued={it.kind === "fallback" && items[k - 1]?.kind === "fallback"} />
        ))}
        {running && (
          <div className="t-wait" aria-live="polite">
            <span className="wait-dot" /> {items.length ? "running…" : "starting…"}
          </div>
        )}
      </div>
    </div>
  );
}

function Driver({ trace }: { trace: Trace }) {
  const total = trace.codeDecisions + trace.modelCalls;
  if (!total) return null;
  return (
    <div className="driver" aria-label={`Control decisions: ${trace.codeDecisions} by code routines, ${trace.modelCalls} by the student model`}>
      <div className="driver-bar" aria-hidden="true">
        <span className="driver-code" style={{ flexGrow: trace.codeDecisions }} />
        <span className="driver-model" style={{ flexGrow: trace.modelCalls }} />
      </div>
      <span className="driver-n">
        <span className="fn-mark fn-mini" aria-hidden="true">
          ƒ
        </span>
        <b>{trace.codeDecisions}</b> code
        <span className="model-mark model-mini" aria-hidden="true">
          4B
        </span>
        <b>{trace.modelCalls}</b> student
        <span className="driver-pct">{Math.round((trace.codeDecisions / total) * 100)}% code</span>
      </span>
    </div>
  );
}

const itemKey = (it: TraceItem) =>
  it.kind === "start" || it.kind === "end" ? `${it.kind}-${it.ev.i}` : `${it.kind}-${it.key}`;

function Item({ it, open, toggle, continued }: { it: TraceItem; open: Set<number>; toggle: (k: number) => void; continued: boolean }) {
  switch (it.kind) {
    case "start":
      return (
        <div className="t-start">
          <span className="mono">task.start</span>
          <span>{it.ev.mode === "baseline" ? "baseline: the student drives a plain tool loop" : "manifest: code routines drive, the student is asked"}</span>
          <time className="mono faint">{it.ev.ts.slice(11, 19)}</time>
        </div>
      );
    case "end": {
      const e = it.ev;
      const limit = !e.pass && e.steps >= 12;
      return (
        <div className={`t-end ${e.pass ? "is-pass" : "is-fail"}`}>
          <span className="t-end-badge">
            {e.pass ? <Check /> : <Cross />}
            {e.pass ? "PASS" : "FAIL"}
          </span>
          <span className="t-end-stats mono">
            {e.steps} steps · <b>{e.modelCalls}</b> model calls · {e.routineCalls} routines · {fmtMs(e.ms)}
          </span>
          {limit && <span className="t-end-why">hit the 12-step limit</span>}
        </div>
      );
    }
    case "routine":
      return <RoutineBlock it={it} open={open} toggle={toggle} />;
    case "fallback":
      return (
        <div className={`t-fallback ${continued ? "is-continued" : ""}`}>
          <button className="t-fallback-h" onClick={() => it.ev && toggle(it.ev.i)} aria-expanded={it.ev ? open.has(it.ev.i) : undefined} disabled={!it.ev}>
            <span className="t-fallback-name mono">ask-student</span>
            <span>no routine applied · the student picks the move</span>
            <span className="t-ms mono">{it.ev ? fmtMs(it.ev.ms) : "…"}</span>
          </button>
          {it.ev && open.has(it.ev.i) && <Details ev={it.ev} />}
          <div className="t-children">
            {it.children.map((c) => (
              <Child key={c.i} ev={c} open={open} toggle={toggle} />
            ))}
          </div>
        </div>
      );
    case "step":
      return (
        <div className="t-step">
          {it.model ? (
            <ModelRow ev={it.model} open={open.has(it.model.i)} toggle={() => toggle(it.model!.i)} step={it.n} />
          ) : null}
          {it.children.length > 0 && (
            <div className="t-children">
              {it.children.map((c) => (
                <Child key={c.i} ev={c} open={open} toggle={toggle} />
              ))}
            </div>
          )}
        </div>
      );
  }
}

function RoutineBlock({ it, open, toggle }: { it: Extract<TraceItem, { kind: "routine" }>; open: Set<number>; toggle: (k: number) => void }) {
  const e = it.ev;
  const isOpen = e ? open.has(e.i) : false;
  return (
    <div className={`t-routine ${e ? "" : "is-running"} ${e?.source === "grown" ? "is-grown" : ""}`}>
      <button className="t-routine-h" onClick={() => e && toggle(e.i)} aria-expanded={e ? isOpen : undefined} disabled={!e}>
        <span className="fn-mark" aria-hidden="true">
          ƒ
        </span>
        <span className="t-routine-name">{e ? e.routine : "routine running"}</span>
        {e?.source && (
          <span className={`src-chip src-${e.source}`} title={e.source === "grown" ? "written by the teacher, kept by the gate" : "part of the tiny hand-written seed harness"}>
            {e.source}
          </span>
        )}
        <span className="t-routine-kind">code</span>
        <span className="t-ms mono">{e ? fmtMs(e.ms) : "…"}</span>
      </button>
      {e && <p className="t-routine-sum">{e.summary}</p>}
      {isOpen && e && <Details ev={e} />}
      {it.children.length > 0 && (
        <div className="t-children">
          {it.children.map((c) => (
            <Child key={c.i} ev={c} open={open} toggle={toggle} />
          ))}
        </div>
      )}
    </div>
  );
}

function Child({ ev, open, toggle }: { ev: ManifestEvent; open: Set<number>; toggle: (k: number) => void }) {
  if (ev.type === "tool.call") return <ToolRow ev={ev} open={open.has(ev.i)} toggle={() => toggle(ev.i)} />;
  if (ev.type === "model.call") return <ModelRow ev={ev} open={open.has(ev.i)} toggle={() => toggle(ev.i)} />;
  if (ev.type === "warden.block") return <BlockRow ev={ev} />;
  if (ev.type === "routine.call") return null;
  return (
    <div className="t-other mono faint">
      {ev.type}
    </div>
  );
}

function argText(args: ToolCall["args"]) {
  if (!args || typeof args !== "object") return "";
  const entries = Object.entries(args);
  if (!entries.length) return "";
  const [k, v] = entries[0];
  const s = typeof v === "string" ? v : JSON.stringify(v);
  const first = k === "path" || k === "cmd" || k === "selector" ? s : `${k}=${s}`;
  const extra = entries.length > 1 && (k === "path") && "start" in args ? `:${args.start}–${args.end}` : "";
  return first + extra;
}

function ToolRow({ ev, open, toggle }: { ev: ToolCall; open: boolean; toggle: () => void }) {
  return (
    <div className={`t-tool ${ev.ok ? "" : "is-bad"}`}>
      <button className="t-tool-line" onClick={toggle} aria-expanded={open}>
        <span className="t-tool-name">{ev.tool}</span>
        <span className="t-tool-args">({argText(ev.args)})</span>
        <span className="t-tool-arrow" aria-hidden="true">→</span>
        <span className="t-tool-sum">
          {!ev.ok && <Cross />}
          {ev.summary}
        </span>
      </button>
      {open && <Details ev={ev} />}
    </div>
  );
}

const PURPOSE: Record<string, string> = {
  step: "chose the next move",
  chat: "chose the next move",
  diagnose: "asked to diagnose",
  patch: "asked for a patch",
};

function ModelRow({ ev, open, toggle, step }: { ev: ModelCall; open: boolean; toggle: () => void; step?: number }) {
  return (
    <div className="t-model">
      <button className="t-model-line" onClick={toggle} aria-expanded={open}>
        <span className="model-mark" aria-hidden="true">
          4B
        </span>
        <span className="t-model-who">Student</span>
        <span className="t-model-what">
          {step !== undefined && <span className="t-step-n">step {step}</span>}
          {PURPOSE[ev.purpose] ?? ev.purpose}
        </span>
        <span className="t-model-tok mono">
          {fmtInt(ev.promptTokens)}→{fmtInt(ev.outTokens)} tok
        </span>
        <span className="t-ms mono">{fmtMs(ev.ms)}</span>
      </button>
      {open && (ev.prompt || ev.response) && (
        <div className="t-say">
          {ev.prompt && (
            <div className="t-say-in">
              <span className="t-say-who">saw</span>
              <pre>{ev.prompt}</pre>
            </div>
          )}
          {ev.response && (
            <div className="t-say-out">
              <span className="t-say-who">said</span>
              <pre>{ev.response}</pre>
            </div>
          )}
        </div>
      )}
      {open && <Details ev={ev} hide={["prompt", "response"]} />}
    </div>
  );
}

function BlockRow({ ev }: { ev: WardenBlock }) {
  return (
    <div className="t-block" role="note">
      <span className="t-block-stamp">BLOCKED</span>
      <span className="t-block-body">
        <span className="t-block-what">
          Warden stopped <b>{ev.skill}</b>: <span className="mono">{ev.attempted}</span>
        </span>
        <span className="t-block-why">{ev.reason}</span>
      </span>
    </div>
  );
}

const HIDE = new Set(["ts", "type", "round", "taskId", "split", "i", "t"]);
function Details({ ev, hide = [] }: { ev: ManifestEvent; hide?: string[] }) {
  const rows = Object.entries(ev).filter(([k]) => !HIDE.has(k) && !hide.includes(k));
  return (
    <dl className="details">
      <div>
        <dt>type</dt>
        <dd>{ev.type}</dd>
      </div>
      <div>
        <dt>ts</dt>
        <dd>{ev.ts}</dd>
      </div>
      {rows.map(([k, v]) => (
        <div key={k}>
          <dt>{k}</dt>
          <dd>{typeof v === "string" ? v : JSON.stringify(v, null, 1)}</dd>
        </div>
      ))}
    </dl>
  );
}

export function EmptyTrace() {
  return (
    <div className="empty-trace">
      <p className="empty-lede">Each row is one thing the harness did.</p>
      <ul className="empty-legend">
        <li>
          <span className="fn-mark">ƒ</span>
          <span>
            <b>Code.</b> A routine doing deterministic control: written by the teacher, kept only if it passed the gate.
          </span>
        </li>
        <li>
          <span className="model-mark">4B</span>
          <span>
            <b>Student.</b> A model call: the only places the small model makes a judgement.
          </span>
        </li>
        <li>
          <span className="t-block-stamp">BLOCKED</span>
          <span>
            <b>Warden.</b> An action outside the routine's permission manifest, stopped before it ran.
          </span>
        </li>
      </ul>
      <p className="faint">Press play, or click any cell on the task board.</p>
    </div>
  );
}
