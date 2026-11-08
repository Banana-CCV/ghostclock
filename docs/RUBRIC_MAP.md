# Rubric map (Finance track)

For each judging criterion: where it is implemented, the evidence file, and the figure. Only measured facts are listed. The worker-drafted matrix ([source/finance_rubric_matrix.md](source/finance_rubric_matrix.md), W17) contained simulated "framing tournament" scores and unverified figures. The director downgraded those to grade D ([reviews/director_W17.md](../reviews/director_W17.md)), and they are **not** used here.

## Traceable reasoning (25%)

| Requirement | Implementation | Evidence | Figure |
|---|---|---|---|
| Trace any decision from raw data to output | Extractor trace → reference → NCC landscape → null → gates → status. Every stage is deterministic Python | [decision_records/](../results/decision_records/SYNTHETIC_claim_discrepancy_2h.json) (full JSON); [C1 trial table](../experiments/c1_enfwhu_unseen_holdout/trials/final_w16_q_clip05_holdout.parquet) (one row per holdout trial: peak, lag, ground truth) | [07 landscape](../results/figures/07_day_landscape_match_REAL.png) |
| Calculations separate from the model's judgement | `ghostclock/` contains no LLM calls. Thresholds are frozen dataclasses | [policy.py](../ghostclock/policy.py) | — |
| States what would change its mind | `what_would_change_this` on every result | [RISK_CONTROLS.md §5](RISK_CONTROLS.md) | — |
| Independent re-derivation | The director's verification scripts, re-run during packaging | [reviews/](../reviews/README.md), [outputs](../reviews/outputs/director_verify_c1.txt) | — |

## Testing on unseen data (25%)

| Requirement | Implementation | Evidence | Figure |
|---|---|---|---|
| Held-out data | ENF-WHU split by day, frozen before tuning, holdout run once | [TESTING.md §1](TESTING.md), [split.json](../experiments/c1_enfwhu_unseen_holdout/split.json) | [10 accuracy vs length](../results/figures/10_holdout_accuracy_vs_length_REAL_UNSEEN.png) |
| Fitting baseline | Metadata-only, naive i.i.d., nate-griff/enf, whole-frame mean (video) | [TESTING.md §2](TESTING.md) | [02 video naive vs RS](../results/figures/02_video_enf_vs_mains_REAL.png) |
| Uncertainty | Wilson 95% CIs with denominators on every rate | [C1 RESULTS.json](../experiments/c1_enfwhu_unseen_holdout/RESULTS.json) | — |
| False alarms and misses shown plainly | Wrong-day 28/270 = 10.4%; speed check 44% detection and 8% false alarms; the 49 s venue clip correctly abstains | [LIMITATIONS.md](LIMITATIONS.md) | [09 failure landscape](../results/figures/09_day_landscape_failure_REAL.png), [12 speed-check failure map](../results/figures/12_speed_check_failure_map_REAL_plus_SYNTH.png) |
| Bad or manipulative inputs caught | No-ENF 0/153; flat tone; duplicated reference hour; spoofed metadata ignored | [TESTING.md §5](TESTING.md) | [08 no-ENF landscape](../results/figures/08_day_landscape_no_enf_REAL.png) |
| Independent reproduction | W02 reproduced the C2 feasibility table within ±2.3% | [W02_reproduce_C2.md](../experiments/w02_independent_reproduction_of_c2/W02_reproduce_C2.md) | [04 NESO vs Elexon](../results/figures/04_reference_neso_vs_elexon_REAL.png) |

## Risk controls (15–20%)

