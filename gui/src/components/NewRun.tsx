import { useMemo, useRef, useState } from "react";
import type { LaunchInfo, LaunchRequest, Profiles } from "../hooks/useLauncher";
import { Chevron } from "./Composer";

type What = "manifest" | "baseline" | "grow" | "rehearsal" | "oracle";
type SplitName = "heldout" | "train" | "gate";

const WHAT: Record<What, { label: string; hint: string }> = {
  manifest: { label: "Grown harness", hint: "code routines drive; the student only diagnoses and patches" },
  baseline: { label: "Student alone", hint: "the 4B model drives a plain tool loop (round-0 behaviour)" },
  grow: { label: "Growth run", hint: "teacher writes routines, Warden + gate keep or drop them · needs the teacher online" },
  rehearsal: { label: "Growth rehearsal", hint: "the whole growth loop with a canned teacher and stub runner · no models" },
  oracle: { label: "Runner self-test", hint: "apply each reference fix and judge it · no models" },
};
const SPLITS: { id: SplitName; label: string }[] = [
  { id: "heldout", label: "Held-out" },
  { id: "train", label: "Train" },
  { id: "gate", label: "Gate" },
];

interface Props {
  available: boolean;
  profiles: Profiles | null;
  busy: string | null;
  active: LaunchInfo | null;
  error: string | null;
  online: boolean;
  onLaunch: (req: LaunchRequest) => void;
  onOpenActive: () => void;
}

