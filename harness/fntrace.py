"""Function-level tracing inside routines: the execution graph of the paper (§3.2).

`instrument(module, emit)` wraps every function defined in a routine module so each call reports
`fn.call` (name, depth, short args) on entry and `fn.return` (short result or exception, ms) on exit.
Calls between the module's own helpers go through module globals, so they are traced too. Tool and
student calls made in between are logged by the tool layer / student client as usual, which gives an
ordered, nested trace: routine -> functions -> tool/student calls -> returns.

Used in-process (InProcessExecutor) and inside Warden's sandbox child (events go back over the pipe),
so a routine produces the same trace wherever it runs.
"""

from __future__ import annotations

import functools
import inspect
import time
from types import ModuleType
from typing import Any, Callable

MAX_REPR = 160
MAX_EVENTS = 80           # per routine run; a looping helper must not flood the log
OPAQUE = {"state": "<state>", "tools": "<tools>", "student": "<student>"}


def short(v: Any, n: int = MAX_REPR) -> str:
    try:
        if type(v).__name__ == "State" or (isinstance(v, dict) and "task_dir" in v):
            return "<state>"
        if type(v).__name__ in ("Tools", "_Proxy", "Student"):
            return f"<{type(v).__name__.lower().lstrip('_')}>"
        if isinstance(v, str):
            r = repr(v)
        elif isinstance(v, (list, tuple)) and len(v) > 4:
            r = f"[{len(v)} items: {short(v[0], 60)}, …]"
        elif isinstance(v, dict) and len(repr(v)) > n:
            r = "{" + ", ".join(f"{k!r}: …" for k in list(v)[:6]) + (", …}" if len(v) > 6 else "}")
        else:
            r = repr(v)
    except Exception:
        r = f"<{type(v).__name__}>"
    return r if len(r) <= n else r[: n - 1] + "…"


def instrument(module: ModuleType, emit: Callable[[str, dict], None], *, routine: str) -> None:
    depth = [0]
    count = [0]

    def wrap(name: str, fn: Callable) -> Callable:
        try:
            params = list(inspect.signature(fn).parameters)
        except (TypeError, ValueError):
            params = []

        @functools.wraps(fn)
        def traced(*args, **kwargs):
            if count[0] >= MAX_EVENTS:
                return fn(*args, **kwargs)
            count[0] += 1
            shown = {}
            for i, a in enumerate(args):
                key = params[i] if i < len(params) else f"arg{i}"
                shown[key] = OPAQUE.get(key) or short(a)
            for k, a in kwargs.items():
                shown[k] = OPAQUE.get(k) or short(a)
            emit("fn.call", {"routine": routine, "fn": name, "depth": depth[0], "args": shown})
            depth[0] += 1
            t0 = time.monotonic()
            try:
                out = fn(*args, **kwargs)
            except BaseException as e:
                depth[0] -= 1
                emit("fn.return", {"routine": routine, "fn": name, "depth": depth[0],
                                   "exc": f"{type(e).__name__}: {short(str(e), 120)}",
                                   "ms": int((time.monotonic() - t0) * 1000)})
                raise
            depth[0] -= 1
            emit("fn.return", {"routine": routine, "fn": name, "depth": depth[0],
                               "ret": short(out), "ms": int((time.monotonic() - t0) * 1000)})
            return out

        traced.__manifest_traced__ = True  # type: ignore[attr-defined]
        return traced

    for name, obj in list(vars(module).items()):
        if inspect.isfunction(obj) and obj.__module__ == module.__name__ and not getattr(obj, "__manifest_traced__", False):
            if name == "applies":
                continue  # evaluated every controller step; tracing it would drown the graph
            setattr(module, name, wrap(name, obj))
