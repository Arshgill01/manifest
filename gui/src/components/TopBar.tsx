import { useEffect, useRef, useState } from "react";
import { prettyModel } from "../lib/derive";
import type { RunStart } from "../lib/types";
import type { Mode } from "../hooks/useRunSource";

interface Props {
  run: RunStart | null;
  round: number;
  maxRound: number;
  netOnline: boolean;
  mode: Mode;
}

export function TopBar({ run, round, maxRound, netOnline, mode }: Props) {
  const runOffline = run?.online === false;
  const offline = !netOnline || runOffline;
  const why = !netOnline
    ? "No network. Student + grown harness run on this laptop."
    : runOffline
      ? "Run started offline. No teacher calls possible."
      : mode === "live"
        ? "Teacher reachable. Only synthetic practice tasks are sent."
        : "Recorded with the teacher online";

  // a short "stamp" when the badge flips, so the moment registers from the back of the room
  const [flip, setFlip] = useState(false);
  const prev = useRef(offline);
  useEffect(() => {
    if (prev.current !== offline) {
      prev.current = offline;
      setFlip(true);
      const t = setTimeout(() => setFlip(false), 700);
      return () => clearTimeout(t);
    }
  }, [offline]);

  const rounds = Array.from({ length: maxRound + 1 }, (_, r) => r);

  return (
    <header className="topbar">
      <div className="brand">
        <svg className="brand-mark" viewBox="0 0 32 32" aria-hidden="true">
          <rect width="32" height="32" rx="6" />
          <path d="M8 23V9l8 8 8-8v14" />
        </svg>
        <div className="brand-text">
          <span className="brand-name">Manifest</span>
          <span className="brand-sub">a harness that grows itself</span>
        </div>
      </div>

      <dl className="actors">
        <div className="actor actor-student">
          <dt>
            <span className="key key-model" aria-hidden="true" />
            Student
          </dt>
          <dd>
            <span className="actor-model">{run?.student ?? "qwen3.5:4b"}</span>
            <span className="actor-where">local · Ollama</span>
          </dd>
        </div>
        <div className="actor actor-teacher">
          <dt>
            <span className="key key-teacher" aria-hidden="true" />
            Teacher
          </dt>
          <dd>
            <span className="actor-model">{prettyModel(run?.teacher ?? "deepseek")}</span>
            <span className="actor-where">open weights · growth only</span>
          </dd>
        </div>
      </dl>

      <div className="round-ind" aria-label={`Round ${round} of ${maxRound}`}>
        <span className="round-label">Round</span>
        <span className="round-num">
          {round}
          <span className="round-of">/{maxRound}</span>
        </span>
        <span className="round-pips" aria-hidden="true">
          {rounds.map((r) => (
            <i key={r} className={r < round ? "done" : r === round ? "now" : ""} />
          ))}
        </span>
      </div>

      <div
        className={`net ${offline ? "net-off" : "net-on"} ${flip ? "net-flip" : ""}`}
        role="status"
        aria-live="polite"
      >
        <span className="net-word">{offline ? "OFFLINE" : "ONLINE"}</span>
        <span className="net-why">{why}</span>
      </div>
    </header>
  );
}
