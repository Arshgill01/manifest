"""Teacher spend control: DeepSeek prices with the peak/off-peak schedule, a persistent ledger, hard caps.

    clock = PriceSchedule.from_env()
    clock.is_peak(now)                    # Mon–Fri 01:00–04:00 and 06:00–10:00 UTC
    clock.prices(now)                     # Prices for that moment (peak = 2x off-peak)
    ledger = Ledger()                     # .manifest/teacher-ledger.jsonl (committed, append-only)
    ledger.total()                        # all-time USD
    guard = Budget(run_cap=0.75)          # raises TeacherBudgetExceeded before a call that can't be afforded

Defaults are DeepSeek's published rates for `deepseek-flash` (V4.1 Flash) as of 2026-10:
off-peak $0.15 / 1M input (cache miss), $0.003 cache hit, $0.60 output; peak exactly double.
Override with TEACHER_PRICE_IN_PER_M / _CACHED_PER_M / _OUT_PER_M (off-peak values) in .env.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / ".manifest" / "teacher-ledger.jsonl"
PEAK_WINDOWS_UTC = ((1, 4), (6, 10))   # [start, end) hours, Monday–Friday
SMART_WAIT_S = 3600                    # "smart" hours: wait for off-peak only when it is at most this far away


class TeacherBudgetExceeded(RuntimeError):
    """The next teacher call could push spend past a cap; the caller should checkpoint and stop."""


@dataclass(frozen=True)
class Prices:
    """USD per 1M tokens."""

    input_miss: float = 0.15
    input_hit: float = 0.003
    output: float = 0.60

    def cost(self, prompt_tokens: int, out_tokens: int, cache_hit_tokens: int = 0) -> float:
        miss = max(prompt_tokens - cache_hit_tokens, 0)
        return (miss * self.input_miss + cache_hit_tokens * self.input_hit + out_tokens * self.output) / 1e6

    def scaled(self, k: float) -> "Prices":
        return Prices(self.input_miss * k, self.input_hit * k, self.output * k)


def is_peak(now: datetime | None = None) -> bool:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return now.weekday() < 5 and any(a <= now.hour < b for a, b in PEAK_WINDOWS_UTC)


def next_offpeak(now: datetime | None = None) -> datetime:
    t = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(second=0, microsecond=0)
    while is_peak(t):
        t += timedelta(minutes=1)
    return t


@dataclass(frozen=True)
class PriceSchedule:
    offpeak: Prices = Prices()
    peak_multiplier: float = 2.0

    @classmethod
    def from_env(cls) -> "PriceSchedule":
        def f(key: str, default: float) -> float:
            v = os.environ.get(key)
            return float(v) if v else default

        d = Prices()
        return cls(Prices(f("TEACHER_PRICE_IN_PER_M", d.input_miss), f("TEACHER_PRICE_CACHED_PER_M", d.input_hit),
                          f("TEACHER_PRICE_OUT_PER_M", d.output)), f("TEACHER_PEAK_MULTIPLIER", 2.0))

    def prices(self, now: datetime | None = None) -> Prices:
        return self.offpeak.scaled(self.peak_multiplier) if is_peak(now) else self.offpeak


class Ledger:
    def __init__(self, path: Path = LEDGER):
        self.path = Path(path)

    def append(self, **row) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **row}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")

    def rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(l) for l in self.path.read_text(encoding="utf-8").splitlines() if l.strip()]

    def total(self) -> float:
        return round(sum(float(r.get("costUsd", 0)) for r in self.rows()), 6)


class Budget:
    """Caps: all-time (ledger) and per run. `estimate_usd` is a conservative guess for the next call
    (default: 40k fresh prompt tokens + 20k output tokens at peak prices = ~$0.072)."""

    def __init__(self, *, run_cap: float | None = None, total_cap: float | None = None,
                 ledger: Ledger | None = None, schedule: PriceSchedule | None = None,
                 hours: str = "any", sleep=time.sleep):
        self.ledger = ledger or Ledger()
        self.schedule = schedule or PriceSchedule.from_env()
        env_total = os.environ.get("TEACHER_BUDGET_USD")
        self.total_cap = total_cap if total_cap is not None else (float(env_total) if env_total else 2.0)
        self.run_cap = run_cap
        self.run_spent = 0.0
        self.hours = hours  # "any" | "offpeak" (always wait) | "smart" (wait only if off-peak is ≤ SMART_WAIT away)
        self.sleep = sleep

    def estimate_usd(self, prompt_tokens: int = 40_000, out_tokens: int = 20_000) -> float:
        return self.schedule.offpeak.scaled(self.schedule.peak_multiplier).cost(prompt_tokens, out_tokens)

    def before_call(self, estimate: float | None = None) -> None:
        until = next_offpeak() if self.hours in ("offpeak", "smart") and is_peak() else None
        wait = max(0.0, (until - datetime.now(timezone.utc)).total_seconds()) if until else 0.0
        if until and (self.hours == "offpeak" or wait <= SMART_WAIT_S):
            print(f"[teacher] peak hours; waiting {wait / 60:.0f} min for off-peak ({until:%H:%M} UTC)", flush=True)
            self.sleep(wait + 5)
        est = self.estimate_usd() if estimate is None else estimate
        total = self.ledger.total()
        if total + est > self.total_cap:
            raise TeacherBudgetExceeded(f"all-time teacher spend ${total:.4f} + next call ≤${est:.3f} would exceed "
                                        f"TEACHER_BUDGET_USD=${self.total_cap:.2f}")
        if self.run_cap is not None and self.run_spent + est > self.run_cap:
            raise TeacherBudgetExceeded(f"run teacher spend ${self.run_spent:.4f} + next call ≤${est:.3f} would "
                                        f"exceed the run cap ${self.run_cap:.2f}")

    def record(self, *, cost: float, **row) -> None:
        self.run_spent += cost
        self.ledger.append(costUsd=round(cost, 6), **row)
