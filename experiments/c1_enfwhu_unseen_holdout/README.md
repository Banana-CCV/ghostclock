# C1: first end-to-end ENF timestamp matching on ENF-WHU (real audio)

All metrics come from real ENF-WHU data (`datasets/raw/enf-whu/repo/ENF-WHU-Dataset`, MIT licence). The only synthetic data is a random-walk unit check of the NCC code, which feeds no reported number.

## Headline (HOLDOUT, frozen DEV settings, run once)
Each 5-min excerpt of a holdout H1 recording is searched over its full 24-h day reference (86,400 candidate offsets).
45 recordings / 15 days, 3 excerpts each, so n = 135 trials.
- Coverage (match issued): 105/135 = 77.8% [70.1, 84.0].
- Issued matches within ±5 s of the README ground truth: 105/105 = 100% [96.5, 100].
- Within ±1 s of README GT: 35/105 = 33.3%. The README GT itself scatters by about ±4 s per file; see DATASET_NOTES.md.
- Within ±1 s of the per-file refined GT (only the 12 reliable holdout files): 31/34 = 91.2% [77.0, 97.0]. Median |err| is 0.18 s.
- False matches: H0 0/153 (0% [0, 2.5]). Wrong-day reference 28/270 = 10.4% [7.3, 14.6]. Pooled 28/423 = 6.6% [4.6, 9.4], which is above the 5% target set on dev.

Holdout curve by excerpt length (all excerpts):

| length | coverage | ±5 s among issued | wrong-ref FMR | H0 FMR |
|---|---|---|---|---|
| 1 min | 9/135 | 8/9 | 10/270 | 0/153 |
| 2 min | 39/135 | 39/39 | 10/270 | 0/153 |
| 3 min | 72/135 | 72/72 | 23/270 | 0/153 |
| 5 min | 105/135 | 105/105 | 28/270 | 0/153 |
| 8 min | 105/126 | 105/105 | 19/252 | 1/36 |
| 10 min | 54/69 | 54/54 | 7/138 | 0/9 |

RESULTS.json has every number with its Wilson 95% CI and denominator. It also includes first-excerpt-only results (n = 45 files) and the dev numbers.

## Method
- `enf.py`: decode with soundfile (ffmpeg fallback), `resample_poly` to 1 kHz (Kaiser FIR anti-aliasing), then a zero-phase Butterworth band-pass from 45 Hz to 360 Hz. STFT: 16 s Hann window, 1 s hop, zero-padded to 1/64 Hz bins. Harmonics k = 1..7 (only 1..3 for the 400 Hz references) are combined spectrally, weighted by SNR, to get a coarse estimate. Each harmonic is then refined by a parabolic peak fit and the refined values are averaged with SNR weights. Output: f(t) in Hz (fundamental-equivalent) and a per-frame quality q (peak/median, dB).
- `match.py`: weighted Pearson NCC over every offset of the 24-h reference, computed with FFTs. The excerpt mean is removed. Weights are 10^(q/20), capped, and frames more than 0.05 Hz from the file median get zero weight. Reports the top-1 offset with sub-second parabolic refinement, the peak, the second peak outside ±60 s, the margin, and a z-score.
- Decision rule: issue a match iff peak NCC > a per-length threshold. The threshold is set on DEV null trials (wrong-day references + H0 excerpts) so the dev false-match rate is ≤ 5%. Frozen thresholds: 1 min 0.9976, 2 min 0.9929, 3 min 0.9812, 5 min 0.9553, 8 min 0.9119, 10 min 0.8768.
- Split (`split.json`, seed 20261108, frozen before any tuning): grouped by recording day for H1 and by source O-file for H0. Dev has 85 H1 / 13 days and 33 H0; holdout has 45 H1 / 15 days and 17 H0. The large day groups pushed it to 65/35 rather than 60/40.
- Dev tuning covered 9 matcher settings × 3 statistics (`tuning_dev_round_all.csv`). Selected: q-weighting, clip 0.05 Hz, no high-pass, statistic = peak. An 8 s window was not tried: re-extracting the day references needs about 1 h on the loaded machine.

## Run (from repo root)
```
set PY=<WORKSPACE>\.venv\Scripts\python.exe
cd work\C1
%PY% h0_groups.py                # H0 crops -> source O-file (h0_groups.json)
%PY% make_split.py               # frozen grouped split (split.json)
%PY% extract_all.py w16 --procs 4   # ENF traces for all 338 files -> cache\w16 (about 49 min wall on the shared, loaded machine)
%PY% gt.py w16                   # ground truth + recording-vs-H1_ref offset audit (gt_w16.json)
%PY% check_ref_overlap.py w16    # day refs do not overlap (ref_overlap_w16.json)
%PY% dup_scan.py                 # duplicated hours inside day refs (dup_scan_w16.json)
REM dev tuning round (each about 5-8 min)
%PY% run_trials.py --split dev --wmode q --tag w16_hp0_q
%PY% run_trials.py --split dev --wmode none --tag w16_hp0_none
%PY% run_trials.py --split dev --wmode q --hp 120 --tag w16_hp120_q
%PY% run_trials.py --split dev --wmode q --medfilt 5 --tag w16_q_med5
%PY% run_trials.py --split dev --wmode q --clip 0.05 --tag w16_q_clip05
%PY% run_trials.py --split dev --wmode q --qthr 8 --medfilt 5 --tag w16_q8_med5
%PY% run_trials.py --split dev --wmode q --clip 0.05 --medfilt 5 --tag w16_q_clip05_med5
%PY% run_trials.py --split dev --wmode q --clip 0.03 --tag w16_q_clip03
%PY% run_trials.py --split dev --wmode none --clip 0.05 --tag w16_none_clip05
%PY% tune.py --dcal 0 --tol 5 --out frozen_round1.json w16_hp0_q w16_hp0_none w16_hp120_q w16_q_med5 w16_q_clip05 w16_q8_med5 w16_q_clip05_med5 w16_q_clip03 w16_none_clip05
REM chosen setting re-run on dev with all lengths -> per-length thresholds -> frozen.json
%PY% run_trials.py --split dev --wmode q --clip 0.05 --lens 60,120,180,300,480,600 --tag final_w16_q_clip05
%PY% tune.py --dcal 0 --tol 5 --stat peak --lens 60,120,180,300,480,600 final_w16_q_clip05
%PY% final_eval.py               # ONE holdout run -> RESULTS.json
%PY% supplementary.py            # post-hoc, no tuning: 3-way day ranking, false-match concentration
%PY% plots.py                    # plots\*.png
```
(The original round-1 ranking was written to `tuning_dev.csv`, and a copy was kept as `tuning_dev_round_all.csv`. The last `tune.py` call overwrote `tuning_dev.csv` with the final-setting row.)

## Files
- Code: `enf.py`, `match.py`, `common.py`, `analyze.py`, `run_trials.py`, `tune.py`, `final_eval.py`, `supplementary.py`, `plots.py`, `gt.py`, `harm_explore.py` (dev-only harmonic-combination check), `probe_gt.py`.
- Data products: `split.json`, `h0_groups.json`, `gt_w16.json`, `frozen.json` (with `frozen_snapshot_before_holdout.json`), `trials/*.parquet`, `RESULTS.json`.
- Docs: `DATASET_NOTES.md`, `FAILURES.md`, `progress.md`.
- Plots: `plots/spectrogram_ridge.png`, `plots/spectrogram_interference_057.png`, `plots/overlay_success.png`, `plots/landscape_success.png`, `plots/landscape_failure.png`, `plots/landscape_h0.png`, `plots/accuracy_vs_length.png`.
