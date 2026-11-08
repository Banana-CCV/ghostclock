> **Release note.** Engineering workstream WS-C5. The Argon calls are real and logged. Grade **B**: executed with full logs. The release engineer re-read the five `report.json` files (statuses, 11 calls, 129,993 tokens, start error 0.17 s, the case-e override), but the runs were not repeated. Paths `work/...` refer to the original workspace (`work/C1` = [c1_enfwhu_unseen_holdout](../c1_enfwhu_unseen_holdout/README.md)). The agent uses **C1's matcher and frozen thresholds**, not the W10 policy.

# C5: real, logged Gemini 4 Argon investigator runs (agy CLI) with a deterministic gate

What this shows: **Argon chooses what to investigate (modality, harmonics, analysis window) and writes the reviewer explanation. Deterministic Python runs the ENF tools. A code gate sets the status, and Argon cannot override it.** All Argon calls below are real calls to `gemini-4-argon-high` through the Antigravity CLI, made on 2026-11-08 between 12:25 and 12:40 UTC. Every step is in `runs/<case>/trace.jsonl`.

## How it works (`agent.py`, about 330 lines)
1. **Probe (tool).** Reports media duration, available modalities, per-harmonic median hum SNR, frame quality, trace std and the length of the permitted reference window. The probe values come from C1's cached ENF traces (`work/C1/cache/w16`, extracted by `work/C1/enf.py`) or, for the venue case, from the director's audio and dark-video traces. The duration comes from ffprobe.
2. **Argon loop (at most 5 calls per case).** Argon receives a JSON dossier: an opaque case id (`GC-xxxxxxxx`), the probe, and all previous tool results. **It never sees filenames, ground truth, metadata times or the claimed time.** It replies with a schema-enforced action (`action_schema.json`): either `extract_and_match(modality, harmonics, window_start_s, window_len_s)` or `decide` (proposed status, explanation, what-would-change list, basis match).
3. **Tool (Python).** `extract_and_match` rebuilds the ENF trace from the chosen harmonics. Using all harmonics gives exactly C1's frozen extraction; a subset is recombined from the cached per-harmonic estimates, weighted by SNR. The trace is then matched with **C1's quality-weighted NCC matcher** (`work/C1/match.py`) over the permitted 24 h reference. For the venue case it uses the director's Elexon 1 s scan (`work/director/blind_match.py`), and audio, video or fused traces are available.
4. **Gate (code, `gate()`).** It applies these rules in order:
   - duration under 60 s → INCONCLUSIVE.
   - the basis match must have peak NCC above **C1's dev-frozen per-length threshold** (`work/C1/frozen.json`), otherwise INCONCLUSIVE.
   - all passing configurations must agree on the media start within 5 s, otherwise INCONCLUSIVE.
   - if the case has a claimed start (hidden from Argon) more than 60 s from the ENF start → MATERIAL_DISCREPANCY_REVIEW.

   If Argon's proposed status differs from the gate's, the gate wins and the conflict is logged.
5. **Citation check.** Every number in Argon's explanation and what-would-change list is checked against the numbers in the probe and tool outputs. Numbers not found there are listed in `report.json → unsupported_numbers_in_explanation`.
6. **Logging.** Each step is written to `trace.jsonl` with `ts, case_id, step, actor (argon|tool|gate), input_summary, output, tokens, latency_s`. Each case also gets `report.json` and `report.md`. Ground-truth scoring happens only after the run, in `evaluation_hidden_from_agent`.

## Exact commands (from the repo root)
```
.venv\Scripts\python.exe work\C5\agent.py case_a        # Argon-directed (each case was run as its own process, a-d in parallel)
.venv\Scripts\python.exe work\C5\agent.py --fixed case_a case_b case_c case_d case_e       # ablation 1: C1's exact trial config
.venv\Scripts\python.exe work\C5\agent.py --fixed-long case_a case_b case_c case_d case_e  # ablation 2: rule = all harmonics, longest calibrated window
```
agy invocation, run as a subprocess with an argument list, with the prompt on stdin and cwd `work/C5/agy_cwd`:
`agy.exe --model gemini-4-argon-high --output-format json --print-timeout 10m --json-schema work/C5/action_schema.json`

