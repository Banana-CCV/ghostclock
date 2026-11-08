# GhostClock: pre-test evidence pack (director's consolidated report)
*Living document, last updated 08 Nov 2026 ~11:05. Every number below has a file path. Grades: **A** = independently reproduced on authentic inputs · **B** = executed with logs, reproduced only on a spot check or not at all · **C** = sourced research · **D** = hypothesis/illustration · **F** = failed.*

## 1. One-paragraph verdict
The physics works on real recordings, both audio and video, and the statistics can tell a real match from a lucky one. What does **not** work is dating a **short** clip against **today's public** GB grid feed, and the no-reference speed-tamper check is too weak to be a verdict. The defensible product is therefore an **insurance evidence-corroboration agent** that (a) dates recordings of several minutes against grid history with calibrated uniqueness, (b) abstains loudly and explains what evidence would change its mind when the signal or reference is inadequate, and (c) never issues an adverse finding by itself.

## 2. What is proven (real data)
| # | Claim | Number | Grade | Evidence |
|---|---|---|---|---|
| 1 | **Audio ENF extraction** tracks the true grid frequency on a real recording (ENF-WHU H1/003) | r = 0.976 at lag 0 (0.9994 after a dataset offset of ~4 s); RMSE 5.5 mHz | B (director reproduced on 1 clip) | work/W06/, agents/reviews/director_W06_smoke.md |
| 2 | **Video ENF** (rolling shutter) from a real 30 fps video tracks the mains reference | r = 0.9954, residual 1.07 mHz, n = 633 windows; the alignment is unique (best other lag r = 0.685); naive frame-mean r = 0.38 | B (director recomputed from saved traces) | work/C4/RESULTS.json, work/C4/plots/real_MOV2_overlay.png, agents/reviews/director_verify_c4.py |
| 3 | **ENF dates a clip**: in that video the ENF match recovered the true start offset, which the filename timestamps had wrong by ~11.5 s | lag 81.5 s vs filename 70 s | B | work/C4/plots/real_MOV2_lag_search.png |
| 4 | **GB reference data** is real, cleaned and live | NESO 1 s for 6 months (Oct 2025 to Sep 2026); Elexon 15 s live archive since 07 Nov 00:00Z, ~1 min behind real time | B (director spot check) | datasets/raw/gb/, work/C2/, agents/reviews/director_verify_c2.py |
| 5 | **Data traps found and fixed**: NESO Oct 2025 stamped UTC+1; NESO flat-filled outages (15 Sep 2026, 3.1 h); Elexon 0.0 Hz placeholders | (would have produced false matches) | B | work/C2/FINDINGS.md |
| 6 | **Elexon 15 s vs NESO 1 s**: identical signal up to Nov 2025 (0.59 mHz), noisier in 2026 (7.45 mHz) at lag 0 | director reproduced | B | agents/reviews/director_verify_c2.py |
| 7 | **Calibrated statistics stop false accusations**: a wrong-day spurious match reaches r = 0.76; naive stats give p ≈ 1e-58, the empirical null gives p ≈ 0.10, so the decision is INCONCLUSIVE | | B (not yet reproduced) | work/W10/ |
| 8 | **The open-source baseline breaks on gaps**: nate-griff/enf is off by 30,907 s on a 5-min clip with a 40 s gap, where the W10 matcher gets 0 s | semi-synthetic (real NESO + noise) | B | work/W10/ |
| 9 | **ENF-WHU end-to-end dating on UNSEEN data** (holdout: 45 recordings, 15 days never used for tuning; settings frozen on dev, run once; every excerpt searched over its full 24 h reference = 86,400 candidate offsets) | **5-min clips: answered 105/135 = 77.8% [70.1, 84.0]; correct within ±5 s 105/105 = 100% [96.5, 100]; no-ENF recordings falsely matched 0/153 [0, 2.5]. Within ±1 s vs per-file refined GT: 31/34 = 91%, median error 0.18 s** | **A** (director recomputed every count from the raw trial table, agents/reviews/director_verify_c1.py) | work/C1/RESULTS.json, work/C1/trials/, work/C1/plots/ |
| 9b | Same, by clip length (holdout, coverage / correct-among-issued / wrong-day false matches) | 1 min 9/135, 8/9, 10/270 · 2 min 39/135, 39/39, 10/270 · 3 min 72/135, 72/72, 23/270 · 5 min 105/135, 105/105, 28/270 · 8 min 105/126, 105/105, 19/252 · 10 min 54/69, 54/54, 7/138 | A | work/C1/plots/accuracy_vs_length.png |

