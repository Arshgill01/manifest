import { useCallback, useEffect, useState } from "react";

export interface LaunchInfo {
  id: string;
  cmd: string;
  pid: number;
  startedAt: number;
  out: string[];
  exit: { code: number | null; signal: string | null; at: number } | null;
}
export interface LaunchRequest {
  kind: "eval" | "grow";
  mode?: "baseline" | "manifest" | "oracle";
  split?: "train" | "gate" | "heldout";
  tasks?: string[];
  profile: string;
  rounds?: number;
  dry?: boolean;
}
export type Profiles = Record<string, { train: string[]; gate: string[]; heldout: string[] }>;

/** Talks to gui/server/launch.ts. `available` is false on a static host (no server = viewer only). */
export function useLauncher() {
  const [available, setAvailable] = useState(false);
  const [active, setActive] = useState<LaunchInfo | null>(null);
  const [last, setLast] = useState<LaunchInfo | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [profiles, setProfiles] = useState<Profiles | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const r = await fetch("/api/launch");
      if (!r.ok || !r.headers.get("content-type")?.includes("json")) throw new Error();
      const d = await r.json();
      setAvailable(true);
      setActive(d.active && !d.active.exit ? d.active : null);
      setLast(d.active?.exit ? d.active : d.last);
      setBusy(d.busy);
    } catch {
      setAvailable(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    fetch("/api/tasks")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d && setProfiles(d.profiles))
      .catch(() => {});
    const t = setInterval(refresh, 1500);
    return () => clearInterval(t);
  }, [refresh]);

  const launch = useCallback(
    async (req: LaunchRequest) => {
      setError(null);
      const r = await fetch("/api/launch", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(req) });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) {
        setError(d.error ?? `couldn't start (${r.status})`);
        return null;
      }
      setActive(d);
      return d as LaunchInfo;
    },
    [],
  );
  const stop = useCallback(async () => {
    await fetch("/api/launch/stop", { method: "POST" });
    refresh();
  }, [refresh]);

  return { available, active, last, busy, profiles, error, launch, stop, setError };
}
