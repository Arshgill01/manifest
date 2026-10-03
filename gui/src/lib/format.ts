const nf = new Intl.NumberFormat("en-US");

export const fmtInt = (n: number | null | undefined) => (n == null ? "–" : nf.format(Math.round(n)));

export function fmtMs(ms: number | null | undefined) {
  if (ms == null) return "–";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)} s`;
  const m = Math.floor(ms / 60_000);
  const s = Math.round((ms % 60_000) / 1000);
  return `${m}m ${String(s).padStart(2, "0")}s`;
}

export function fmtUsd(x: number) {
  if (x === 0) return "$0.00";
  if (x < 0.01) return `$${x.toFixed(4)}`;
  return `$${x.toFixed(2)}`;
}

export const fmtPct = (x: number) => `${Math.round(x * 100)}%`;

/** Local wall-clock HH:MM:SS for an ISO timestamp. */
export function fmtClock(ts: string | undefined) {
  if (!ts) return "--:--:--";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts.slice(11, 19);
  return d.toLocaleTimeString("en-GB", { hour12: false });
}