### 2b. Audio extractor details (W06, ENF-WHU dev only: 78 H1 + 30 H0, grade B)
- Multi-harmonic SNR-weighted tracking: median r = 0.984 vs reference (lag 0), 86% of recordings at r ≥ 0.8. Single 100 Hz: 73%. **50 Hz fundamental alone: median r = 0.11, useless**; the hum lives in the harmonics.
- ENF-presence detector: ROC AUC 0.991; TPR 96.2% at 5% FPR.
- Codec robustness: MP3/AAC at 32 kbps changes median r by ≤ 0.0002, so compressed claimant evidence keeps the audio fingerprint.
- Confirms zero pipeline group delay; the ENF-WHU offsets are in the dataset (C1 agrees independently).

## 3. Feasibility limits (semi-synthetic: real NESO data + injected noise)
P(top-1 within ±15 s) in a 24 h search window, n = 1000 per cell (work/C2/RESULTS.json):

| Clip length | 1 s ref (NESO) | 15 s ref, block-averaged | **Real Elexon 15 s (2026)** |
|---|---|---|---|
| 2 min | 1.00 | 0.88 | **0.10** |
| 5 min | 1.00 | 1.00 | **0.75** |
| 10 min | 1.00 | 1.00 | **0.95** |
| 20 min | 1.00 | 1.00 | **0.99** |
(σ = 2 mHz; the 1 s column is an upper bound.) **Grade A**: W02 independently reproduced every column within ±2.3% (n = 400, agents/reviews/W02_reproduce_C2.md), and found that linearly interpolating real Elexon 15 s data to 1 s improves recall to **0.18 / 0.81 / 0.985 / 0.998** at 2/5/10/20 min. Use that method in the product. W02 also found that NESO's 2025 BST months (Apr–Oct 2025) are all stamped UTC+1 (2026 is clean UTC), and that Elexon's extra 2026 scatter began exactly on 13 Feb 2026; during NESO's 3 h flat-line, Elexon stayed live, so the two are independent meters that can cross-check each other. → **Same-day dating needs ≥10–20 min.** NESO 1 s data is published ~5–6 weeks later. That fits insurance, where claims are investigated weeks after the event, but a claim reviewed within ~5 weeks only has Elexon.

## 4. What failed or is weak (show these plainly; the testing criterion rewards it)
- **Wrong-day false matches are above target (the most important weakness).** If the recording was NOT made on the day of the searched reference, the matcher still issued a (wrong) match in 28/270 = 10.4% [7.3, 14.6] of 5-min holdout trials (target ≤5%). No-ENF recordings never fooled it (0/153); it is clean, real-ENF recordings searched against the wrong day that do. When the true day competes against two wrong days, it wins 87.4% of 5-min holdout trials. **Product consequence:** a single-day search must not be the decision; the gate must require the best match to be unique **across all candidate days** (the claimed day ± N days) and must report the runner-up day. Fixing the threshold needs a wrong-day-specific calibration and a FRESH test set (this holdout has now been seen).
- **Coverage gaps are honest abstentions:** 21 of 30 5-min holdout non-answers are recordings whose "ENF" hum does not follow the grid at all (they match none of 28 days).
- **No-reference speed-tamper check** (work/C3/, holdout, real audio + synthetic manipulations): "8 s at 1.75×" flagged 20/45 = 44% [31, 59]; false alarms on untouched clips 18/225 = 8.0% [5.1, 12.3]; ×1.25/×1.5/×2.0 nearly invisible (hum at 100 Hz multiples aliases back onto harmonics); the speed estimate k is unreliable; tempo-only (pitch-preserving) edits are not detected (3/990), though 95.6% of them come out NO_GRID_SIGNAL rather than "genuine". **Verdict: at most a "refer to a human" flag, never a finding.**
- **Splice detection**: insertions 57% (where a usable hum line exists), deletions 20%; false alarms 8.5%.
- **Real-world no-ENF**: 7 ENF-WHU dev recordings have strong hum that does **not** follow the grid (device or local source); they match nowhere in 28 days. The extractor sees "hum", but the matcher correctly finds no match: this is the abstention case.
- **ENF-WHU ground truth** is only good to ±5 s (a per-file offset of −5…+4.5 s, director/C1). One day-reference file repeats whole hours (recordings 090/091 excluded).
- **Video conditions**: anti-flicker exposure (≈10 ms) and very weak flicker defeat every method; 25 fps works only with true rolling-shutter modelling (validated on synthetic video only).
- **Gemini API key** provided: 403 billing error on its project; Argon works through the org project (Vertex AI, uclagentverse26lon-5508) via the agy CLI.

