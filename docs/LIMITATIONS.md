# Limitations and failures

This page sets out what does not work, what is weak, and what has not been tested. Failures are reported with the same precision as successes. The source is [EVIDENCE.md §4](EVIDENCE.md), plus each study's FAILURES.md.

## Measured failures

| # | Failure | Number | Data | Source | Product consequence |
|---|---|---|---|---|---|
| 1 | **Wrong-day false matches** (most important). A real-ENF excerpt searched against the wrong day's reference still produced a match | 5 min: 28/270 = 10.4% [7.3, 14.6]; target was ≤ 5%. When the true day competes with two wrong days, it wins 87.4% of 5-min trials | REAL, unseen | [C1 RESULTS.json](../experiments/c1_enfwhu_unseen_holdout/RESULTS.json), [C1 FAILURES.md](../experiments/c1_enfwhu_unseen_holdout/FAILURES.md) | A single-day search must not decide the outcome. The gate must require a best match that is unique across all candidate days and must report the runner-up day. Re-calibrating needs a **fresh** test set, because this holdout has now been seen. |
| 2 | **Coverage gaps.** Of the 30 unanswered 5-min holdout clips, 21 come from recordings whose "ENF" does not follow the grid at all | 30/135 not answered | REAL | [EVIDENCE.md §4](EVIDENCE.md) | Honest abstention, and the right outcome. |
| 3 | **Short clips against the live 15 s feed** | P(top-1 within ±15 s) = 0.10 at 2 min, 0.75 at 5 min (0.18 / 0.81 with interpolation) | SEMI-SYNTHETIC | [C2 RESULTS.json](../experiments/c2_gb_reference_and_feasibility/RESULTS.json) | Same-day dating needs 10–20 min of usable ENF. NESO 1 s data arrives about 5–6 weeks late, so a claim reviewed within about 5 weeks has only Elexon. |
| 4 | **No-reference speed-tamper check** | "8 s at 1.75×" flagged 20/45 = 44% [31, 59]; false alarms 18/225 = 8.0% [5.1, 12.3]; ×1.25, ×1.5 and ×2.0 nearly invisible (aliasing onto harmonics); tempo-only edits detected 3/990 (95.6% come out `NO_GRID_SIGNAL`) | REAL audio + SYNTHETIC edits | [C3 FAILURES.md](../experiments/c3_speed_and_splice/FAILURES.md) | At most a "refer to a human" flag, never a finding. |
| 5 | **Splice detection** | insertions 57% (where a usable hum line exists); deletions 20%; false alarms 8.5% | REAL audio + SYNTHETIC edits | [C3 README](../experiments/c3_speed_and_splice/README.md) | Triage flag only. |
| 6 | **Hum that is not the grid.** 7 ENF-WHU dev recordings have strong hum that does not follow the grid (a device or local source) and match nowhere in 28 days | 7 recordings | REAL | [EVIDENCE.md §4](EVIDENCE.md) | The extractor reports "hum", the matcher finds no match, and the result is an abstention. "Hum present" must never be read as "ENF present". |
| 7 | **Venue video: a single case, and a small null.** It was dated to within 2 s of the camera clock, but it is one recording. Its p-value is floored at 1/8 because only 7 wrong-day nulls were run. Short clips abstain by design (49 s: wrong days 0.929–0.937 vs best 0.928) | — | REAL | [team_recordings_venue](../experiments/team_recordings_venue/README.md) | Run a larger wrong-day null and record more venue clips before quoting a rate. |
| 8 | **Video conditions.** Anti-flicker exposure (≈ 10 ms) and very weak flicker defeat every method. 25 fps works only with full rolling-shutter modelling | — | SYNTHETIC | [C4 FAILURES.md](../experiments/c4_video_rolling_shutter/FAILURES.md) | Abstain on these. The capture protocol asks for 30/60 fps. |
| 9 | **The 50 Hz fundamental alone is useless for audio** (median r = 0.11); the hum is in the harmonics | dev only | REAL | [W06](../experiments/w06_audio_extractor/README.md) | The extractor combines harmonics 1–7. |
| 10 | **C1 harmonic combination can be corrupted** by one loud non-ENF interferer in a single harmonic (H1/003 r = −0.20 in one configuration). W06/W10 per-harmonic consensus restores r = 0.999 | dev | REAL | [W10 audit](../reviews/W10_audit_summary.md) | Consensus weighting is the better extractor. It was not the one used for the frozen C1 holdout. |

## Not tested or not verified

- **Real videos:** the Zenodo MOV2 clip (Spanish grid, co-recorded reference) and the team's 18.4-min venue video (GB, blind against Elexon; 2 s from the camera clock). That is two clips, not a test set.
- **The W10 matcher and policy on ENF-WHU** (coverage 10/45, selective accuracy 10/10, H0 false positives 0/17, wrong-day false positives 2/45) are grade B and were not reproduced by the director. **The grade-A holdout headline uses the C1 matcher** with per-length thresholds, not the W10 policy.
- **Gemini-worker studies** (`w*` folders) are not independently re-verified, except W06 on one clip and the W02 reproduction itself.
- **Grid-statistics lead (W11):** GB frequency is about 45% more volatile around the half-hourly settlement boundaries (p < 1e-160, Aug 2026). This is a lead to verify, not a claim.
- **Red-team guards (W14)** exist as code and a plan only. **No evaluation results were produced**, so no robustness claim is made against notch filtering, ENF injection or re-encoding attacks beyond W06's codec test (MP3/AAC at 32 kbps changes median r by ≤ 0.0002).
- **Live reference station (W12)** is a prototype and is not part of any reported metric.
- **The Argon investigator (C5)** was run on only 5 cases. A fixed pipeline reaches the same 5 statuses, so **no accuracy gain from Argon is claimed**. When Argon tries several configurations, look-elsewhere risk rises above C1's measured rate. Its harmonic-subset traces are not calibrated. The tools use precomputed traces. Calls take 40–165 s. The gate rules are disclosed to Argon, so agreement with the gate is not independent evidence ([C5 README](../experiments/c5_argon_agent/README.md)).
- **No user study** with real SIU investigators. The use case is a hypothesis built on sourced industry facts ([USE_CASE.md](USE_CASE.md)).
- **Ground truth**: ENF-WHU is good to about ±5 s, so ±1 s accuracy is shown only against per-file refined ground truth (12 files).
