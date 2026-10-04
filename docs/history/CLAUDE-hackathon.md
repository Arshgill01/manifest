# Manifest — agent guide

Read `SPEC.md` (whole thing), `CONTRACT.md`, and your track in `SPECLIST.md` before writing code.

- You are one of five parallel worktrees (A tasks · B harness · C grow · D warden · E gui). Edit ONLY the paths your track owns (SPEC §11, SPECLIST.md). Need something from another track? Code against the signature in `CONTRACT.md`; stub it locally behind that signature if it isn't merged yet.
- Never change `CONTRACT.md` or `SPEC.md`. Propose contract changes in your final report instead.
- Never hand-write anything into `routines/grown/` or `skills/<grown-name>/`.
- Write events only via `harness.log.EventLog`.
- Python 3.12 via uv: `uv sync` once, then `uv run python -m ...`, `uv run pytest`. Repo-level tests live in `tests/` (named `tests/test_<track>_*.py` to avoid merge clashes).
- Student = `qwen3.5:4b` on local Ollama (`http://localhost:11434`, brew-installed 0.35.x). Teacher key in `.env` (`DEEPSEEK_API_KEY`, `TEACHER_MODEL`); copy `.env.example`.
- 8 GB RAM laptop: never run two Ollama-backed suites at once; don't load other models.
- Commit small and often on your track branch (`wt/<track>`) with clear messages; tick boxes in your SPECLIST section as part of your commits. Don't push to `main`; the integrator merges.
