# GhostClock — shared project context (read fully)

## What we are building
**GhostClock**: an evidence-corroboration agent for insurance claims investigators. Under the right conditions, ordinary audio/video recordings capture **Electrical Network Frequency (ENF)**: the tiny, constantly changing deviations of the mains grid around its nominal 50 Hz. They show up as mains hum (50 Hz and harmonics) in audio and as light flicker (≈100 Hz for many mains lamps) in video, recovered via the camera's rolling shutter. Matching the extracted ENF *sequence* against an independent grid-frequency record (GB: NESO historical 1-second data; Elexon ~15-second rolling feed) can corroborate **when** a recording was made, or reveal **tampering** such as speed changes or splices. Gemini 4 Argon acts as the investigator: it inspects the media, chooses regions and methods, reacts to verifier failures, and abstains honestly. Deterministic code does all the numerical work and enforces the decision gates.

Competition: **UCL AgentVerse 2026, Finance track**, "Help people make better money decisions". Today is **Sunday 8 Nov 2026**, the final build day; the submission deadline is later today. Prioritise fast, real, verifiable results; your first useful deliverable should exist within ~60–90 minutes, with iteration afterwards.

Judging (Finance). Slide weights: Traceable reasoning 25%, Testing on unseen data 25%, Risk controls 20%, Relevance 15%, Ambition 15%. A later read-aloud rubric swapped risk to 15% and relevance to 20%; optimise for both.
- Traceable (strong): a judge can pick any decision and trace it from raw data to output; calculations are separate from model judgement; the agent states **what would change its mind**.
- Testing (strong): data the team never saw; a fitting baseline; uncertainty; false alarms, misses and losses shown as plainly as wins; bad or manipulative inputs caught. *Rigour, not big numbers.*
- Risk (strong): limits enforced in code, not prompts; every action logged; the agent holds or asks a human when unsure; one control visibly triggers on screen.
- Relevance (strong): a well-evidenced need for a specific user; the failure that would hurt them most is handled on screen.
- Ambition (strong): an original approach to a hard problem; the agent clearly does something a conventional program couldn't.
Deliverables: a public repo plus a pitch deck. Judges score every team from the deck; the top 3 pitch for 4 minutes plus 2 minutes of Q&A. Jane Street and a hedge-fund CEO are among the judges.

## Scientific ground truth (never violate)
1. GB nominal is 50 Hz. Hum may appear at 50 Hz or its harmonics (100, 150, 200 Hz…). Lamp flicker is often 100 Hz. None of this is guaranteed in a given clip.
2. A flat 50 Hz tone cannot date a recording. Dating needs a distinctive **sequence** of variations matched against an independent reference, with uncertainty that accounts for the size of the search space.
3. Audio ENF and video ENF from one clip sense the **same** electrical environment. They are not independent evidence; never multiply their confidences.
4. Rolling shutter ≠ mean frame brightness. Frame rate, row readout time, exposure, anti-flicker, compression, VFR, light type, motion and codec all matter.
5. Failure sources: no signal, misleading harmonics, inverter/LED drivers, generators, device audio processing (AGC, noise suppression), location/grid mismatch, metadata leakage, manipulation, reference resolution, and huge search windows.
6. Claims we may make: correspondence to a grid trace under stated assumptions. Never claim fraud, full authenticity, or that an event happened as shown.
7. Reference resolution is binding. NESO 1 s historical data is good; Elexon ~15 s may be too coarse for short clips. **Measure, don't assume.**
8. Never use metadata, filenames, EXIF, visible clocks or upload times inside the blinded ENF analysis. They can be shown only as separate, labelled corroboration.

## Decision statuses (code-enforced; the LLM cannot override)
`MATCH_SUPPORTED`, `INCONCLUSIVE`, `MATERIAL_DISCREPANCY_REVIEW` (human review required). GhostClock never approves or denies a claim and never labels anyone a fraudster.

## Environment (Windows 11; you run inside PowerShell)
- Repo root: `<WORKSPACE>`. **Your working directory is `work/<YOUR_ID>/`. Write ONLY there**, plus `agents/status/<YOUR_ID>.json`, plus any shared path your task explicitly grants you. Read anything.
- `python` is a shared venv (Python 3.12) with numpy, scipy, pandas, matplotlib (Agg), soundfile, librosa, opencv-python-headless, av, pydub, requests, scikit-learn, statsmodels, numba, pyarrow, plotly, fastapi, google-genai, pytest. `ffmpeg` and `ffprobe` are on PATH. If you truly need another package, `python -m pip install <pkg>`, and note it in your README.
- **Allowed terminal commands only:** `python …`, `pip …`, `ffmpeg …`, `ffprobe …`, `git …` (never push or add remotes; clone only into your own work dir), `cd`, `ls`/`dir`/`Get-ChildItem`, `cat`/`Get-Content`, `mkdir`, `Test-Path`, `Get-FileHash`, `Select-String`, `Select-Object`. **Anything else is auto-denied and can kill your run.** Do downloads (use `requests`), unzipping, hashing, file moves and HTTP API calls **from Python scripts you write**. Use your file-writing tools for creating files.
- Web: you may use web search and read URLs. Prefer primary sources (papers, official docs, repos).
- Never print or store API keys. `GEMINI_API_KEY` may or may not be set; check `os.environ` in code and degrade gracefully.
- Large raw downloads go under `datasets/raw/<name>/` only if your task grants it; otherwise under your work dir. Keep a manifest (URL, licence, size, sha256, date).

## Shared inputs (read-only for you unless your task owns them)
- `sources/`: organiser docs and the original briefs (AGENTVERSE_MASTER_HANDOFF.md, SOURCE_EXCERPTS_AND_CONFLICTS.md, GHOSTCLOCK_SWARM_BRIEF.md, ChatGPT_Ideate-GhostClock-Feedback….md).
- `datasets/raw/enf-whu/repo/`: ENF-WHU (MIT), cloned by the director. A `datasets/raw/enf-whu/READY` file appears when the clone is complete.
- `integration/interfaces.md`: **frozen data formats. Follow them.**
- Other workers' outputs appear under `work/<ID>/`. You may read and reuse them (cite the path), but never edit them.

## Sibling workers (so you don't duplicate)
W01 physics/literature PI · W02 GB reference data (NESO/Elexon) · W03 ENF-WHU loader+splits · W04 video datasets (Zenodo etc.) · W05 open-source baselines · W06 audio extractor A (STFT/interp/harmonics) · W07 audio extractor B (subspace/phase/ML) · W08 visual rolling-shutter · W09 visual ROI + camera physics + capture protocol · W10 matcher + statistics + eval protocol (auditor, has veto) · W11 uniqueness/feasibility math on NESO · W12 live reference station + near-real-time feeds · W13 speed-change & splice detection · W14 adversarial red team · W15 product UX + demo prototype · W16 insurance domain + fictional case · W17 pitch framing + rubric + judge Q&A · W18 Argon agent architecture · W19 idea lab · W20 prior art + dataset hunting.