## Cases
| case | media given to the agent (blinded) | permitted reference | hidden truth |
|---|---|---|---|
| a | ENF-WHU **holdout** H1 `011` (734 s audio) | its own 24 h day ref `011` | GT start 50769.05 s (C1 `gt_w16.json`); C1 issued a match for the L=300 trial k=1 |
| b | ENF-WHU **holdout** H0 negative `13` (465 s) | day ref `070` | no ENF; any match would be false |
| c | same recording as a | **wrong day** ref `020-025` (C1's own h1_wrong trial) | any match would be false |
| d | team venue clip A001_11081103_C002 (49.39 s, audio and dark video traces) | GB Elexon live archive, 2026-11-07 00:00 to 2026-11-08 12:21 UTC | too short to date |
| e | same recording as a | own day ref | **false claimed start (+7200 s)**, which only the gate sees |

## Results (Argon-directed runs, all real)
| case | Argon calls | Argon's actions | gate status | expected | Argon tokens (total) | Argon latency | post-hoc check |
|---|---|---|---|---|---|---|---|
| a | 2 | audio, h=[2,3,4,6] (dropped weak h1/h5/h7, SNR 4.5/9.9/9.4), 600 s window → peak 0.99967 > thr 0.87678, margin 0.217 → decide | **MATCH_SUPPORTED** | MATCH_SUPPORTED | 17,315 | 119.5 s | start error **0.17 s** vs GT |
| b | 3 | h=[4,5,6,7] 300 s → 0.661; then h=[4] 300 s → 0.671 (thr 0.955) → decide | **INCONCLUSIVE** | INCONCLUSIVE | 37,390 | 208.5 s | correct abstention |
| c | 3 | h=[2,3,4,6] 600 s → 0.784; h=[2,4,6] 600 s from 134 s → 0.749 (thr 0.877) → decide | **INCONCLUSIVE** | INCONCLUSIVE | 38,510 | 204.7 s | no false match on the wrong day |
| d | 1 | decided immediately, without a tool call, because 49.39 s is under the 60 s gate | **INCONCLUSIVE** | INCONCLUSIVE | 14,588 | 165.0 s | correct; the explanation asks for a longer recording |
| e | 2 | same as case a → Argon proposed MATCH_SUPPORTED (it cannot see the claim) | **MATERIAL_DISCREPANCY_REVIEW** (gate overrode Argon, logged) | MDR | 22,190 | 100.6 s | ENF start 0.17 s from GT; claim off by about +7200 s |

**Totals:** 11 Argon calls, 129,993 tokens, 798 s of Argon latency (about 40 to 165 s per call; four processes ran in parallel). Citation check: no unsupported numbers in a, c, d or e. In b it flagged "10" twice; that number comes from the probe field name `frac_frames_quality_ge_10db`, so it is a false positive of the checker.

## Ablation: the same cases without Argon (all 5 statuses agree)
| case | fixed = C1's exact trial config (all harmonics, 300 s at C1's start) | fixed_long = rule: all harmonics, longest calibrated window from 0 | Argon |
|---|---|---|---|
| a | MATCH_SUPPORTED, peak 0.99959 (thr 0.95531), err 0.20 s | MATCH_SUPPORTED, 0.99966 (thr 0.87678), err 0.18 s | MATCH_SUPPORTED, 0.99967, err 0.17 s |
| b | INCONCLUSIVE, 0.72111 | INCONCLUSIVE, 0.64632 | INCONCLUSIVE, 0.661 / 0.671 |
| c | INCONCLUSIVE, **0.95257 vs thr 0.95531 (near miss, 0.003 below)** | INCONCLUSIVE, 0.78440 vs 0.87678 | INCONCLUSIVE, 0.78438 / 0.74851 |
| d | INCONCLUSIVE (duration gate; scan peak 0.9324 with no calibrated threshold) | same | INCONCLUSIVE (no tool call) |
| e | MDR | MDR | MDR (gate override) |

