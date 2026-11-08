# C4 — Visual ENF via the rolling shutter: physics and method brief

GhostClock pre-test, 8 Nov 2026. Author: workstream WS-C4. Status: the brief is based on primary
sources where marked **[read]**. Items marked **[abstract/metadata only]** were not read in full
because the full text could not be fetched today. Items marked **[derived]** are my own
derivations from the stated model. I have not invented any figure from a paper.

## Sources

| # | Reference | How used |
|---|---|---|
| S1 | S. Vatansever, A. E. Dirik, N. Memon, "Analysis of Rolling Shutter Effect on ENF-Based Video Forensics", *IEEE Trans. Inf. Forensics Security*, 2019, doi:10.1109/TIFS.2019.2895540; preprint arXiv:1903.09889 | **[read]** full arXiv text (eqs. 1–24, Figs. 5–8) |
| S2 | H. Su, A. Hajj-Ahmad, R. Garg, M. Wu, "Exploiting rolling shutter for ENF signal extraction from video", *Proc. IEEE ICIP* 2014, doi:10.1109/ICIP.2014.7026086 | **[abstract/metadata only]**, plus S1's restatement of its filter-bank model |
| S3 | A. Hajj-Ahmad, A. Berkovich, M. Wu, "Exploiting Power Signatures for Camera Forensics", *IEEE Signal Process. Lett.* 23(5):713–717, 2016, doi:10.1109/LSP.2016.2537201 | **[abstract/metadata only]** (par.nsf.gov refused the connection), plus S1's restatement (eq. 23) |
| S4 | G. Karantaidis, C. Kotropoulos, "An Automated Approach for Electric Network Frequency Estimation in Static and Non-Static Digital Video Recordings", *J. Imaging* 7(10):202, 2021, doi:10.3390/jimaging7100202, **PMC8538866** | **[read]** via PMC. This is the paper that evaluates the *ENF Moving Video Database*. **Correction to the brief:** PMC8538866 is by Karantaidis & Kotropoulos, not by Vatansever et al. |
| S5 | S. Fernández-Menduiña, F. Pérez-González, *ENF Moving Video Database*, Zenodo, doi:10.5281/zenodo.3549379 (CC-BY-4.0); related letter "Temporal Localization of Non-Static Digital Videos Using the Electrical Network Frequency", *IEEE SPL* 2020, doi:10.1109/LSP.2020.2988145 | Zenodo record **[read]** via API; letter **[abstract only]** |
| S6 | J. Choi, C.-W. Wong, H. Su, M. Wu, "Analysis of ENF Signal Extraction From Videos Acquired by Rolling Shutters", TechRxiv 2022/2025, doi:10.36227/techrxiv.21300960 | **[abstract only]** ("periodic zeroing-out") |
| S7 | S. Vatansever, "A Thorough Investigation Into the ENF Reconstruction in Videos Exposed by Rolling Shutter", *IEEE Access* 2023, doi:10.1109/ACCESS.2023.3312030 | **[abstract only]** (ENF reversal) |
| S8 | G. Frijters, Z. Geradts, "Use of electric network frequency presence in video material for time estimation", *J. Forensic Sci.* 2022, doi:10.1111/1556-4029.15003 | **[abstract only]** (smartphones, light sources) |
| S9 | R. Wyton, B. Rehman, "Frame Rate, Not the Grid: A Confound in Single-Clip Optical ENF Video Forensics", arXiv:2610.20549 (2026) | **[abstract only]** (frame-rate comb confound) |
| S10 | Android `CaptureRequest.CONTROL_AE_ANTIBANDING_MODE` (OFF / 50HZ / 60HZ / AUTO), developer.android.com | general API knowledge; not re-fetched today |

