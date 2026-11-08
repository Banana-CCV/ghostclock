# C4: visual ENF from rolling-shutter flicker in ordinary video

GhostClock pre-test (UCL AgentVerse 2026, Finance track), 8 Nov 2026. Physics and citations
are in [METHOD.md](METHOD.md). Failure analysis is in [FAILURES.md](FAILURES.md). The work log
is [progress.md](progress.md). All numbers below come from `RESULTS.json`.

## Headline (REAL data)

**Test clip:** Zenodo 3549379 (ENF Moving Video Database, Vigo, Spain, 50 Hz).

| Property | Value |
|---|---|
| File | `MOV2_20190508_200450A.mp4` |
| Format | 1280×720 H.264, 30.026 fps, 647 s, 19,441 frames |
| Scene | "movement, but most frames static": a person walks through |
| Reference | `b827ebd746d7_tensiunator2_20190508_200340.wav` (1 kHz mains voltage) |
| Checksums | md5 verified for both files |

| Method | r @ filename lag 70 s | r @ best lag 81.5 s | RMSE (mHz) | bias (mHz) | RMSE after bias removal (mHz) | median q (dB) |
|---|---|---|---|---|---|---|
| **Rolling-shutter extractor** (T_ro = 28.25 ms, estimated) | 0.645 | **0.9954** | 4.48 | +4.35 | **1.07** | 45.1 |
| Strip-wise alias baseline | 0.646 | **0.9967** | 4.44 | +4.34 | 0.91 | 30.5 |
| Naive whole-frame mean | 0.323 | 0.381 (best lag 79 s) | 35.9 | −1.76 | 35.9 | 14.0 |

Reading the table:

* **n = 633** windows (16 s Hann windows at a 1 s hop). They overlap, so they are not
  independent samples.
* **Lag.** The best lag was searched over 10–130 s, with one free parameter.
  * Over the full feasible range of 0–252.5 s the peak is still at 81.5 s, and the next-best
    correlation more than 10 s away is 0.685.
  * The filename timestamps disagree with that lag by 11.5 s. The likely cause is that the
    recorder clocks were not synchronised (FAILURES.md F1). At the filename lag, r is only 0.645.
* **Bias.** The constant +4.35 mHz bias equals 87 ppm of 50 Hz. This is a timebase mismatch
  between the phone's frame clock and the reference ADC clock, not an extraction error
  (FAILURES.md F2).

### What the real result does and does not show

* **What it shows.** The rolling-shutter extractor recovers the ENF from an ordinary phone-style
  720p H.264 clip with a person walking through it. After lag alignment, r = 0.995 and the error
  is about 1 mHz once the bias is removed.
* **The naive whole-frame mean fails on this clip (r = 0.38) for a physical reason.**
  * The estimated read-out time is 28.25 ms. The whole-frame mean therefore averages
    100 × 0.02825 = 2.8 flicker cycles, and the 100 Hz term is scaled by
    `|sinc(2.825)| ≈ 0.06` (METHOD §3).
  * Its median q is 14 dB, against 45 dB for the rolling-shutter extractor.
* **On this clip, rolling shutter has no advantage over the strip-wise alias baseline.**
  * That baseline is per-row-band frame-rate sampling, like the per-row series of
    Hajj-Ahmad et al. At 30 fps it is just as accurate (r 0.9967 against 0.9954).
  * The rolling-shutter extractor gives a 15 dB higher q, which matters for abstaining, and it
    estimates T_ro.
  * **The rolling-shutter method only becomes necessary at degenerate frame rates (25/50 fps on
    a 50 Hz grid).** That case is demonstrated on SYNTHETIC data only, because the Zenodo
    videos are 30 fps.
* **No comparison with published numbers.** Karantaidis & Kotropoulos (PMC8538866) report a
  maximum correlation of 0.9704 on "mov2". Their windows, metric and possibly their file differ
  from ours, so the two results are not comparable.

## SYNTHETIC validation (`synth_rs.py`; every file is prefixed `SYNTH_`)

**Setup:** 640×360, 240 s, libx264 at CRF 20, OU random-walk ENF (about 15 mHz per minute),
textured scene with a clipped window, a dark corner and a moving dark "person", 2 % slow
auto-exposure drift, noise σ = 1.5. Flicker depth m1 = 5 %, T_exp = 2 ms unless noted. Truth is
the Hann-window-averaged ENF. All rows below are SYNTHETIC.

