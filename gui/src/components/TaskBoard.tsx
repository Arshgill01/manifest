import type { Cell, Derived, RunIndex } from "../lib/derive";
import type { Split } from "../lib/types";

interface Props {
  index: RunIndex;
  d: Derived;
  focus: { taskId: string; round: number } | null;
  onPick: (taskId: string, round: number) => void;
}

const SPLIT_COPY: Record<Split, { title: string; note: string }> = {
  train: { title: "Train", note: "practice tasks · failures go to the teacher" },
  gate: { title: "Gate", note: "unseen · decides keep or drop" },
  heldout: { title: "Held-out", note: "never seen by the teacher" },
};

export function TaskBoard({ index, d, focus, onPick }: Props) {
  const rounds = Array.from({ length: index.maxRound + 1 }, (_, r) => r);
  const seenDomains = new Set([...index.bySplit.train, ...index.bySplit.gate].map((id) => index.tasks.get(id)?.domain));

  return (
    <section className="panel board" aria-labelledby="board-h">
      <header className="panel-h board-h">
        <h2 id="board-h">Task board</h2>
        <div className="board-cols" aria-hidden="true" style={{ ["--cols" as string]: rounds.length }}>
          {rounds.map((r) => (
            <span key={r} className={r === d.round ? "now" : ""}>
              R{r}
            </span>
          ))}
        </div>
      </header>

      <div className="board-body">
        {index.tasks.size === 0 && <p className="empty-note">Tasks appear here as the run starts them.</p>}
        {(["train", "gate", "heldout"] as const).map((split) => {
          const ids = index.bySplit[split];
          if (!ids.length) return null;
          const score = scoreAt(ids, d, d.round);
          return (
            <div key={split} className={`split split-${split}`}>
              <div className="split-h">
                <span className="split-title">
                  {split === "heldout" && <SealIcon />}
                  {SPLIT_COPY[split].title}
                  <span className="split-count">{ids.length}</span>
                </span>
                <span className="split-note">{SPLIT_COPY[split].note}</span>
                <span className="split-score" title={`Round ${d.round}: ${score.passed} of ${ids.length} passing`}>
                  {score.ran ? (
                    <>
                      <b>{score.passed}</b>/{ids.length}
                    </>
                  ) : (
                    <span className="faint">–/{ids.length}</span>
                  )}
                </span>
              </div>
              <ul className="rows" role="list">
                {ids.map((id) => {
                  const t = index.tasks.get(id)!;
                  const row = d.cells.get(id) ?? [];
                  return (
                    <li key={id} className={`row ${focus?.taskId === id ? "focused" : ""}`}>
                      <span className="task-name" title={`${id} · ${t.bugShape}`}>
                        <span className="task-domain">{t.domain}</span>
                        <span className="task-num">{t.num}</span>
                        {split === "heldout" && !seenDomains.has(t.domain) && <span className="tag-new">new domain</span>}
                      </span>
                      <span className="pips" style={{ ["--cols" as string]: rounds.length }}>
                        {rounds.map((r) => (
                          <Pip
                            key={r}
                            cell={row[r]}
                            now={r === d.round}
                            focused={focus?.taskId === id && focus.round === r}
                            label={`${id}, round ${r}`}
                            onClick={() => onPick(id, r)}
                          />
                        ))}
                      </span>
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function scoreAt(ids: string[], d: Derived, round: number) {
  // the score for the newest round this split has any result in, up to `round`
  for (let r = round; r >= 0; r--) {
    let ran = 0, passed = 0;
    for (const id of ids) {
      const c = d.cells.get(id)?.[r];
      if (c && c.status !== "running") ran++;
      if (c?.status === "pass") passed++;
    }
    if (ran || ids.some((id) => d.cells.get(id)?.[r])) return { ran: true, passed, round: r };
  }
  return { ran: false, passed: 0, round };
}

function Pip({ cell, now, focused, label, onClick }: { cell?: Cell; now: boolean; focused: boolean; label: string; onClick: () => void }) {
  const status = cell?.status ?? "none";
  const words = { pass: "passed", fail: "failed", running: "running", none: "not run" }[status];
  return (
    <button
      className={`pip pip-${status} ${now ? "pip-now" : ""} ${focused ? "pip-focus" : ""}`}
      aria-label={`${label}: ${words}`}
      aria-pressed={focused}
      disabled={!cell}
      onClick={onClick}
      title={cell?.end ? `${label}: ${words} · ${cell.end.modelCalls} model calls · ${cell.end.steps} steps` : `${label}: ${words}`}
    >
      {status === "pass" && <Check />}
      {status === "fail" && <Cross />}
    </button>
  );
}

export const Check = () => (
  <svg viewBox="0 0 12 12" aria-hidden="true">
    <path d="M2.5 6.2l2.3 2.3 4.7-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
export const Cross = () => (
  <svg viewBox="0 0 12 12" aria-hidden="true">
    <path d="M3.2 3.2l5.6 5.6M8.8 3.2l-5.6 5.6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
  </svg>
);
const SealIcon = () => (
  <svg className="seal" viewBox="0 0 16 16" aria-hidden="true">
    <rect x="3" y="7" width="10" height="7" rx="1.5" fill="currentColor" />
    <path d="M5.5 7V5a2.5 2.5 0 015 0v2" fill="none" stroke="currentColor" strokeWidth="1.6" />
  </svg>
);
