# How this work was produced

GhostClock's pre-test evidence was produced on 7–8 Nov 2026 by **Gemini 4 Argon worker agents via the Antigravity CLI, plus the team's own engineering, with every headline number independently re-verified** ([reviews/](../reviews/README.md)). The team also captured the venue recordings and made the final decisions.

## Who did what

- **20 Gemini 4 Argon (High) worker agents** (`W01`–`W20`) ran headless through the **Antigravity CLI** (`agy`) on the hackathon's Google Cloud project. Each had a scoped brief (research, extractor, matcher, reference data, red team, UX, ...) and a mandatory contract ([prompts/_contract.md](prompts/_contract.md)): orient → research → plan → implement → execute → critique → iterate → deliver. Deliverables were README, FINDINGS, RESULTS.json with denominators, FAILURES and HANDOFF. **Never invent a measurement. Never tune on a holdout. Label synthetic data everywhere.** An example brief is [prompts/W10_example.md](prompts/W10_example.md), and the shared context is [prompts/_context.md](prompts/_context.md). Their studies are the `w*` folders in [experiments/](../experiments/README.md).
- **The team's engineering workstreams** took the critical path: WS-C1 (unseen-holdout audio dating), WS-C2 (GB reference), WS-C3 (speed and splice), WS-C4 (video rolling shutter), and WS-C5 (the Gemini 4 Argon investigator loop with its code gate). These are the `c*` folders.
- **Supervisor.** [orchestration/launch.py](orchestration/launch.py) runs each Argon worker as an `agy` subprocess with the prompt on stdin. It writes a per-worker stream log and status file, auto-resumes runs that end without DONE/BLOCKED (with a "continue" nudge that points the worker at its own `progress.md`), and retries transport errors with bounded backoff. [orchestration/monitor.py](orchestration/monitor.py) is the **stall watchdog**: it emits one line per meaningful swarm change so the director can see stalls and failures.
- **Director verification.** Before any number entered the evidence pack, the director re-derived it with separate code ([reviews/](../reviews/README.md)) and assigned an evidence grade. Outputs that failed review were downgraded in writing (e.g. [director_W17.md](../reviews/director_W17.md): the simulated "framing tournament" scores became grade D).

## Controls on the agents themselves

- Scoped permissions: workers could write only inside the project folder, and none could push to git.
- The ENF-WHU dev/holdout split was frozen before any tuning. The holdout was run once.
- Evidence grades (A/B/C/D/F) and data labels (REAL / SEMI-SYNTHETIC / SYNTHETIC / ILLUSTRATIVE) were required on every claim.
- Independent reproduction was assigned deliberately: W02 reproduced WS-C2's feasibility table.

## What we learned about running a swarm

- The binding constraint was the project's **tokens-per-minute quota**, which allowed about 12 concurrent workers at most, not the number of agents.
- A Gemini API key supplied separately returned a 403 billing error on its own project. Argon worked through the organisation's Vertex AI project via the `agy` CLI.
- Worker self-assessments were sometimes optimistic: W11 self-graded A and the director graded it B. Some deliverables were referenced before they existed: W14's results files were never produced. The director's grade is the one used in this repository.

The secrets-handling helper and raw logs from the orchestration are deliberately **not** included.