| SYNTHETIC case | T_ro est / true (ms) | RS r / RMSE (mHz) | strip-alias r / RMSE | naive r / RMSE | RS median q (dB) |
|---|---|---|---|---|---|
| fps30_tro25 | 25.00 / 25 | **0.999 / 0.34** | 0.996 / 0.80 | 0.971 / 1.67 | 45.5 |
| fps30_tro30_framemean_null (sinc = 0) | 30.25 / 30 | **0.999 / 0.27** | 0.995 / 0.67 | 0.830 / 3.29 | 47.5 |
| fps60_tro12 | 12.00 / 12 | **0.998 / 0.32** | 0.996 / 0.94 | 0.962 / 1.62 | 42.0 |
| **fps25_tro25_alias_degenerate** | 25.25 / 25 | **0.986 / 0.96** | **−0.994 / 93.7** | −0.274 / 86.0 | 56.0 |
| fps30_antibanding_exp10ms (negative control) | 6.25 / 25 | −0.218 / 95.5 | −0.116 / 96.6 | 0.037 / 134.6 | **3.9** |
| fps30_weak_m1pct_crf28 (stress) | 22.75 / 25 | 0.109 / 110.4 | 0.037 / 138.4 | −0.280 / 157.4 | **3.6** |

What the synthetic runs show:

* **Degenerate frame rate (25 fps).** Both frame-rate methods fail there, and the strip-wise
  alias baseline returns a confident but sign-flipped trace. The rolling-shutter extractor
  still tracks the ENF (r = 0.986).
* **Abstaining.** When the flicker is absent or too weak, q collapses from more than 40 dB to
  about 4 dB. A q gate (for example 20 dB) separates the working cases from the failing ones.
* **Read-out direction.** At 25 fps ±T_ro tie exactly (score ratio 1.0000), so the scan
  direction, and therefore the ENF sign, is ambiguous. See FAILURES.md F4.

## Plots (`plots/`)

* `real_MOV2_banding_residual.png`: decoded frame, contrast-stretched residual (frame minus
  the mean of 60 frames) showing the horizontal flicker bands (about ±3 grey levels), and the
  row profile (about 2.8 cycles per frame).
* `real_MOV2_row_spectrogram.png`: spectrogram of the rolling-shutter baseband around 100 Hz,
  with 2× the reference ENF overlaid.
* `real_MOV2_overlay.png`: extracted ENF vs reference (rolling-shutter, strip-wise and naive)
  plus the residual.
* `real_MOV2_lag_search.png`: correlation against lag over the full feasible range.
* `Tro_search.png`: T_ro objective for the real clip (both scan directions) and all synthetic
  cases.
* `SYNTH_summary.png`, `SYNTH_*_overlay.png`, `SYNTH_fps30_tro25_banding_residual.png`,
  `SYNTH_fps30_tro25_row_spectrogram.png`: SYNTHETIC only.

## Run commands (repo root, Windows, venv Python)

```bat
set PY=<WORKSPACE>\.venv\Scripts\python.exe
cd work\C4
rem 1) list Zenodo files and download smallest video + its reference (md5-verified)
%PY% zenodo_list.py zenodo_files.json
%PY% zenodo_fetch.py zenodo_files.json ..\..\datasets\raw\video_c4 b827ebd746d7_tensiunator2_20190508_200340.wav MOV2_20190508_200450A.mp4
rem 2) real run (decodes once into datasets\raw\video_c4\cache\MOV2_cells.npz, ~6 min; analysis ~4 min)
%PY% run_real.py
rem 3) synthetic benchmark (renders synth\SYNTH_<case>.mp4, then evaluates)
%PY% synth_eval.py fps30_tro25 fps30_tro30_framemean_null fps25_tro25_alias_degenerate fps25_tro25_alias_degenerate+bidir fps60_tro12 fps30_antibanding_exp10ms fps30_weak_m1pct_crf28
rem 4) collect + plot
%PY% assemble_results.py
%PY% make_plots.py
rem any video (generic CLI): writes <out>_rs_trace.csv (t_s, enf_hz, q_db), <out>_naive_trace.csv, <out>_info.json
%PY% rs_enf.py path\to\video.mp4 --grid 50 --out myclip [--tro-ms 28.25] [--allow-negative-tro]
```

## Files

| File | Purpose |
|---|---|
| `rs_enf.py` | extractor: decode → cells → static mask → relative residual → robust row signal → row-time heterodyne → T_ro search → STFT track; naive and strip-wise baselines; reference ENF; lag search |
| `synth_rs.py` | SYNTHETIC rolling-shutter renderer + H.264 encode |
| `synth_eval.py` | SYNTHETIC benchmark cases and metrics |
| `run_real.py` | REAL Zenodo MOV2 run |
| `assemble_results.py`, `make_plots.py` | RESULTS.json and figures |
| `zenodo_list.py`, `zenodo_fetch.py`, `zenodo_files.json` | Zenodo API listing, resumable download and md5 check |
| `ffprobe_MOV2.json`, `mov2_pts.csv` | container and stream probe, per-packet PTS |
| `real_MOV2_*_trace.csv`, `ref_MOV2_enf_trace.csv` | extracted traces (t, f, q) and reference trace |
| `synth/old_*` | archived superseded runs (bugs documented in progress.md) |
