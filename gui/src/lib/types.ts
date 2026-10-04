// CONTRACT.md part 1, as TypeScript. Extra fields are allowed and ignored unless named here.

export type Split = "train" | "gate" | "heldout";

interface Base {
  ts: string;
  round: number;
  taskId: string | null;
  split: Split | null;
  /** index in the file; added by the parser */
  i: number;
  /** ms since run start; added by the parser */
  t: number;
}

export interface RunStart extends Base { type: "run.start"; mode: string; student: string; teacher: string; online: boolean; fixture?: boolean; rounds?: number }
export interface TaskStart extends Base { type: "task.start"; domain: string; bugShape: string; mode?: string }
export interface TaskEnd extends Base { type: "task.end"; pass: boolean; steps: number; modelCalls: number; routineCalls: number; ms: number }
export interface RoutineCall extends Base { type: "routine.call"; routine: string; summary: string; ms: number; source?: "seed" | "grown" }
export interface ModelCall extends Base {
  type: "model.call"; model: string; role: "student" | "teacher"; purpose: string;
  promptTokens: number; outTokens: number; ms: number; cacheHitTokens?: number; costUsd?: number;
  /** optional (newer runs): newest message the model saw, and its reply + tool calls */
  prompt?: string; response?: string;
}
export interface ToolCall extends Base { type: "tool.call"; tool: string; args: Record<string, unknown> | null; ok: boolean; summary: string }
export interface GrowthProposal extends Base { type: "growth.proposal"; routine: string; rationale: string; triggerDescription: string; skillPath: string; status?: string }
export interface Finding { rule?: string; severity?: string; file?: string; line?: number | null; detail?: string }
export interface WardenManifest extends Base {
  type: "warden.manifest"; skill: string; read: string[]; write: string[]; commands: string[];
  network: boolean; findings: (Finding | string)[]; verdict: string;
}
export interface WardenBlock extends Base { type: "warden.block"; skill: string; attempted: string; reason: string }
export interface GateResult extends Base {
  type: "gate.result"; routine: string; accepted: boolean; gateBefore: number | null; gateAfter: number | null;
  regressions: string[]; modelCallsBefore: number | null; modelCallsAfter: number | null; rejectReason?: string;
}
export interface EvalHeldout extends Base { type: "eval.heldout"; passed: number; total: number; avgModelCalls: number }
export interface RunEnd extends Base {
  type: "run.end";
  summary: unknown;
}

/** v2 growth (paper failure window): one per optimisation step, whatever stage decided it. */
export interface GrowthStep extends Base {
  type: "growth.step"; step: number; outcome: "accepted" | "rejected"; stage: string; reason: string; changes: string[]; harness: number;
}
/** v2: the candidate re-run on the failure window. */
export interface GrowthRepair extends Base {
  type: "growth.repair"; step: number; candidate: string[]; solved: string[]; unsolved: string[]; threshold: number; ok: boolean;
}

export type ManifestEvent =
  | RunStart | TaskStart | TaskEnd | RoutineCall | ModelCall | ToolCall | GrowthProposal
  | WardenManifest | WardenBlock | GateResult | EvalHeldout | RunEnd | GrowthStep | GrowthRepair;

export type EventType = ManifestEvent["type"];
