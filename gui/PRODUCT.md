# Product

## Register

product

## Users
Two audiences, one screen. **Judges** at a hackathon stage, about 3 m from a projector in a bright hall. They get a 3-minute pitch and read the screen at a glance. **The presenter** (the builder) drives it from a laptop: replaying a recorded growth run at speed, then switching Wi-Fi off and tailing a live run. The presenter's job is to make one argument visible: code is doing the control, and the small model does only the judgement.

## Product Purpose
The Manifest GUI is a read-only viewer over the harness's event logs (`.manifest/runs/*.jsonl`). It replays a growth run round by round: a 4B student fails, a frontier teacher writes control routines as code, Warden grants or refuses each one a permission manifest, and a gate keeps or drops it. It also tails a live run. Success means a judge can say, unprompted, "the red board turned green, the model calls went down, and the thing that did it was code that had to earn permissions."

## Brand Personality
Precise, accountable, quietly confident. It reads like a flight-data recorder or a lab notebook: every action is logged, attributed and stamped. It shows evidence; it doesn't hype.

## Anti-references
- The generic observability dashboard (Grafana, Datadog): dark tiles, neon sparklines, gauge widgets, a panel grid with no argument.
- The "AI agent" dark terminal with glowing green text.
- SaaS hero metrics (big number, small label, gradient accent).
- Chat-bubble transcripts that make the model look like the protagonist.

## Design Principles
1. **Code versus model is the whole story.** Any row, card or chart must make it obvious whether code or a model acted. The two never share a visual vocabulary.
2. **Evidence over claims.** Show the actual routine name, permission globs, gate numbers and token counts. Stamps and verdicts come from logged events, never from decoration.
3. **Readable at 3 metres.** Glanceable states (pass/fail, ONLINE/OFFLINE, accepted/rejected) carry size, shape and words, not only hue.
4. **A viewer, never a controller.** Nothing in the UI changes the run. Controls exist only to move through time.
5. **Offline is the climax.** The OFFLINE state is the hero moment; design for it, not just tolerate it.

## Accessibility & Inclusion
WCAG AA contrast on a white surface (it must survive projector washout). Pass/fail always pairs colour with a glyph. Replay motion respects `prefers-reduced-motion`. Full keyboard control of transport (space, ←/→, speed keys).