| Requirement | Implementation | Evidence |
|---|---|---|
| Limits enforced in code | `PolicyThresholds` gates; blindness invariant | [RISK_CONTROLS.md §2–3](RISK_CONTROLS.md) |
| Abstain or escalate when unsure | `INCONCLUSIVE` with reasons; `MATERIAL_DISCREPANCY_REVIEW` → human; no reject path | [policy.py](../ghostclock/policy.py) |
| Every action logged | Self-contained decision JSON; reference provenance sidecars; media SHA-256; per-action agent `trace.jsonl` (each Argon call, tool call and gate decision, with tokens and latency) | [RISK_CONTROLS.md §6](RISK_CONTROLS.md), [case a trace](../experiments/c5_argon_agent/runs/case_a/trace.jsonl) |
| Visible safeguard | Naive p = 1e-58 vs calibrated p = 0.10, giving `INCONCLUSIVE` | [W10 FINDINGS.md](../experiments/w10_matcher_and_null_calibration/FINDINGS.md) |
| **Safeguard firing on the agent** | C5 case e: a false claimed start (+7200 s) is hidden from Argon. Argon proposes `MATCH_SUPPORTED`; the code gate overrides it with `MATERIAL_DISCREPANCY_REVIEW`, logged as "gate wins" | [case e trace](../experiments/c5_argon_agent/runs/case_e/trace.jsonl), [report.json](../experiments/c5_argon_agent/runs/case_e/report.json) |
| Abstains on a short real clip | 49 s venue clip: wrong days scored 0.929–0.937, above its best of 0.928, so it abstains (C5 case d is also `INCONCLUSIVE`) | [TEST_49s_audio](../experiments/team_recordings_venue/blind/TEST_49s_audio/result.json) |

## Relevance (15–20%)

| Requirement | Implementation | Evidence |
|---|---|---|
| Named user | UK insurance SIU investigator / complex-claims handler | [USE_CASE.md §1](USE_CASE.md) |
| Evidenced need | ABI detected-fraud statistics (grade C, sourced). No published figure exists for the disputed-timestamp subset, and we say so | [USE_CASE.md §2](USE_CASE.md) |
| Most harmful failure handled | A false "recorded at a different time" → calibrated null, no-ENF abstention, human gate, no accuse path. The remaining wrong-day weakness is stated | [USE_CASE.md §3](USE_CASE.md) |
| Fits the workflow timing | Claims are investigated weeks later, by which time NESO 1 s data is published (about 5–6 weeks) | [EVIDENCE.md §3](EVIDENCE.md) |

## Ambition (15%)

| Requirement | Evidence |
|---|---|
| Original approach to a hard problem | Dating ordinary claim media against the GB grid, from **both** audio hum and **video rolling-shutter flicker** (real clip r = 0.9954, where the naive approach gets 0.38). This is combined with look-elsewhere-calibrated statistics ([C4](../experiments/c4_video_rolling_shutter/README.md), [W10](../experiments/w10_matcher_and_null_calibration/README.md)). |
| Real-world demonstration | The team's own 18.4-min venue video was dated blind from ceiling-light flicker against 36.3 h of the live GB feed: best 11:42:39Z vs camera clock 11:42:37Z (2 s error), NCC 0.979 against ≤ 0.847 on wrong days ([team_recordings_venue](../experiments/team_recordings_venue/README.md)) |
| What a conventional program could not do | **C5 Argon investigator** (real, logged, 5 cases). Argon reads a blinded probe, picks the modality, harmonics and window, calls the tools, and writes an explanation whose numbers are checked against tool outputs, with what would change its mind. **Honest ablation:** a fixed pipeline reaches the same 5 statuses, so no accuracy gain is claimed ([C5 README](../experiments/c5_argon_agent/README.md)) |

## Best use of Gemini

| Item | Status |
|---|---|
| Gemini 4 Argon produced most of the research and engineering (20 workers via the Antigravity CLI) | Verified; see [process/PROCESS.md](../process/PROCESS.md) |
| Real verification of Gemini output | The director's independent scripts ([reviews/](../reviews/README.md)) and W02's reproduction of C2. Worker studies not re-verified are labelled as such |
| Non-chat UI | Two static investigator-workbench prototypes, ILLUSTRATIVE ([prototypes/ui](../prototypes/ui/README.md)) |
| Gemini in the product loop | **C5:** `gemini-4-argon-high` via the Antigravity CLI, 11 calls and 129,993 tokens on 5 cases. It has a schema-enforced action output, a citation check of its numbers, and a code gate that overrode it on case e ([case a](../experiments/c5_argon_agent/runs/case_a/trace.jsonl), [case e](../experiments/c5_argon_agent/runs/case_e/trace.jsonl)). It works on precomputed audio and video ENF traces (no direct multimodal media ingestion). Accuracy gain over the fixed pipeline: **none measured** |
