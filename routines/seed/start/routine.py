"""Seed routine (hand-written, minimal): load TASK.md and list the repository files. Runs once."""

NAME = "start"


def applies(state) -> bool:
    return state.routine_runs.get(NAME, 0) == 0


def run(state, tools, student):
    try:
        state.task = tools.read_file("TASK.md")
    except Exception:
        state.task = "The test suite is failing. Make it pass without editing tests."
    state.files = tools.list_files()
    state.summary = f"loaded TASK.md, listed {len(state.files)} files"
    return state
