import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import type { Derived, RunIndex } from "../lib/derive";
import { fmtInt, fmtPct, fmtUsd } from "../lib/format";

interface Props {
  d: Derived;
  index: RunIndex;
}

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [w, setW] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setW(Math.floor(e.contentRect.width)));
    ro.observe(el);
    setW(Math.floor(el.getBoundingClientRect().width));
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

export function Results({ d, index }: Props) {
  const rounds = Array.from({ length: index.maxRound + 1 }, (_, r) => r);
  const held = rounds.map((r) => d.rounds[r]?.heldout ?? null);
  const bill = d.rounds
    .filter((rs) => rs.teacher.length)
    .map((rs) => ({
      r: rs.round,
      calls: rs.teacher.length,
      tok: rs.teacher.reduce((s, m) => s + m.promptTokens + m.outTokens, 0),
      usd: rs.teacher.reduce((s, m) => s + (m.costUsd ?? 0), 0),
      routine: rs.proposal?.routine,
    }));
  const first = held.find(Boolean);
  const last = [...held].reverse().find(Boolean);

  return (
    <section className="results" aria-labelledby="results-h">
      <h2 id="results-h" className="sr-only">
        Results
      </h2>
      <Figure
        title="Held-out pass rate"
        sub="tasks the teacher never sees"
        headline={last ? fmtPct(last.passed / last.total) : "–"}
        from={first && last && first !== last ? fmtPct(first.passed / first.total) : undefined}
      >
        <LineChart
          rounds={rounds}
          values={held.map((h) => (h ? h.passed / h.total : null))}
          tip={(r) => {
            const h = held[r];
            return h ? `${h.passed}/${h.total} passed · ${fmtPct(h.passed / h.total)}` : "not run yet";
          }}
        />
      </Figure>
      <Figure
        title="Model calls per task"
        sub="student, held-out avg · lower = more in code"
        headline={last ? last.avgModelCalls.toFixed(1) : "–"}
        from={first && last && first !== last ? first.avgModelCalls.toFixed(1) : undefined}
      >
        <ColumnChart
          rounds={rounds}
          values={held.map((h) => (h ? h.avgModelCalls : null))}
          tip={(r) => (held[r] ? `${held[r]!.avgModelCalls.toFixed(2)} calls per task` : "not run yet")}
        />
      </Figure>
      <div className="fig bill" aria-label="Teacher bill">
        <div className="fig-h">
          <h3>Teacher bill</h3>
          <p className="fig-sub">all frontier calls, ever</p>
        </div>
        <ol className="bill-rows">
          {bill.length === 0 && <li className="faint">no teacher calls yet</li>}
          {bill.map((b) => (
            <li key={b.r} title={`${b.calls} calls · ${fmtInt(b.tok)} tokens`}>
              <span className="mono">R{b.r}</span>
              <span className="bill-what mono">{b.routine ?? `${b.calls} call${b.calls === 1 ? "" : "s"}`}</span>
              <span className="mono bill-usd">{fmtUsd(b.usd)}</span>
            </li>
          ))}
        </ol>
        <div className="bill-total">
          <span>Total</span>
          <span className="mono">{fmtUsd(d.teacherCost)}</span>
        </div>
        <p className="bill-kept">
          <b>{d.accepted.length}</b> routine{d.accepted.length === 1 ? "" : "s"} kept as Agent Skills
          {d.rejected.length > 0 && (
            <>
              {" "}
              · <b>{d.rejected.length}</b> rejected
            </>
          )}
        </p>
      </div>
    </section>
  );
}

function Figure({ title, sub, headline, from, children }: { title: string; sub: string; headline: string; from?: string; children: ReactNode }) {
  return (
    <figure className="fig">
      <div className="fig-h">
        <figcaption>
          <h3>{title}</h3>
        </figcaption>
        <p className="fig-num">
          {from && (
            <span className="fig-from">
              {from}
              <span aria-hidden="true"> → </span>
              <span className="sr-only"> to </span>
            </span>
          )}
          {headline}
        </p>
      </div>
      <p className="fig-sub">{sub}</p>
      {children}
    </figure>
  );
}

const H = 140;
const PAD = { l: 34, r: 14, t: 10, b: 20 };

function useHover(rounds: number[], w: number) {
  const [hover, setHover] = useState<number | null>(null);
  const x = (r: number) => PAD.l + (rounds.length <= 1 ? 0 : (r / (rounds.length - 1)) * (w - PAD.l - PAD.r));
  const onMove = (ev: React.PointerEvent<SVGElement>) => {
    const box = (ev.currentTarget as SVGElement).getBoundingClientRect();
    const px = ev.clientX - box.left;
    let best = 0;
    for (const r of rounds) if (Math.abs(x(r) - px) < Math.abs(x(best) - px)) best = r;
    setHover(best);
  };
  return { hover, setHover, x, onMove };
}