## 5. Grid-statistics insight (W11, grade B, not reproduced)
GB frequency is ~45% more volatile around the half-hourly settlement boundaries (p < 1e-160 on Aug 2026), so recordings that span :00/:30 should be more datable. Treat this as a lead to verify, not a deck claim.

## 6. Recommended demo (honest version)
1. **Hero reveal**: the real Zenodo video. Show the banding image → extracted ENF trace → match landscape with one unique peak → revealed true offset. All REAL, with figures in work/C4/plots/.
2. **Audio, the unseen-data proof**: ENF-WHU recording → trace overlay (work/C1/plots/overlay_success.png) → match landscape over a full day with one peak above the threshold (landscape_success.png) vs a no-ENF clip that never crosses it (landscape_h0.png) → the holdout table: "on 5-minute clips it answers 78% of the time, and every answer was right to ±5 s; it never matched a no-ENF clip; its weakness is wrong-day references, at 10%, which is why the verdict requires cross-day uniqueness and a human."
3. **Safeguard fires**: a wrong-day or no-ENF clip. Naive stats would scream "match, p = 1e-58"; GhostClock's calibrated null says INCONCLUSIVE and lists what evidence would change it. Optionally add the projector as a non-grid flicker the agent rejects (steady, wrong frequency family).
4. **Financial decision**: a fictional £20k commercial claim. The evidence report goes to a human-review gate; GhostClock cannot deny the claim.
5. **Limits slide**: the feasibility table (≥10–20 min for same-day dating) + the speed-check failure numbers.

## 7. Deck-ready figures (all REAL unless marked)
- work/C4/plots/real_MOV2_banding_residual.png: flicker bands made visible (REAL)
- work/C4/plots/real_MOV2_overlay.png: video ENF vs mains reference, naive vs rolling shutter (REAL)
- work/C4/plots/real_MOV2_lag_search.png: unique match peak (REAL)
- work/C2/plots/neso_vs_elexon_1h.png: the two reference sources (REAL)
- work/C3/plots/spectrum_orig_vs_1.75x_8s.png: speed-up shifts the hum (REAL audio, SYNTHETIC manipulation)
- work/C3/plots/heatmap_tpr_rate_holdout.png: where the speed check fails (REAL + SYNTHETIC)
- work/C1/plots/overlay_success.png: audio ENF vs reference, error −0.27 s (REAL)
- work/C1/plots/landscape_success.png / landscape_h0.png / landscape_failure.png: full-day match landscapes with the threshold (REAL)
- work/C1/plots/accuracy_vs_length.png: holdout coverage/accuracy vs clip length (REAL, unseen data)
- work/C1/plots/spectrogram_ridge.png: the tracked mains-hum ridge (REAL)

## 8. Process facts (for "how we built it")
20 Gemini 4 Argon (High) workers via the Antigravity CLI on the hackathon org project, plus the team's own engineering workstreams (WS-C1 to WS-C5) for the critical path; a supervisor with stall watchdog, auto-resume and per-worker director notes; scoped permissions (no push, project-folder writes only). The binding constraint was the project's tokens-per-minute quota (~12 concurrent workers max). Every headline number above was spot-checked by the director with independent code (agents/reviews/).
