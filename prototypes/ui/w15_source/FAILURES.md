# W15 Failures, Visual Defects & Honest Limitations (`FAILURES.md`)

## 1. Real Failure Case Caught & Resolved During W15 Execution (Step F → Step G)
- **Failure Case (`proto_A` v1 Vertical Viewport Clipping at `1680x1050`):**
  - *Observation:* When inspecting our first headless browser render (`work/W15/plots/proto_A_case1_discrepancy.png`), the tall two-step Argon Investigation Replay card in the center column pushed **Card 6 (Match Landscape Plot)** and **Card 9's Export Button** below the `1050px` bottom edge, cutting off the candidate time axis and the `CLAIMED TIME (r=0.118)` annotation.
  - *Root Cause:* Allocating `200px` + `195px` SVG viewBox heights plus `13px` card padding and `12px` grid gaps exceeded `1050px` whenever an investigation had $\ge 2$ Argon attempts.
  - *Step G Fix & Verified Delta:* We compacted `.card` padding (`9px 11px`), `.layout-grid` gaps (`10px`), and SVG chart heights (`165px`) in `work/W15/build_prototypes.py` and re-ran `verify_and_render.py`. In the revised renders, **100% of all 9 cards, both SVG axes, and the Export button fit inside a single `1680x1050` screen without scrolling**.

## 2. Structural & Domain Limitations of the Prototype UI
1. **Bundled Data Provenance (`ILLUSTRATIVE — SYNTHETIC FIXTURE`):**
   - Because W15 ran in parallel with the signal-processing and matching workers (W06–W13), the 4 default scenarios embedded in `cases_illustrative.json` are **synthetic/illustrative fixtures** generated with fixed seed `20261108` to match `integration/interfaces.md` v1.
   - *Mitigation:* Every screen, SVG chart header, and exported JSON log carries an unmistakable amber provenance banner (`ILLUSTRATIVE — SYNTHETIC FIXTURE (NO LIVE MEASUREMENT CLAIMED)`). Real `.trace.json` and `match.json` outputs from sibling workers can be loaded via the `Load interfaces.md JSON` file picker.
2. **Browser-Side File Upload Cannot Run Native `ffmpeg` / STFT Without Local Backend:**
   - Static HTML (`file://`) can parse and render `.json` outputs (`trace.json`, `match.json`, or full case bundles) immediately, but raw `.mp4` / `.wav` extraction requires invoking the Python deterministic pipeline (`W06`/`W08`/`W10`/`W13`) via a local FastAPI endpoint (`W18`/integration).
3. **No Live Human-Subject Usability Trial (`not_run`):**
   - Comparison between Prototype A and Prototype B is based on programmatic rubric-token verification (`10/10` elements) and visual inspection of `1680x1050` headless renders rather than a multi-participant human timing study (`live_human_subject_usability_study: "not_run"` in `RESULTS.json`).
