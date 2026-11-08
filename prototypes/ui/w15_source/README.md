# GhostClock W15 — Product UX, Dual Forensic Prototypes & Demo Storyboard

## Overview
Worker **W15** designed and built the non-chat forensic investigator UI prototypes and 4-minute pitch storyboard for **GhostClock**, translating the winning *ShadowStop* stagecraft pattern (**real-world mess → Argon proposal → deterministic verifier rejection with counterexample → Argon revision → vivid financial/forensic consequence**) into an auditable insurance Special Investigations Unit (SIU) workbench.

Both prototypes (`proto_A` and `proto_B`) are zero-dependency, self-contained static HTML/JS consoles that:
1. Strictly implement the frozen data contracts in `integration/interfaces.md` v1 (`trace.json`, `reference.json`, `match.json`, plus `speed_check` from W13 and `investigation_replay`).
2. Explicitly badge all bundled fixture scenarios as **`ILLUSTRATIVE — SYNTHETIC FIXTURE (NO LIVE MEASUREMENT CLAIMED)`** while providing an interactive **`Load interfaces.md JSON`** drop-in button so real outputs from W06/W07/W08/W10/W13 can be loaded directly in the browser.
3. Enforce all 8 scientific ground-truth rules and `FCA ICOBS 8.1.1R` regulatory guardrails (blinding notice, no multiplication of audio/video confidences, null-calibrated match landscape, and a hardcoded human-review gate where GhostClock cannot deny a claim or accuse a claimant of fraud).

---

## Exact Reproducible Run Commands (from Repo Root `<WORKSPACE>`)

```powershell
# 1. Generate integration/interfaces.md v1 illustrative JSON fixtures and standalone sample trace/match files
python work\W15\generate_fixtures.py

# 2. Build both self-contained static HTML/JS prototypes (work/W15/proto_A/index.html & work/W15/proto_B/index.html)
python work\W15\build_prototypes.py

# 3. Run automated contract verification, headless browser screenshot capture (6 PNGs), and composite plot generation
python work\W15\verify_and_render.py
```

To inspect either prototype interactively in any browser (no web server required; works over `file://`):
- **Prototype A ("Case File & Investigation Dossier" layout):** open `work/W15/proto_A/index.html` (supports `?case=0`, `?case=1`, `?case=2`, `?case=3`)
- **Prototype B ("Signal Lab & Multi-Modal Workbench" layout):** open `work/W15/proto_B/index.html` (supports `?case=0`, `?case=1`, `?case=2`, `?case=3`)

---

## Directory Manifest (`work/W15/`)
- `ORIENT.md` — Step A orientation, constraints, blinding rules, and falsification criteria.
- `PLAN.md` — Step B primary literature synthesis and Step C experimental UX & schema plan.
- `generate_fixtures.py` — Deterministic generator (`seed=20261108`) for `data/cases_illustrative.json`, `data/sample_case1.trace.json`, `data/sample_case1.trace.npz`, and `data/sample_case1.match.json`.
- `build_prototypes.py` — Builds `proto_A/index.html` and `proto_B/index.html`.
- `verify_and_render.py` — Verifies `interfaces.md` v1 schema compliance, audits required UI elements, captures headless Edge/Chrome screenshots (`1680x1050`), and renders `plots/fig_w15_forensic_telemetry_overview.png`.
- `demo_storyboard.md` (and `artifacts/docs/demo_storyboard.md`) — 4-minute pitch schedule, live judge-upload protocol, negative safeguard moment, two fallback options, and figure provenance table.
- `FINDINGS.md`, `FAILURES.md`, `HANDOFF.md`, `RESULTS.json`, `progress.md`.