Abstracts for S2, S3 and S6–S9 come from the OpenAlex cache in `work/W08/literature_cache.json`
(read-only use of W08's output).

## 1. What the light does

The instantaneous power into a resistive or filament lamp goes as `v(t)^2`. So the light
output carries a component at **2·f_ENF**, which is about 100 Hz on a 50 Hz grid, plus weaker
harmonics at 200 Hz and above (S1 §II: "absolute cosine form of the illumination signal").
LED and CFL drivers can attenuate or reshape this ripple (S8: best results with halogen and
incandescent lamps; LED works only in ideal conditions). The ENF wander, roughly ±0.05–0.1 Hz,
therefore appears doubled, around 100 Hz.

## 2. Row-time model (rolling shutter)

A CMOS rolling shutter resets and reads the sensor one row at a time (S1 Fig. 1). For frame `k`
starting at `t_k`, with `H` rows:

```
t(k, r) = t_k + r · T_ro / H  (+ T_exp/2 if we refer to the exposure centre)
T_frame = 1/fps = T_ro + T_idle
```

`T_ro` is the frame read-out time, a camera- and mode-specific parameter (S3). `T_idle` is the
blank period between the last row of one frame and the first row of the next, during which no
light is sampled. S1 writes this with `M` = rows that could be read in one frame period and
`L` = actual rows. The idle fraction is `(M − L)/M`, so `T_ro = (L/M)·T_frame`.

Each row also integrates light for `T_exp`. A sinusoid at `f` is multiplied by
`sinc(f·T_exp) = sin(π f T_exp)/(π f T_exp)` and delayed by `T_exp/2` **[derived, standard]**.

Consequences:

* **Rows sample the flicker much faster than the frame rate.** The effective rate is about
  `H / T_ro`, for example 720 rows / 25 ms ≈ 29 kHz. That is far above Nyquist for 100 Hz, so
  the true 100 Hz line can be observed without temporal aliasing (S1 §II, S2). Within one frame,
  the flicker appears as **horizontal bands** with `f · T_ro` cycles per frame height (≈2.5
  bands for T_ro = 25 ms).
* **The idle gap matters.** If rows are *concatenated directly*, ignoring the idle gap, the
  100 Hz line is replaced by components at `f_y = f0 ± m·Fr` (S1 eq. 21). For 30 fps on a
  50 Hz grid, the strongest component moves from 100 Hz to 70, 40 and 10 Hz at 15 %, 45 % and
  75 % idle (S1 Fig. 6), and its power drops as the idle period grows. S1's measured examples:
  Canon PowerShot SX230HS at 30 fps had about 48 % idle (480p) and 38 % idle (720p). Nikon
  D3100 at 720p had about 4 % idle at 30 fps and 23 % at 23.976 fps (S1 Figs. 7–8). Idle time
  therefore depends on camera, resolution and frame rate.
* **Fixing the gap.** S6 proposes **periodic zeroing-out**: insert zeros for the idle samples.
  This needs `T_ro`, but the strongest component then stays at the true frequency, with no
  distortion (S6 abstract). Our extractor implements the equivalent operation.
  * Each row sample sits at its **true time** `t(k, r)`.
  * We heterodyne by `exp(−j2π f0 t)` and sum the rows of each frame. This is a non-uniform DFT
    in which the idle gap is simply absent.
* **Estimating T_ro.** S3 estimates `T_ro` from the *vertical phase* of the alias tone in each
  row's time series. S1 restates this as `T_ro = L·ω_b/(2π·f_e)` (eq. 23), and S3 reports
  relative error within 1.5 % (abstract). S1 notes that this fails when the frame rate divides
  the nominal ENF, because the alias sits at 0 Hz.
  * We use a frame-rate-independent search instead. For each candidate `T_ro`, form the
    baseband series and measure how sharp its spectral peak is near 0 Hz (that is, near f0).
  * A wrong `T_ro` mis-phases the rows within a frame, which smears and attenuates the peak.

## 3. Why per-frame mean brightness aliases (the naive method)

Averaging the whole steady region per frame gives **one sample per frame**, so the sampling rate
is `fps` (S1 §I; S4 eq. 2: `f_E = |f_l − γ f_s|`):

| fps | 100 Hz light appears at | Note |
|---|---|---|
| 30 | 10 Hz | S4 Table 1 |
| 29.97 | 10.09 Hz | S4 Table 1 |
| 60 | 20 Hz | |
| 24 | 4 Hz | |
| **25** | **0 Hz** | **degenerate** |
| 50 | 0 Hz | degenerate |

At 25 fps (PAL, and many EU phone and CCTV defaults) the flicker folds onto DC:

* it is indistinguishable from scene brightness, auto-exposure drift and the static scene;
* the sign of the ENF deviation is lost (`+δ` and `−δ` fold to the same `|2δ|`).

S1 makes this point explicitly against S3's vertical-phase method ("inapplicable to videos where
the frame rate is a divisor of nominal ENF").

**[derived]** With a rolling shutter, the frame mean is not even a point sample. It averages the
flicker over the read-out window, so the 100 Hz term is multiplied by `|sinc(f0·T_ro)|`. That
factor is **zero whenever T_ro is a multiple of 10 ms**, for example a 30 ms read-out at 30 fps.
The naive method can therefore fail at a "good" frame rate as well.

**[derived]** In the rolling-shutter heterodyne, the static scene `S(r)` maps to
`C·exp(−j2π f0 t_k)`. Its frequency is `−f0` aliased by fps: −10 Hz at 30 fps and 0 Hz at 25 fps.
* At 30 and 60 fps it lies outside the ±0.5 Hz search band, so scene texture is rejected
  automatically.
* At 25 fps it collides with the signal. The only remedy is temporal mean removal, which is a
  high-pass in baseband. ENF deviations whose doubled offset `|2δ|` is below about 1/(mean
  window) are therefore suppressed.
* This is the same frame-rate-comb confound S9 warns about: a harmonic of fps landing on 100 Hz
  can make the estimator report "50.000 Hz" with confidence. **A 25 fps or 50 fps clip cannot be
  trusted unless band drift is visible and the trace is not stuck at exactly nominal.**

## 4. Phone anti-flicker (anti-banding) auto-exposure

Phones deliberately suppress the banding we want. With anti-banding in 50 Hz or AUTO mode (S10),
auto-exposure prefers exposure times that are integer multiples of 1/100 s. At those values
`sinc(100·T_exp) = 0`, so each row integrates a whole number of flicker cycles and the bands
vanish **[derived from §2]**. In practice:

* **Dim indoor scene → T_exp ≥ 10 ms → bands cancelled → no visual ENF.** This is the default
  failure for a judge's phone.
* **Bright scene, or manual/"pro" shutter 1/500–1/2000 s →** `sinc` close to 1, so the bands
  survive. Some third-party apps can also set the anti-banding mode to OFF.
* Auto-exposure also changes `T_exp` and gain mid-clip. Our relative (divide-by-temporal-mean)
  normalisation absorbs slow gain drift. Exposure steps, however, change the flicker amplitude
  and phase.
* VFR and timestamp jitter: phone MP4s carry millisecond-quantised PTS. At 100 Hz, 1 ms is 0.63
  rad of phase. We therefore fit a straight line to the PTS, assuming a steady sensor clock, and
  report the residual. True VFR (dropped or duplicated frames) breaks that assumption.

## 5. Algorithm implemented (`rs_enf.py`)

1. **Decode.** Extract the Y plane and average it into cells of 4 rows × W/16 columns. This
   keeps the row resolution needed for the row-time model.
2. **Timing.** Robust linear fit of PTS → `t_k` and fps. Report the residual and dt statistics.
3. **Static mask.** Drop cells whose mean is below 30 or above 225 (tv-range Y), or with more
   than 2 % clipped pixels.
4. **Scene removal.** Each cell is divided by its temporal mean, minus 1. This removes the
   temporal mean image in relative terms and absorbs slow auto-exposure drift.
   * Normal frame rates: a 60 s moving mean.
   * Degenerate fps (fps divides f0): the whole-clip mean, because there the flicker is nearly
     static in each cell.
5. **Row signal.** Per frame and row group, take the **median across good column blocks**. This
   is robust to moving objects that cover fewer than half of the columns.
6. **Heterodyne.**
   `z_k = mean_r s[k,r]·exp(−j2π f0 (t_k + y_r T_ro/H))`.
   * At degenerate fps only, the whole-clip mean of `z` is subtracted, because the static scene
     lands on 0 Hz there.
   * At 30 and 60 fps nothing is subtracted. A 60 s high-pass was measured to cost accuracy:
     SYNTHETIC RMSE 0.34 → 3.27 mHz.
7. **T_ro.** Grid search from 0.5 ms to 1/fps in 0.25 ms steps. The default prior is a
   top-to-bottom read-out. `--allow-negative-tro` also searches a bottom-up scan, but at
   degenerate fps the two directions tie and the ENF sign flips (FAILURES.md F4). The objective
   is the mean over 16 s windows (4 s hop, first 180 s) of (peak power in |f|<0.5 Hz) /
   (median power).
8. **Track.** 16 s Hann STFT with 1 s hop, zero-padded to at most 2 mHz bins, with quadratic
   peak interpolation. Then `f_light = f0 + f_bb`, `ENF = f_light/2` and
   `q = 10·log10(peak/median)`.
9. **Baselines.**
   * **Naive:** same static mask, plain whole-frame mean per frame, the same STFT tracker
     searching ±0.5 Hz around the alias, then unfolded (`f_light = n·fps ± f_alias`).
   * **Strip-wise alias:** 45 horizontal strips, each sampled once per frame, so it avoids the
     `sinc(f0·T_ro)` cancellation. The per-strip power spectra are summed incoherently around
     the alias. This is close in spirit to the per-row time series of S3. It is still
     degenerate at 25 fps.
10. **Reference.** STFT of the 1 kHz mains WAV (decimated to 250 Hz) around 50 Hz with the same
    window and hop. Comparison uses interpolation at `t_video + lag`.
    * The lag implied by the filename timestamps is 70 s.
    * The correlation search picks 81.5 s on the real clip (FAILURES.md F1).
