# C3: no-reference ENF speed and splice checks for short clips

This is part of the GhostClock hackathon pre-test (UCL AgentVerse 2026, Finance track).
It is a triage aid for insurance investigators. A flag means "send this to a human reviewer".
It is never proof of tampering.

## What it does

`speed_check.py` looks for **playback-speed changes** without needing a reference recording.
Mains hum appears at n x f_grid. If audio is played k times faster (pitch and tempo together),
every hum line moves to n x f_grid x k. The checker works like this:

1. It computes one long-window, zero-padded Hann spectrum of the clip, then the SNR of each
   frequency bin against a 4 Hz running median.
2. It runs a harmonic-sum comb over the base frequency b, from 25 to 120 Hz in 0.005 Hz steps.
   The score is the line excess summed over harmonics 1 to 12, with a penalty of lam per
   missing harmonic slot below the highest harmonic it explains.
3. It tests these hypotheses:
   - H50: b within 50 Hz x (1 +/- k_tol)
   - H60: b within 60 Hz x (1 +/- k_tol)
   - Hk: the best b anywhere in the range, giving k = b/50 (and b/60 as an alternative)

   An off-nominal family is reported only if it explains at least min_lines_alt harmonics.
4. It refines b by a weighted least-squares fit of f_n = n*b over the line peaks
   (parabolic interpolation).
5. It builds a 95% CI for k by bootstrapping 5 sub-windows (each half the clip length).
   A second interval also folds in the +/-0.2 Hz grid band.
6. It returns one of four decisions: `CONSISTENT_WITH_REALTIME`, `SPEED_ALTERED_REVIEW`,
   `NO_GRID_SIGNAL` or `AMBIGUOUS_50_vs_60`.

`splice_check.py` follows the approach of Rodriguez, Apolinario and Biscainho (2010):

1. It picks the strongest hum line at or below 950 Hz.
2. It applies a narrow zero-phase band-pass filter around that line.
3. It demodulates the analytic signal to get the ENF phase in 0.1 s frames.
4. It computes the jump statistic J(t): the phase change across +/-1 s that the local
   (median) frequency does not explain.
5. It flags `SPLICE_SUSPECTED` when max J > theta, and lists candidate times.

**Grid facts.** GB statutory limit: +/-1 % of the declared 50 Hz
([ESQCR 2002, reg. 27(3)(a)](https://www.legislation.gov.uk/uksi/2002/2665/regulation/27)).
The Grid Code's statutory band is 49.5-50.5 Hz. NESO's normal operational band is 49.8-50.2 Hz.
k_tol = 0.006 covers the operational band (0.4 %) plus a margin for measurement error.
A fundamental of 52.5 Hz therefore implies k = 1.05.

## Run

```
set PY=<WORKSPACE>\.venv\Scripts\python.exe
cd <WORKSPACE>\work\C3

:: single file (audio, or video via ffmpeg)
%PY% speed_check.py path\to\clip.wav [--start 30 --dur 8] [--json]
%PY% splice_check.py path\to\clip.wav [--json]
%PY% speed_check.py demo\090_rate1.75_8s.wav

:: full pipeline (the split is already frozen; make_split.py refuses to overwrite it)
%PY% _map_h0.py            :: H0 crop -> source map (h0_crop_map.json)
%PY% make_split.py         :: split.json
%PY% run_eval.py --workers 7   :: eval/features.jsonl  (~1-2 h on a loaded 8-core box)
%PY% tune_and_report.py tune   :: dev only -> speed_params.json, splice_params.json, eval/tuning.json
%PY% tune_and_report.py report :: RESULTS.json (dev + holdout, Wilson 95% CIs)
%PY% ci_check.py               :: eval/ci_check.json (holdout CI coverage)
%PY% make_plots.py --rec 090 --splice-rec 120 :: plots/*.png
```

## Files

| File | What it is |
|---|---|
| `split.json` | Frozen dev/holdout split, grouped by recording day (H1) and by source recording (H0) |
| `speed_check.py`, `speed_params.json` | Speed checker and its dev-tuned thresholds |
| `splice_check.py`, `splice_params.json` | Splice checker and its dev-tuned thresholds |
| `run_eval.py`, `tune_and_report.py` | Builds the evaluation clips, tunes on dev, reports |
| `RESULTS.json` | All numbers, with k/n and Wilson 95 % CIs |
| `FAILURES.md` | Limitations and failure modes, with numbers |
| `progress.md` | Work log |
| `plots/` | Figures |
| `demo/` | 8 s original clips and 1.75x clips (the 1.75x clips are SYNTHETIC) |

The data is ENF-WHU (MIT licence): real recordings made in Wuhan on a 50 Hz grid.
Every manipulation is **synthetic** and is labelled that way in `RESULTS.json`.

The motivating case is the r/LegalAdviceUK post from March 2026, "Insurance claim - 3rd party
submitted sped up CCTV footage". It describes an 8 s clip in which about 14 s passed on the
on-screen clock, so k is about 1.75. It is used only to choose a test scenario. No claim is
made about any party in that case.

## Key holdout results (see RESULTS.json and FAILURES.md)

| Metric | Holdout result |
|---|---|
| 8 s at 1.75x (asetrate), SPEED_ALTERED_REVIEW | 20/45 = 44 % [31, 59] (dev 58/85 = 68 %) |
| False alarm on unmodified H1, all lengths | 18/225 = 8.0 % [5.1, 12.3] (dev 20/425 = 4.7 %) |
| H0 originals and synthetic 1.75x versions | 120/120 and 120/120 NO_GRID_SIGNAL |
| atempo flagged | 3/990 = 0.3 %, as expected (95.6 % come back NO_GRID_SIGNAL) |
| k = 1.25 / 1.5 / 2.0 | 11 % / 9 % / 13 % (harmonic collisions with n x 50 Hz) |
| k estimate | unreliable (1/20 within 1 % at 8 s / 1.75x); use the flag, not k |
| Splices, localised within 1.5 s, given a usable line | insertions 89/156 = 57 %, deletions 59/290 = 20 % |
| Splice false alarm, given a usable line | 12/142 = 8.5 % |

Plots: `plots/spectrum_orig_vs_1.75x_8s.png`, `plots/heatmap_tpr_rate_holdout.png`, `plots/splice_phase_jump_example.png`.