function LineChart({ rounds, values, tip }: { rounds: number[]; values: (number | null)[]; tip: (r: number) => string }) {
  const [ref, w] = useWidth<HTMLDivElement>();
  const { hover, setHover, x, onMove } = useHover(rounds, w);
  const y = (v: number) => PAD.t + (1 - v) * (H - PAD.t - PAD.b);
  const pts = rounds.map((r) => (values[r] == null ? null : ([x(r), y(values[r]!)] as const)));
  const drawn = pts.filter(Boolean) as (readonly [number, number])[];
  const lastIdx = values.reduce<number>((acc, v, k) => (v == null ? acc : k), -1);

  return (
    <div className="chart" ref={ref}>
      {w > 0 && (
        <svg width={w} height={H} role="img" aria-label={`Held-out pass rate by round: ${rounds.map((r) => `R${r} ${values[r] == null ? "not run" : fmtPct(values[r]!)}`).join(", ")}`} onPointerMove={onMove} onPointerLeave={() => setHover(null)}>
          {[0, 0.5, 1].map((g) => (
            <g key={g}>
              <line className="gridline" x1={PAD.l} x2={w - PAD.r} y1={y(g)} y2={y(g)} />
              <text className="tick" x={PAD.l - 6} y={y(g)} dy="0.32em" textAnchor="end">
                {g * 100}%
              </text>
            </g>
          ))}
          {rounds.map((r) => (
            <text key={r} className="tick" x={x(r)} y={H - 4} textAnchor="middle">
              R{r}
            </text>
          ))}
          {drawn.length > 1 && <path className="area area-code" d={`M${drawn[0][0]},${y(0)} ${drawn.map((p) => `L${p[0]},${p[1]}`).join(" ")} L${drawn[drawn.length - 1][0]},${y(0)}Z`} />}
          {drawn.length > 1 && <path className="line line-code" d={`M${drawn.map((p) => `${p[0]},${p[1]}`).join(" L")}`} />}
          {hover !== null && <line className="crosshair" x1={x(hover)} x2={x(hover)} y1={PAD.t} y2={H - PAD.b} />}
          {pts.map((p, r) => p && <circle key={r} className={`dot dot-code ${r === lastIdx ? "dot-last" : ""}`} cx={p[0]} cy={p[1]} r={r === lastIdx ? 5 : 4} />)}
        </svg>
      )}
      {hover !== null && w > 0 && <Tip x={x(hover)} w={w} label={`Round ${hover}`} value={tip(hover)} />}
    </div>
  );
}

function ColumnChart({ rounds, values, tip }: { rounds: number[]; values: (number | null)[]; tip: (r: number) => string }) {
  const [ref, w] = useWidth<HTMLDivElement>();
  const { hover, setHover, x, onMove } = useHover(rounds, w);
  const peak = Math.max(1, ...values.map((v) => v ?? 0));
  // nice ceiling with headroom for the value label on the tallest column
  const step = peak > 10 ? 5 : peak > 4 ? 2 : 1;
  const max = Math.ceil((peak * 1.18) / step) * step;
  const y = (v: number) => PAD.t + (1 - v / max) * (H - PAD.t - PAD.b);
  const bw = Math.min(24, Math.max(10, (w - PAD.l - PAD.r) / (rounds.length * 2.4)));
  const present = values.map((v, k) => (v == null ? -1 : k)).filter((k) => k >= 0);
  const labelled = new Set([present[0], present[present.length - 1]]);

  return (
    <div className="chart" ref={ref}>
      {w > 0 && (
        <svg width={w} height={H} role="img" aria-label={`Student model calls per task by round: ${rounds.map((r) => `R${r} ${values[r] == null ? "not run" : values[r]!.toFixed(1)}`).join(", ")}`} onPointerMove={onMove} onPointerLeave={() => setHover(null)}>
          {[0, max / 2, max].map((g) => (
            <g key={g}>
              <line className="gridline" x1={PAD.l} x2={w - PAD.r} y1={y(g)} y2={y(g)} />
              <text className="tick" x={PAD.l - 6} y={y(g)} dy="0.32em" textAnchor="end">
                {Math.round(g)}
              </text>
            </g>
          ))}
          {rounds.map((r) => (
            <text key={r} className="tick" x={x(r)} y={H - 4} textAnchor="middle">
              R{r}
            </text>
          ))}
          {values.map((v, r) => {
            if (v == null) return null;
            const top = y(v), base = y(0), cx = x(r);
            const rad = Math.min(4, (base - top) / 2);
            return (
              <g key={r} className={hover === r ? "col-hover" : ""}>
                <path
                  className="col col-model"
                  d={`M${cx - bw / 2},${base} V${top + rad} Q${cx - bw / 2},${top} ${cx - bw / 2 + rad},${top} H${cx + bw / 2 - rad} Q${cx + bw / 2},${top} ${cx + bw / 2},${top + rad} V${base}Z`}
                />
                {labelled.has(r) && (
                  <text className="col-label" x={cx} y={top - 5} textAnchor="middle">
                    {v.toFixed(1)}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      )}
      {hover !== null && w > 0 && <Tip x={x(hover)} w={w} label={`Round ${hover}`} value={tip(hover)} />}
    </div>
  );
}

function Tip({ x, w, label, value }: { x: number; w: number; label: string; value: string }) {
  const left = Math.min(Math.max(x, 70), w - 70);
  return (
    <div className="tip" style={{ left }} role="presentation">
      <b>{value}</b>
      <span>{label}</span>
    </div>
  );
}
