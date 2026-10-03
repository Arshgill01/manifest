# Manifest

**A coding-agent harness that grows itself.** A 4B model on a laptop fails at agent work because of *process* (loops, bad tool calls, never re-running tests), not intelligence. Manifest watches it fail on practice tasks; an open frontier model (DeepSeek V4.1 Flash, MIT open weights) writes the missing control routines **as code**; each routine must pass a gate on unseen tasks and earn a **permission manifest** from **Warden** before it is kept. After growth, the 4B model (Qwen3.5-4B via Ollama) + grown harness runs **fully offline** on your real code.

> Taught once online. Runs offline forever. Your code never leaves your laptop.

_Status: under construction (hackathon build). Results table lands here._

## Prior work
Builds on *"Grow the Harness, Not the Context"* (arXiv 2609.26760). Our additions: the coding domain, grown routines exported as Agent Skills, Warden in the gate and at runtime, and fully offline deployment.

## Disclosures
- Starters/templates: none yet (will be listed here).

## License
MIT — see [LICENSE](LICENSE).
