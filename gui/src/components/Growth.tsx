import { useEffect, useRef } from "react";
import type { Derived, RoundState, RunIndex } from "../lib/derive";
import type { Finding, GateResult, WardenBlock, WardenManifest } from "../lib/types";
import { fmtInt, fmtUsd } from "../lib/format";

interface Props {
  d: Derived;
  index: RunIndex;
  onJumpRound: (r: number) => void;
  onPick: (taskId: string, round: number) => void;
}

export function Growth({ d, index, onJumpRound, onPick }: Props) {
  const body = useRef<HTMLOListElement>(null);
  const rounds = Array.from({ length: index.maxRound + 1 }, (_, r) => r);

  // bring the round being written into view
  useEffect(() => {
    const el = body.current?.querySelector<HTMLElement>(`[data-round="${d.round}"]`);
    el?.scrollIntoView({ block: "nearest", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  }, [d.round, d.rounds[d.round]?.gate, d.rounds[d.round]?.manifest]);

  return (
    <section className="growth" aria-labelledby="growth-h">
      <header className="panel-h">
        <h2 id="growth-h">Growth</h2>
        <p className="panel-sub">
          teacher proposes <Arrow /> Warden permits <Arrow /> gate keeps
        </p>
      </header>
      <ol className="growth-body" ref={body}>
        {rounds.map((r) => {
          const rs = d.rounds[r];
          const inFile = index.seen.has(r);
          const reached = inFile && r <= d.round && !!rs;
          return (
            <li key={r} data-round={r} className={`gr ${reached ? "" : "gr-ghost"} ${r === d.round ? "gr-now" : ""} ${reached && r > 0 && !rs?.proposal ? "gr-pending" : ""}`}>
              <button className="gr-h" onClick={() => onJumpRound(r)} title={`Replay from round ${r}`}>
                <span className="gr-r">R{r}</span>
                <span className="gr-title">
                  {!inFile ? "not in this run" : r === 0 ? "Baseline" : rs?.proposal?.routine ?? (reached ? "in progress" : "not reached yet")}
                </span>
              </button>
              {reached && (r === 0 ? <Baseline rs={rs!} /> : <RoundCard rs={rs!} index={index} d={d} />)}
              {reached && <Blocks blocks={d.blocks.filter((b) => b.round === r)} onPick={onPick} />}
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function phaseText(rs: RoundState, index: RunIndex, d: Derived) {
  if (rs.phase === "train") {
    const ids = index.bySplit.train;
    const done = ids.filter((id) => {
      const c = d.cells.get(id)?.[rs.round];
      return c && c.status !== "running";
    }).length;
    return done < ids.length ? `practising on train · ${done}/${ids.length}` : "teacher is reading the failures…";
  }
  if (rs.phase === "proposal") return "teacher is writing a routine…";
  return "…";
}

/** Warden refusals at runtime in this round: the demo's "it can't touch tests/" moment, one click from the trace. */
function Blocks({ blocks, onPick }: { blocks: WardenBlock[]; onPick: (taskId: string, round: number) => void }) {
  if (!blocks.length) return null;
  return (
    <ul className="gr-blocks">
      {blocks.map((b) => (
        <li key={b.i}>
          <span className="t-block-stamp">BLOCKED</span>
          <span className="gr-block-what">
            <b>{b.skill}</b> tried <span className="mono">{b.attempted}</span>
          </span>
          {b.taskId && (
            <button className="btn-quiet" onClick={() => onPick(b.taskId!, b.round)}>
              view trace
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}

function Baseline({ rs }: { rs: RoundState }) {
  return (
    <div className="gr-body gr-baseline">
      <p>
        No routines yet. The student drives a plain tool loop: <span className="mono">list · read · run_tests · edit · bash</span>.
      </p>
      {rs.heldout && (
        <p className="gr-held">
          held-out <b className="mono">{rs.heldout.passed}/{rs.heldout.total}</b> · {rs.heldout.avgModelCalls.toFixed(1)} model calls per task
        </p>
      )}
    </div>
  );
}

function RoundCard({ rs, index, d }: { rs: RoundState; index: RunIndex; d: Derived }) {
  const p = rs.proposal;
  const cost = rs.teacher.reduce((s, m) => s + (m.costUsd ?? 0), 0);
  const gateTotal = index.bySplit.gate.length;
  return (
    <div className="gr-body">
      {p ? (
        <>
          <p className="voice gr-rationale">“{p.rationale}”</p>
          <p className="gr-trigger">
            <span className="lbl">runs when</span> <span className="mono">{p.triggerDescription}</span>
          </p>
          <p className="gr-teacher-meta">
            <span className="key key-teacher" aria-hidden="true" /> teacher · {rs.teacher.length} call{rs.teacher.length === 1 ? "" : "s"} ·{" "}
            {fmtInt(rs.teacher.reduce((s, m) => s + m.promptTokens + m.outTokens, 0))} tok · {fmtUsd(cost)}
          </p>
        </>
      ) : (
        <p className="gr-wait">{phaseText(rs, index, d)}</p>
      )}

      {rs.manifest ? <WardenCard m={rs.manifest} /> : p ? <p className="gr-wait">Warden is scanning the routine…</p> : null}

      {rs.manifest && <Gate gate={rs.gate} rs={rs} gateTotal={gateTotal} />}
      {rs.gate && <Stamp accepted={rs.gate.accepted} key={rs.gate.i} />}
      {rs.heldout && (
        <p className="gr-held">
          held-out after this round <b className="mono">{rs.heldout.passed}/{rs.heldout.total}</b> · {rs.heldout.avgModelCalls.toFixed(1)} model calls per task
        </p>
      )}
    </div>
  );
}

function Gate({ gate, rs, gateTotal }: { gate?: GateResult; rs: RoundState; gateTotal: number }) {
  if (!gate) {
    if (rs.gateRun.running || rs.gateRun.done)
      return (
        <div className="gate gate-running">
          <span className="lbl">Gate</span>
          <span className="mono">
            running on unseen tasks · {rs.gateRun.done}/{gateTotal} done · {rs.gateRun.passed} passing
          </span>
        </div>
      );
    return null;
  }
  if (gate.gateAfter == null) {
    return (
      <div className="gate gate-skip">
        <span className="lbl">Gate</span>
        <span>not run: {gate.rejectReason ?? "rejected before the gate"}</span>
      </div>
    );
  }
  const delta = (gate.gateAfter ?? 0) - (gate.gateBefore ?? 0);
  const callsDelta =
    gate.modelCallsBefore && gate.modelCallsAfter != null ? (gate.modelCallsAfter - gate.modelCallsBefore) / gate.modelCallsBefore : null;
  return (
    <div className={`gate ${gate.accepted ? "gate-ok" : "gate-bad"}`}>
      <span className="lbl">Gate</span>
      <span className="gate-score mono">
        {gate.gateBefore ?? "–"}/{gateTotal} <Arrow /> <b>{gate.gateAfter}/{gateTotal}</b>
        {delta !== 0 && <span className={delta > 0 ? "up" : "down"}>{delta > 0 ? `+${delta}` : delta}</span>}
      </span>
      {callsDelta !== null && (
        <span className="gate-calls mono">
          model calls {gate.modelCallsBefore?.toFixed(1)} <Arrow /> {gate.modelCallsAfter?.toFixed(1)}
          <span className={callsDelta < 0 ? "up" : "down"}>
            {callsDelta < 0 ? "−" : "+"}
            {Math.abs(Math.round(callsDelta * 100))}%
          </span>
        </span>
      )}
      <span className={`gate-reg ${gate.regressions.length ? "bad" : ""}`}>
        {gate.regressions.length ? `regressions: ${gate.regressions.join(", ")}` : "no regressions"}
      </span>
      {gate.rejectReason && <span className="gate-why">{gate.rejectReason}</span>}
    </div>
  );
}

const SAFE_CMD = /^python -m pytest/;
const sevRank: Record<string, number> = { high: 0, critical: 0, medium: 1, low: 2, info: 3 };

export function WardenCard({ m }: { m: WardenManifest }) {
  const verdict = (m.verdict || "review").toLowerCase();
  const findings = (m.findings ?? []).map((f): Finding => (typeof f === "string" ? { detail: f } : f));
  findings.sort((a, b) => (sevRank[a.severity ?? "info"] ?? 3) - (sevRank[b.severity ?? "info"] ?? 3));
  const counts = findings.reduce<Record<string, number>>((acc, f) => ((acc[f.severity ?? "info"] = (acc[f.severity ?? "info"] ?? 0) + 1), acc), {});
  // beyond the default grown manifest (read **, write src/**, run pytest). Red only when Warden says dangerous.
  const outside = (glob: string, kind: "read" | "write") =>
    /^(~|\/)/.test(glob) || glob.includes("..") || (kind === "write" && !glob.startsWith("src/"));
  const tone = verdict === "dangerous" ? "chip-risk" : "chip-extra";

  return (
    <div className={`warden v-${verdict}`} role="group" aria-label={`Warden permission manifest for ${m.skill}: ${verdict}`}>
      <div className="warden-h">
        <span className="warden-name">
          <ShieldIcon /> Warden
        </span>
        <span className="warden-sub">permission manifest</span>
        <span className={`verdict verdict-${verdict}`}>{verdict}</span>
      </div>
      <dl className="perm">
        <div>
          <dt>read</dt>
          <dd>{chips(m.read, (g) => outside(g, "read"), tone)}</dd>
        </div>
        <div>
          <dt>write</dt>
          <dd>{chips(m.write, (g) => outside(g, "write"), tone)}</dd>
        </div>
        <div>
          <dt>run</dt>
          <dd>{chips(m.commands, (c) => !SAFE_CMD.test(c), tone)}</dd>
        </div>
        <div>
          <dt>network</dt>
          <dd>
            {m.network ? (
              <span className={`chip ${tone}`}>requested</span>
            ) : (
              <span className="chip chip-none">none</span>
            )}
          </dd>
        </div>
      </dl>
      {findings.length > 0 && (
        <div className="findings">
          <p className="findings-h">
            findings{" "}
            {Object.entries(counts)
              .map(([k, v]) => `${v} ${k}`)
              .join(" · ")}
          </p>
          <ul>
            {findings.slice(0, 5).map((f, k) => (
              <li key={k} className={`sev-${f.severity ?? "info"}`}>
                {f.rule && <span className="f-rule mono">{f.rule}</span>}
                <span className="f-detail">{f.detail}</span>
                {f.line != null && f.file && <span className="f-loc mono">{f.file}:{f.line}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function chips(xs: string[] | undefined, beyond: (x: string) => boolean, tone: string) {
  if (!xs?.length) return <span className="chip chip-none">none</span>;
  return xs.map((x) => (
    <span key={x} className={`chip ${beyond(x) ? tone : ""}`} title={beyond(x) ? "beyond the default grown-routine manifest" : undefined}>
      {x}
    </span>
  ));
}

function Stamp({ accepted }: { accepted: boolean }) {
  return (
    <div className={`stamp ${accepted ? "stamp-ok" : "stamp-no"}`} role="status">
      <span>{accepted ? "Accepted" : "Rejected"}</span>
    </div>
  );
}

const Arrow = () => (
  <svg className="arrow" viewBox="0 0 14 8" aria-hidden="true">
    <path d="M0 4h12M9 1l3 3-3 3" fill="none" stroke="currentColor" strokeWidth="1.3" />
  </svg>
);
const ShieldIcon = () => (
  <svg className="shield" viewBox="0 0 16 16" aria-hidden="true">
    <path d="M8 1.5l5.5 2v4.2c0 3.3-2.3 5.7-5.5 6.8-3.2-1.1-5.5-3.5-5.5-6.8V3.5z" fill="currentColor" />
  </svg>
);