Honest reading:
- The `fixed` run reproduces C1's holdout parquet exactly: case a 0.999587, case c 0.952568, case b 0.721113. This confirms the tools are wired correctly.
- On these 5 cases, **Argon did not change any outcome** compared with either fixed pipeline. Its useful choice was the longer 600 s window. That choice turned the case-c wrong-day near miss (0.953 vs 0.955) into a clear rejection (0.784 vs 0.877). The simple rule "longest calibrated window" gets the same benefit at zero cost, and dropping the weak harmonics changed the peak by only about 0.0001.
- **We do not claim Argon improves accuracy.** That has not been measured: 5 cases is far too few, and C1's frozen thresholds are the validated part (holdout: 105/105 issued matches within ±5 s, H0 0/153).
- What Argon adds here is an adaptive, logged choice of what to run, plus a reviewer explanation that uses only numbers from the tool outputs.

## Limitations (read before presenting)
- **Look-elsewhere.** C1's thresholds were frozen for one configuration (all harmonics, 16 s window, q-weighting, clip 0.05 Hz). When Argon tries several configurations (2 in cases b and c), the false-match risk is higher than C1's measured rate. The gate's consistency rule partly mitigates this, and the gate logs the caveat in its reasons when more than one configuration was tried.
- **Harmonic subsets are uncalibrated.** Argon's subset traces are recombined from cached per-harmonic estimates (SNR-weighted, snr >= 2). This is not identical to a fresh `enf.extract_enf(harmonics=...)` run and was not part of C1's threshold calibration.
- **Precomputed traces.** The tools use precomputed traces (C1 cache and the director's venue CSVs) rather than decoding media live, for speed. Audio decode and extraction (`work/C1/enf.py`) was validated by C1, not re-run here.
- **Venue case.** For case d no calibrated GB threshold exists for clips under 60 s. The fixed scan's best peak of 0.9324 is meaningless; the director's null test on 7 wrong days gave peaks up to 0.937. Argon chose not to run a tool, which is consistent with the gate's rules but means the case-d trace has no tool step.
- **Case-d superseded run.** The first case-d Argon run used a wrong duration (52.99 s, estimated from the trace span instead of ffprobe). It is kept in `runs/case_d_superseded_bad_duration/` and replaced by the ffprobe-based run (49.39 s). The status was INCONCLUSIVE in both runs.
- **Gate rules are disclosed to Argon.** Its proposals therefore usually match the gate, so agreement is not independent evidence. Case e shows the override path, because only the gate sees the claim.
- **Latency.** 40 to 165 s per Argon call, so roughly 2 to 3.5 minutes per case. That is fine for a demo and slow for batches.
- **W18's agent** (106 KB) was not used. Its recorded agy smoke test had failed (`-p` flag misuse), and a compact rewrite was faster than debugging it.

## Files
- `agent.py`: agent, tools wrapper, gate and logging. `action_schema.json`: Argon output schema. `test_schema.json` and `agy_test_out.json`: initial agy smoke test (SUCCESS, 30 s).
- `runs/case_{a..e}/`: Argon runs. `runs/case_*_fixed/` and `runs/case_*_fixedlong/`: ablations. Each folder holds `trace.jsonl`, `report.json` and `report.md`.
- `logs/run_*.log`: one-line run summaries. `progress.md`: timeline.
- **Demo traces:** `runs/case_a/trace.jsonl` (clean MATCH_SUPPORTED: Argon picks harmonics and window, the tool verifies, start error 0.17 s) and `runs/case_e/trace.jsonl` (same evidence plus a hidden false claim; the gate overrides Argon's MATCH_SUPPORTED with MATERIAL_DISCREPANCY_REVIEW).
