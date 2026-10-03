import type { ManifestEvent } from "./types";

const KNOWN = new Set([
  "run.start", "task.start", "task.end", "routine.call", "model.call", "tool.call", "growth.proposal",
  "warden.manifest", "warden.block", "gate.result", "eval.heldout", "run.end",
]);

/**
 * Incremental JSONL parser. Feed it chunks as they arrive (live tail); a trailing partial line is held
 * until its newline lands. Malformed or unknown lines are skipped and counted, never fatal.
 */
export class JsonlParser {
  events: ManifestEvent[] = [];
  skipped = 0;
  private rest = "";
  private t0: number | null = null;

  push(chunk: string): ManifestEvent[] {
    const text = this.rest + chunk;
    const lines = text.split("\n");
    this.rest = lines.pop() ?? "";
    const added: ManifestEvent[] = [];
    for (const raw of lines) {
      const line = raw.trim();
      if (!line) continue;
      const ev = this.parseLine(line);
      if (ev) {
        this.events.push(ev);
        added.push(ev);
      }
    }
    return added;
  }

  /** Flush a final line with no trailing newline (whole-file loads). */
  end(): ManifestEvent[] {
    const line = this.rest.trim();
    this.rest = "";
    if (!line) return [];
    const ev = this.parseLine(line);
    if (ev) this.events.push(ev);
    return ev ? [ev] : [];
  }

  private parseLine(line: string): ManifestEvent | null {
    let obj: Record<string, unknown>;
    try {
      obj = JSON.parse(line);
    } catch {
      this.skipped++;
      return null;
    }
    if (!obj || typeof obj !== "object" || !KNOWN.has(obj.type as string)) {
      this.skipped++;
      return null;
    }
    const ms = Date.parse(String(obj.ts));
    const prev = this.events.length ? this.events[this.events.length - 1].t : 0;
    if (this.t0 === null && Number.isFinite(ms)) this.t0 = ms;
    // keep time monotonic even if a writer's clock stutters or ts is missing
    const t = Number.isFinite(ms) && this.t0 !== null ? Math.max(prev, ms - this.t0) : prev;
    return {
      ...obj,
      round: typeof obj.round === "number" ? obj.round : 0,
      taskId: (obj.taskId as string | null) ?? null,
      split: (obj.split as ManifestEvent["split"]) ?? null,
      i: this.events.length,
      t,
    } as ManifestEvent;
  }
}

export function parseAll(text: string) {
  const p = new JsonlParser();
  p.push(text);
  p.end();
  return p;
}
