"""v2 growth: the paper's failure-guided harness growth (Algorithm 1), mapped to routines. SPEC §5.

    uv run python -m growth.stream --profile full                          # real run (Ollama + DeepSeek)
    uv run python -m growth.stream --resume <run-id>                       # continue after a crash/stop
    uv run python -m growth.stream --fake-teacher --stub-runner            # rehearsal: no models at all
    uv run python -m growth.stream --ablate window-1|no-gate|no-fn-trace   # ablations (SPEC §5.6)

Loop: run the current harness h over a stream of train tasks until the failure window W holds K
failures; the teacher proposes one change set from W's function-level traces; the candidate is
validated (edit budget, scope, no deletions, specificity, Warden), re-run on W (needs ≥ Q repairs) and
gated (gate success must not drop below the checkpoint's). Accept → h moves on and W keeps the still-
unsolved tasks with fresh traces; reject → rollback (h unchanged), attempts++ and tasks retire at R_max.
Held-out is evaluated once, on the final harness h*.

On disk:
  harnesses/<run-id>/h<k>.json                 registry of every accepted harness version (h0 = seeds)
  harnesses/<run-id>/routines/<name>/v<j>/     routine.py, manifest.json, SKILL.md, proposal.json
  harnesses/<run-id>/registry.json             final h*
  .manifest/growth/<run-id>/checkpoint.json    resumable state (written after every task)
  .manifest/growth/<run-id>/candidates/s<t>/   staged candidates (accepted or not)
  .manifest/runs/<run-id>.jsonl                the one event log (appended on resume)
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from growth import stubs
from growth.gate import as_split_result, passing_ids
from growth.grow import (SEED_REGISTRY, LeakError, api_reference, assert_no_leak, banned_terms as leak_terms_for,
                         load_splits, registry_for_teacher, registry_key, rel, render_skill_md, resolve, with_routine)
from growth.traces import window_entry
from growth.validate import Verdict, banned_terms, check_changeset
from harness.budget import Budget, TeacherBudgetExceeded
from harness.env import host_info, load_env
from harness.log import ROOT, RUNS_DIR, EventLog, new_run_id
from harness.teacher import FakeTeacher, Teacher, TeacherError, TeacherOutputError

GROWTH_ROOT = ROOT / ".manifest" / "growth"
HARNESSES = ROOT / "harnesses"
ABLATIONS = ("no-gate", "window-1", "no-fn-trace")


def say(msg: str) -> None:
    print(f"[stream {time.strftime('%H:%M:%S')}] {msg}", flush=True)


@dataclass
class StreamConfig:
    profile: str = "full"
    k: int = 4                 # window capacity      [paper: 8 BrowseComp-Plus / 4 WebArena]
    r_max: int = 3             # repair attempts      [paper: 5]
    q: int = 1                 # repair threshold     [paper: Q]
    budget: int = 10           # edit budget L        [paper: 10]
    max_opt_steps: int = 12    # optimisation steps (teacher calls that produced a candidate)
    max_hours: float = 72.0
    teacher_budget: float = 0.75
    teacher_hours: str = "smart"  # any | offpeak | smart
    ablate: list[str] = field(default_factory=list)
    fake_teacher: bool = False
    stub_runner: bool = False
    heldout_final: bool = True
    max_steps: int = 12
    max_seconds: int = 1800
    executor: str = "auto"
    train_ids: list[str] | None = None
    gate_ids: list[str] | None = None
    heldout_ids: list[str] | None = None
    heldout_profile: str | None = None   # evaluate h* on another profile's held-out (e.g. v2: 26 tasks)
    label: str = "stream"

    @property
    def scratch(self) -> bool:
        return self.fake_teacher or self.stub_runner


class Stream:
    def __init__(self, cfg: StreamConfig, *, teacher: Any = None, run_split: Callable[..., Any] | None = None,
                 warden: tuple[Callable, Callable] | None = None, resume: str | None = None, root: Path | None = None):
        self.cfg = cfg
        if "window-1" in cfg.ablate:
            cfg.k = 1
        self.fn_level = "no-fn-trace" not in cfg.ablate
        self.run_id = resume or new_run_id(cfg.label + ("-ablate-" + "-".join(cfg.ablate) if cfg.ablate else "")
                                           + ("-dryrun" if cfg.scratch else ""))
        base = root or (ROOT / ".manifest" / "work" / f"stream-{self.run_id}" if cfg.scratch else None)
        self.gdir = (base / "growth" if base else GROWTH_ROOT / self.run_id)
        self.hdir = (base / "harnesses" if base else HARNESSES / self.run_id)
        log_path = (base / "run.jsonl") if base else RUNS_DIR / f"{self.run_id}.jsonl"
        self.log = EventLog(log_path)
        self.ckpt_path = self.gdir / "checkpoint.json"

        splits = load_splits(cfg.stub_runner, cfg.profile) if not cfg.stub_runner else dict(stubs.STUB_SPLITS)
        self.train = cfg.train_ids or list(splits["train"])
        self.gate_ids = cfg.gate_ids or list(splits["gate"])
        self.heldout = cfg.heldout_ids or list(splits["heldout"])
        if cfg.heldout_profile and not cfg.heldout_ids:
            self.heldout = list(load_splits(False, cfg.heldout_profile)["heldout"])
        self.leak_terms = leak_terms_for(splits)
        if set(self.train) & set(splits.get("heldout", []) + splits.get("heldoutAll", [])):
            raise LeakError("a held-out task was passed as a train task")
        self.banned = banned_terms(self.train + self.gate_ids + self.heldout)

        if teacher is None:
            budget = Budget(run_cap=cfg.teacher_budget, hours=cfg.teacher_hours)
            teacher = FakeTeacher(self.log) if cfg.fake_teacher else Teacher(self.log, budget=budget, run_id=self.run_id)
        teacher.log = self.log
        self.teacher = teacher

        if run_split is None:
            if cfg.stub_runner:
                def run_split(split, *, mode, round, log, registry=None, task_ids=None, **_):
                    return stubs.run_split(split, mode=mode, round=round, log=log, registry=registry, task_ids=task_ids)
            else:
                from growth.eval import run_split as real
                from warden.sandbox import make_executor
                executor = make_executor(cfg.executor, self.log)
                self.executor_desc = executor.describe()

                def run_split(split, *, mode, round, log, registry=None, task_ids=None, **_):
                    return real(split, mode=mode, round=round, log=log, registry=registry, task_ids=task_ids,
                                profile=cfg.profile, max_steps=cfg.max_steps, max_seconds=cfg.max_seconds,
                                executor=executor)
        self.run_split = run_split
        if warden is None:
            if cfg.stub_runner:
                warden = (stubs.warden_scan, stubs.warden_build)
            else:
                from warden.manifest import build
                from warden.scan import scan
                warden = (scan, build)
        self.scan, self.build = warden
        self.state = self._load() if resume else None

    # ------------------------------------------------------------------ persistence

    def _load(self) -> dict:
        if not self.ckpt_path.exists():
            raise SystemExit(f"no checkpoint at {rel(self.ckpt_path)}")
        state = json.loads(self.ckpt_path.read_text())
        if hasattr(self.teacher, "budget") and self.teacher.budget is not None:
            self.teacher.budget.run_spent = state.get("teacherCost", 0.0)
        self.teacher.cost_usd = state.get("teacherCost", 0.0)
        return state

    def save(self) -> None:
        self.state["teacherCost"] = round(float(getattr(self.teacher, "cost_usd", 0.0)), 6)
        self.gdir.mkdir(parents=True, exist_ok=True)
        tmp = self.ckpt_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=1, default=str))
        tmp.replace(self.ckpt_path)

    # ------------------------------------------------------------------ harness versions

    def entries(self, version: int | None = None) -> list[dict]:
        k = self.state["harness"] if version is None else version
        return json.loads((self.hdir / f"h{k}.json").read_text())

    def registry_path(self, version: int | None = None) -> Path:
        return self.hdir / f"h{self.state['harness'] if version is None else version}.json"

    def grown_sources(self, entries: list[dict]) -> dict[str, str]:
        return {e["name"]: (resolve(e["path"]) / "routine.py").read_text() for e in entries if e.get("source") == "grown"}

    # ------------------------------------------------------------------ running tasks

    def run(self, split: str, ids: list[str], registry: Path, step: int) -> dict:
        with self.log.scope(round=step, taskId=None, split=None):
            res = as_split_result(self.run_split(split, mode="manifest", round=step, log=self.log,
                                                 registry=str(registry), task_ids=ids))
        return res

    def gate(self, registry: Path, entries: list[dict], step: int) -> dict:
        key = registry_key(entries)
        cache = self.state.setdefault("gateCache", {})
        if key not in cache:
            res = self.run("gate", self.gate_ids, registry, step)
            cache[key] = {"passed": res["passed"], "total": res["total"], "avgModelCalls": res["avgModelCalls"],
                          "pass": sorted(passing_ids(res))}
            self.save()
        return cache[key]

    # ------------------------------------------------------------------ the loop

    def start(self) -> None:
        self.state = {
            "runId": self.run_id, "config": asdict(self.cfg), "step": 0, "cursor": 0, "window": [],
            "traces": {}, "retired": [], "solvedOnFill": [], "harness": 0, "versions": [], "history": [],
            "accepted": [], "teacherCost": 0.0, "stopReason": None, "done": False, "startedAt": time.time(),
        }
        self.hdir.mkdir(parents=True, exist_ok=True)
        (self.hdir / "h0.json").write_text(json.dumps(SEED_REGISTRY, indent=2) + "\n")
        self.state["versions"].append({"k": 0, "step": 0, "changes": [], "registry": rel(self.hdir / "h0.json")})
        self.log.emit("run.start", mode="growth-stream", student=host_info()["studentModel"] if not self.cfg.stub_runner else "stub",
                      teacher=self.teacher.model, online=not isinstance(self.teacher, FakeTeacher),
                      algorithm="paper-failure-window", config=asdict(self.cfg),
                      trainTasks=len(self.train), gateTasks=len(self.gate_ids), heldoutTasks=len(self.heldout),
                      executor=getattr(self, "executor_desc", "stub"),
                      host=host_info() if not self.cfg.stub_runner else None)
        say(f"run {self.run_id}  K={self.cfg.k} R_max={self.cfg.r_max} Q={self.cfg.q} L={self.cfg.budget} "
            f"ablate={self.cfg.ablate or '-'}  log {rel(self.log.path)}")
        g = self.gate(self.registry_path(0), self.entries(0), 0)
        self.state["gateSR"] = {"passed": g["passed"], "total": g["total"], "harness": 0}
        say(f"h0 gate: {g['passed']}/{g['total']}")
        self.save()

    def loop(self) -> dict:
        if self.state is None:
            self.start()
        else:
            say(f"resuming {self.run_id} at step {self.state['step']}, cursor {self.state['cursor']}, "
                f"window {[w['taskId'] for w in self.state['window']]}")
        t_end = self.state["startedAt"] + self.cfg.max_hours * 3600
        while not self.state["done"]:
            self.fill()
            if not self.state["window"]:
                self.finish("stream exhausted and the window is empty")
                break
            if self.state["step"] >= self.cfg.max_opt_steps:
                self.finish(f"reached max optimisation steps ({self.cfg.max_opt_steps})")
                break
            if time.time() > t_end:
                self.finish(f"reached max hours ({self.cfg.max_hours})")
                break
            try:
                self.step()
            except TeacherBudgetExceeded as e:
                self.finish(f"teacher budget: {e}", resumable=True)
                break
            except TeacherError as e:
                self.finish(f"teacher unavailable: {e}", resumable=True)
                break
        return self.summary()

    def fill(self) -> None:
        st = self.state
        new_fail, new_pass = [], []
        while len(st["window"]) < self.cfg.k and st["cursor"] < len(self.train):
            tid = self.train[st["cursor"]]
            res = self.run("train", [tid], self.registry_path(), st["step"])
            outcome = res["results"][0]
            st["cursor"] += 1
            if outcome["pass"]:
                st["solvedOnFill"].append(tid)
                new_pass.append(tid)
            else:
                st["window"].append({"taskId": tid, "attempts": 0})
                st["traces"][tid] = window_entry(tid, outcome.get("events") or [], attempts=0, fn_level=self.fn_level)
                new_fail.append(tid)
            self.save()
        if new_fail or new_pass:
            say(f"fill: +{len(new_fail)} failures {new_fail}, solved {new_pass}; cursor {st['cursor']}/{len(self.train)}")
            with self.log.scope(round=st["step"], taskId=None, split=None):
                self.log.emit("growth.window", step=st["step"], cursor=st["cursor"], window=st["window"],
                              retired=st["retired"], solvedOnFill=new_pass)

    def context(self, entries: list[dict], step: int) -> dict:
        st = self.state
        window = [{**st["traces"][w["taskId"]], "attempts": w["attempts"]} for w in st["window"]]
        scope = sorted({r for w in window for r in w.get("routines", [])})
        return {"step": step, "api": api_reference(), "registry": registry_for_teacher(entries), "scope": scope,
                "restrict_scope": self.fn_level, "history": st["history"], "window": window,
                "q": self.cfg.q, "r_max": self.cfg.r_max, "budget": self.cfg.budget}

    def step(self) -> None:
        st = self.state
        t = st["step"] + 1
        entries = self.entries()
        current = self.grown_sources(entries)
        with self.log.scope(round=t, taskId=None, split=None):
            self.log.emit("growth.checkpoint", step=t, path=rel(self.ckpt_path), harness=st["harness"])
        ctx = self.context(entries, t)
        assert_no_leak(ctx, self.leak_terms)
        scope = set(ctx["scope"])
        verdict_box: list[Verdict] = []

        def check(cs) -> None:
            changes = [c.model_dump() for c in cs.changes]
            v = check_changeset(changes, current, scope=scope, budget=self.cfg.budget, banned=self.banned,
                                order=cs.order, restrict_scope=self.fn_level)
            if not v.ok:
                raise ValueError(f"constraint violated: {v.reason}")
            verdict_box[:] = [v]

        say(f"step {t}: asking the teacher about window {[w['taskId'] for w in st['window']]}")
        try:
            cs = self.teacher.propose_changes(ctx, check=check)
        except (TeacherOutputError, ValueError) as e:
            st["step"] = t
            return self.reject(t, [], "validate", str(e)[:400])
        names = [c["name"] for c in cs["changes"]]
        verdict = verdict_box[0] if verdict_box else Verdict(True)
        say(f"step {t}: proposal {names} (d_fun {verdict.d_fun}) — {cs['rationale'][:140]}")
        st["step"] = t

        cdir = self.gdir / "candidates" / f"s{t}"
        if cdir.exists():
            shutil.rmtree(cdir)
        manifests = []
        cand_entries = [dict(e) for e in entries]
        for ch in cs["changes"]:
            d = cdir / ch["name"]
            d.mkdir(parents=True)
            (d / "routine.py").write_text(ch["routine_py"])
            prov = {k: ch[k] for k in ("name", "trigger_description", "requested_permissions")}
            prov.update(step=t, teacher=self.teacher.model, runId=self.run_id, rationale=cs["rationale"],
                        functionsChanged=verdict.per_routine.get(ch["name"], {}))
            (d / "proposal.json").write_text(json.dumps(prov, indent=2) + "\n")
            proposal = {"name": ch["name"], "skill_md": ch["skill_md"], "trigger_description": ch["trigger_description"]}
            findings = self.scan(d, teacher=self.teacher)
            m = self.build(d, ch["requested_permissions"], findings)
            (d / "manifest.json").write_text(json.dumps(m, indent=2) + "\n")
            (d / "SKILL.md").write_text(render_skill_md(proposal, round=t, teacher_model=self.teacher.model, manifest=m))
            manifests.append(m)
            cand_entries = with_routine(cand_entries, {"name": ch["name"], "path": rel(d), "source": "grown"})
        if cs.get("order"):
            grown = {e["name"]: e for e in cand_entries if e.get("source") == "grown"}
            cand_entries = [cand_entries[0], *[grown[n] for n in cs["order"]], cand_entries[-1]]
        creg = cdir / "registry.json"
        creg.write_text(json.dumps(cand_entries, indent=2) + "\n")

        with self.log.scope(round=t, taskId=None, split=None):
            self.log.emit("growth.proposal", routine=", ".join(names), rationale=cs["rationale"],
                          triggerDescription=" | ".join(c["trigger_description"] for c in cs["changes"]),
                          skillPath=rel(cdir), step=t, status="proposed",
                          changes=[{"name": c["name"], "edit": c["name"] in current,
                                    "functionsChanged": verdict.per_routine.get(c["name"], {})} for c in cs["changes"]],
                          dFun=verdict.d_fun, order=cs.get("order"))
            for m in manifests:
                self.log.emit("warden.manifest", **{k: m.get(k) for k in ("skill", "read", "write", "commands",
                                                                        "network", "findings", "verdict")})
        bad = [m["skill"] for m in manifests if m.get("verdict") == "dangerous"]
        if bad:
            return self.reject(t, names, "warden", f"Warden verdict dangerous for {', '.join(bad)}")

        # re-execute the candidate on the window
        wids = [w["taskId"] for w in st["window"]]
        res = self.run("train", wids, creg, t)
        solved = sorted(r["taskId"] for r in res["results"] if r["pass"])
        unsolved = [tid for tid in wids if tid not in solved]
        ok = len(solved) >= self.cfg.q
        say(f"step {t}: window re-run solved {solved or 'none'} of {wids}")
        with self.log.scope(round=t, taskId=None, split=None):
            self.log.emit("growth.repair", step=t, candidate=names, solved=solved, unsolved=unsolved,
                          threshold=self.cfg.q, ok=ok)
        if not ok:
            return self.reject(t, names, "repair", f"re-run on the window solved {len(solved)} of {len(wids)} "
                                                   f"(needs {self.cfg.q})")

        # gate: success must not drop below the checkpoint's
        before = st["gateSR"]
        if "no-gate" in self.cfg.ablate:
            after = {"passed": None, "total": before["total"], "pass": [], "avgModelCalls": None}
        else:
            after = self.gate(creg, cand_entries, t)
            prev = self.state["gateCache"].get(registry_key(entries), {})
            regress = sorted(set(prev.get("pass", [])) - set(after["pass"]))
            accepted = after["passed"] >= before["passed"]
            with self.log.scope(round=t, taskId=None, split="gate"):
                self.log.emit("gate.result", routine=", ".join(names), accepted=accepted, gateBefore=before["passed"],
                              gateAfter=after["passed"], regressions=regress, gateTotal=after["total"],
                              modelCallsBefore=prev.get("avgModelCalls"), modelCallsAfter=after["avgModelCalls"],
                              rejectReason=None if accepted else "gate success dropped", rule="SR(cand) >= SR(checkpoint)")
            say(f"step {t}: gate {before['passed']} -> {after['passed']}/{after['total']}" + (f", regressions {regress}" if regress else ""))
            if not accepted:
                return self.reject(t, names, "gate", f"gate success dropped ({before['passed']} -> {after['passed']} "
                                                     f"of {after['total']}); rolled back")
        self.accept(t, cs, cand_entries, cdir, res, solved, after)

    def _bump_and_retire(self, keep: list[str] | None = None) -> list[str]:
        st = self.state
        retired = []
        nxt = []
        for w in st["window"]:
            if keep is not None and w["taskId"] not in keep:
                continue
            w = {**w, "attempts": w["attempts"] + 1}
            if w["attempts"] >= self.cfg.r_max:
                retired.append(w["taskId"])
                st["retired"].append(w["taskId"])
                st["traces"].pop(w["taskId"], None)
            else:
                nxt.append(w)
        st["window"] = nxt
        return retired

    def reject(self, t: int, names: list[str], stage: str, reason: str) -> None:
        st = self.state
        # A candidate that never ran (invalid output) is not a repair attempt on the window tasks.
        retired = self._bump_and_retire() if stage != "validate" else []
        st["history"].append({"step": t, "changes": names, "outcome": "rejected", "stage": stage, "reason": reason})
        say(f"step {t}: REJECTED at {stage}: {reason}" + (f"; retired {retired}" if retired else ""))
        with self.log.scope(round=t, taskId=None, split=None):
            self.log.emit("growth.step", step=t, outcome="rejected", stage=stage, reason=reason, changes=names,
                          dFun=None, harness=st["harness"], retired=retired)
        self.save()

    def accept(self, t: int, cs: dict, cand_entries: list[dict], cdir: Path, res: dict, solved: list[str],
               gate_after: dict) -> None:
        st = self.state
        k = st["harness"] + 1
        final_entries = []
        for e in cand_entries:
            src = resolve(e["path"])
            if e.get("source") == "grown" and src.is_relative_to(cdir):
                vdir = self.hdir / "routines" / e["name"]
                j = 1 + len([p for p in vdir.glob("v*") if p.is_dir()]) if vdir.exists() else 1
                dest = vdir / f"v{j}"
                shutil.copytree(src, dest)
                e = {**e, "path": rel(dest)}
            final_entries.append(e)
        (self.hdir / f"h{k}.json").write_text(json.dumps(final_entries, indent=2) + "\n")
        names = [c["name"] for c in cs["changes"]]
        st["harness"] = k
        st["versions"].append({"k": k, "step": t, "changes": names, "registry": rel(self.hdir / f"h{k}.json")})
        st["accepted"].append({"step": t, "harness": k, "changes": names, "solved": solved})
        if gate_after.get("passed") is not None:
            st["gateSR"] = {"passed": gate_after["passed"], "total": gate_after["total"], "harness": k}
            st["gateCache"][registry_key(final_entries)] = gate_after
        # unresolved window tasks keep fresh traces from the candidate's re-run
        by_id = {r["taskId"]: r for r in res["results"]}
        unsolved = [w["taskId"] for w in st["window"] if w["taskId"] not in solved]
        retired = self._bump_and_retire(keep=unsolved)
        for w in st["window"]:
            st["traces"][w["taskId"]] = window_entry(w["taskId"], by_id[w["taskId"]].get("events") or [],
                                                     attempts=w["attempts"], fn_level=self.fn_level)
        for tid in solved:
            st["traces"].pop(tid, None)
        st["history"].append({"step": t, "changes": names, "outcome": "accepted", "stage": "accepted",
                              "reason": f"repaired {len(solved)} window task(s); gate "
                                        f"{gate_after.get('passed')}/{gate_after.get('total')}"})
        say(f"step {t}: ACCEPTED -> h{k} ({', '.join(names)})" + (f"; retired {retired}" if retired else ""))
        with self.log.scope(round=t, taskId=None, split=None):
            self.log.emit("growth.step", step=t, outcome="accepted", stage="accepted", reason="", changes=names,
                          harness=k, solved=solved, retired=retired)
        self.save()

    def finish(self, reason: str, resumable: bool = False) -> None:
        st = self.state
        st["stopReason"] = reason
        say(f"stop: {reason}")
        final = self.registry_path()
        shutil.copy2(final, self.hdir / "registry.json")
        if self.cfg.heldout_final and not resumable:
            say(f"held-out (once) on final harness h{st['harness']}")
            res = self.run("heldout", self.heldout, final, st["step"])
            st["heldout"] = {"harness": st["harness"], "passed": res["passed"], "total": res["total"],
                             "avgModelCalls": res["avgModelCalls"]}
        st["done"] = not resumable
        with self.log.scope(round=st["step"], taskId=None, split=None):
            self.log.emit("run.end", summary=self.summary())
        self.save()

    def summary(self) -> dict:
        st = self.state
        return {"runId": self.run_id, "steps": st["step"], "accepted": st["accepted"], "finalHarness": st["harness"],
                "registry": rel(self.hdir / "registry.json"), "gate": st.get("gateSR"), "heldout": st.get("heldout"),
                "retired": st["retired"], "solvedOnFill": st["solvedOnFill"], "stopReason": st["stopReason"],
                "teacherCostUsd": round(float(getattr(self.teacher, "cost_usd", 0.0)), 4),
                "teacherCalls": getattr(self.teacher, "calls", 0), "ablate": self.cfg.ablate}


def _ids(s: str | None) -> list[str] | None:
    return [x.strip() for x in s.split(",") if x.strip()] if s else None


def main(argv: list[str] | None = None) -> int:
    load_env()
    p = argparse.ArgumentParser(prog="python -m growth.stream", description=__doc__.split("\n\n")[0])
    p.add_argument("--profile", default="full")
    p.add_argument("--window", type=int, default=4, help="K, failure-window capacity")
    p.add_argument("--r-max", type=int, default=3, help="repair attempts per task before it retires")
    p.add_argument("--q", type=int, default=1, help="repair threshold on the window")
    p.add_argument("--edit-budget", type=int, default=10, help="L, max functions added/modified per step")
    p.add_argument("--max-opt-steps", type=int, default=12)
    p.add_argument("--max-hours", type=float, default=72.0)
    p.add_argument("--teacher-budget", type=float, default=0.75, help="USD cap for this run")
    p.add_argument("--teacher-hours", choices=("any", "offpeak", "smart"), default="smart",
                   help="smart: during DeepSeek peak hours wait only if off-peak is ≤ 60 min away")
    p.add_argument("--ablate", action="append", choices=ABLATIONS, default=[])
    p.add_argument("--fake-teacher", action="store_true")
    p.add_argument("--stub-runner", action="store_true")
    p.add_argument("--no-heldout", action="store_true", help="skip the final held-out evaluation")
    p.add_argument("--max-steps", type=int, default=12)
    p.add_argument("--max-seconds", type=int, default=1800)
    p.add_argument("--executor", choices=("auto", "sandbox", "inprocess"), default="auto")
    p.add_argument("--train-tasks"); p.add_argument("--gate-tasks"); p.add_argument("--heldout-tasks")
    p.add_argument("--heldout-profile", help="evaluate the final harness on this profile's held-out split")
    p.add_argument("--resume", metavar="RUN_ID")
    p.add_argument("--label", default="stream")
    a = p.parse_args(argv)
    cfg = StreamConfig(profile=a.profile, k=a.window, r_max=a.r_max, q=a.q, budget=a.edit_budget,
                       max_opt_steps=a.max_opt_steps, max_hours=a.max_hours, teacher_budget=a.teacher_budget,
                       teacher_hours=a.teacher_hours, ablate=a.ablate, fake_teacher=a.fake_teacher,
                       stub_runner=a.stub_runner, heldout_final=not a.no_heldout, max_steps=a.max_steps,
                       max_seconds=a.max_seconds, executor=a.executor, train_ids=_ids(a.train_tasks),
                       gate_ids=_ids(a.gate_tasks), heldout_ids=_ids(a.heldout_tasks),
                       heldout_profile=a.heldout_profile, label=a.label)
    if a.resume:
        saved = json.loads((GROWTH_ROOT / a.resume / "checkpoint.json").read_text())["config"]
        cfg = StreamConfig(**{**saved, "teacher_budget": a.teacher_budget, "teacher_hours": a.teacher_hours,
                              "max_hours": a.max_hours, "max_opt_steps": a.max_opt_steps})
    try:
        summary = Stream(cfg, resume=a.resume).loop()
    except LeakError as e:
        print(f"[stream] aborted: {e}", file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