/** "What should the student do?" A real composer: it starts the harness CLIs, then the session tails the log. */
export function NewRun({ available, profiles, busy, active, error, online, onLaunch, onOpenActive }: Props) {
  const [what, setWhat] = useState<What>("manifest");
  const [split, setSplit] = useState<SplitName>("heldout");
  // live-demo defaults: grown harness on the demo profile's held-out tasks (falls back to core)
  const [profileChoice, setProfile] = useState<string | null>(null);
  const profile = profileChoice ?? (profiles?.demo ? "demo" : "core");
  const [rounds, setRounds] = useState(3);
  const [text, setText] = useState("");
  const input = useRef<HTMLTextAreaElement>(null);

  const isGrow = what === "grow" || what === "rehearsal";
  const pool = useMemo(() => {
    const p = profiles?.[profile];
    return p ? [...p.heldout, ...p.train, ...p.gate] : [];
  }, [profiles, profile]);
  const splitsHere = SPLITS.filter((s) => (profiles?.[profile]?.[s.id]?.length ?? 1) > 0);
  const effSplit = splitsHere.some((s) => s.id === split) ? split : (splitsHere[0]?.id ?? split);
  const inSplit = profiles?.[profile]?.[effSplit] ?? [];
  const typed = text.split(/[\s,]+/).filter(Boolean);
  const unknown = typed.filter((t) => !pool.includes(t));
  const tasks = typed.filter((t) => pool.includes(t));
  const n = isGrow ? null : tasks.length || inSplit.length;

  const req: LaunchRequest = isGrow
    ? { kind: "grow", profile, rounds, dry: what === "rehearsal" }
    : { kind: "eval", mode: what as LaunchRequest["mode"], split: effSplit, profile, tasks };
  const cmd = isGrow
    ? `python -m growth.grow --rounds ${rounds} --profile ${profile}${what === "rehearsal" ? " --fake-teacher --stub-runner" : ""}`
    : `python -m growth.eval --split ${effSplit} --mode ${what} --profile ${profile}${what === "manifest" ? " --round 2" : what === "baseline" ? " --round 0 --force" : ""} --max-seconds 240${tasks.length ? ` --tasks ${tasks.join(",")}` : ""}`;

  const needsTeacher = what === "grow";
  const needsModel = what === "manifest" || what === "baseline" || what === "grow";
  const blockedBy = !available
    ? "Starting runs needs the local server (npm run dev / npm run serve). This page is a viewer only."
    : active
      ? null
      : busy && needsModel
        ? `${busy} is still running. One model run at a time on 8 GB; this unlocks when it finishes. (Self-test and rehearsal still work.)`
        : needsTeacher && !online
          ? "A growth run needs the teacher, and you're offline. Grown harness and Student alone run fully offline."
          : unknown.length
            ? `Not a task in the ${profile} profile: ${unknown.join(", ")}`
            : null;

  const go = () => {
    if (!blockedBy && !active) onLaunch(req);
  };

  return (
    <div className="newrun">
      <div className="nr-hero">
        <svg className="brand-mark nr-mark" viewBox="0 0 32 32" aria-hidden="true">
          <rect width="32" height="32" rx="7" />
          <path d="M8 23V9l8 8 8-8v14" />
        </svg>
        <h1>What should the student work on?</h1>
      </div>

      <div className="nr-chips">
        <label className="chip-select">
          <span className="sr-only">What to run</span>
          <select value={what} onChange={(e) => setWhat(e.target.value as What)}>
            {(Object.keys(WHAT) as What[]).map((w) => (
              <option key={w} value={w}>
                {WHAT[w].label}
              </option>
            ))}
          </select>
          <Chevron />
        </label>
        {!isGrow && (
          <label className="chip-select">
            <span className="sr-only">Split</span>
            <select value={effSplit} onChange={(e) => setSplit(e.target.value as SplitName)}>
              {splitsHere.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label} split
                </option>
              ))}
            </select>
            <Chevron />
          </label>
        )}
        {isGrow && (
          <label className="chip-select">
            <span className="sr-only">Rounds</span>
            <select value={rounds} onChange={(e) => setRounds(Number(e.target.value))}>
              {[1, 2, 3, 4].map((r) => (
                <option key={r} value={r}>
                  {r} round{r === 1 ? "" : "s"}
                </option>
              ))}
            </select>
            <Chevron />
          </label>
        )}
        <label className="chip-select">
          <span className="sr-only">Task profile</span>
          <select value={profile} onChange={(e) => setProfile(e.target.value)}>
            {Object.entries(profiles ?? { core: null }).map(([name, p]) => (
              <option key={name} value={name}>
                {name} tasks{p ? ` (${p.train.length} · ${p.gate.length} · ${p.heldout.length})` : ""}
              </option>
            ))}
          </select>
          <Chevron />
        </label>
      </div>

      <form
        className="nr-box"
        onSubmit={(e) => {
          e.preventDefault();
          go();
        }}
      >
        <textarea
          ref={input}
          rows={2}
          value={text}
          disabled={isGrow}
          placeholder={isGrow ? WHAT[what].hint : `Task ids, or leave empty for all ${inSplit.length || ""} ${SPLITS.find((s) => s.id === effSplit)?.label.toLowerCase()} tasks. e.g. ${inSplit[0] ?? "ledgerly-07"}`}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              go();
            }
          }}
          aria-label="Task ids"
        />
        <div className="nr-row">
          <span className="nr-cmd mono" title="exactly what will run, from the repo root">
            {cmd}
          </span>
          <span className="nr-model">
            <span className="key key-model" aria-hidden="true" /> qwen3.5:4b
            {needsTeacher && (
              <>
                {" "}
                + <span className="key key-teacher" aria-hidden="true" /> teacher
              </>
            )}
          </span>
          <button className="send" type="submit" disabled={!!blockedBy || !!active} aria-label="Start run" title={blockedBy ?? `Start · ${n ?? rounds + " rounds"}`}>
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path d="M8 13V3M3.5 7.5L8 3l4.5 4.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        </div>
      </form>

      <p className="nr-hint">
        {active ? (
          <>
            A run is going: <span className="mono">{active.cmd.replace(/^uv run /, "")}</span>{" "}
            <button className="btn-quiet" onClick={onOpenActive}>
              open it
            </button>
          </>
        ) : (
          error ?? blockedBy ?? WHAT[what].hint
        )}
      </p>

      {!isGrow && inSplit.length > 0 && (
        <div className="nr-tasks" aria-label="Tasks in this split">
          {inSplit.map((t) => (
            <button
              key={t}
              className={`nr-task ${tasks.includes(t) ? "on" : ""}`}
              onClick={() => {
                setText(() => (tasks.includes(t) ? typed.filter((y) => y !== t).join(" ") : [...typed, t].join(" ")));
                input.current?.focus();
              }}
            >
              {t}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
