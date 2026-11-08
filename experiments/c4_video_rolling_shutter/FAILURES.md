# C4 failure analysis (honest)

Each item states what failed or could mislead, the evidence, and what we did about it.
Numbers come from `RESULTS.json`. "SYNTH" means synthetic data.

## Real Zenodo MOV2 clip

**F1. The filename timestamps do not give the correct alignment.**
* Evidence:
  * At the filename-implied lag of 70 s (video 20:04:50, WAV 20:03:40), the rolling-shutter
    trace reaches only r = 0.645 against the reference.
  * The correlation peaks at a lag of 81.5 s (r = 0.995). That lag is unique over the whole
    feasible range of 0–252.5 s; the best value more than 10 s away is 0.685.
  * The dataset README only says the recording times are "very similar".
* Consequence: the lag was chosen by maximising correlation (one free parameter), so r = 0.995
  is a matched-lag figure.
* For GhostClock this is in fact the intended use: **ENF localises the clip in time**. Here it
  says the video started about 11.5 s later than the filename stamps imply.
* Which clock was wrong is not known: the phone or the Raspberry Pi reference recorder.

**F2. There is a constant +4.35 mHz bias (87 ppm of 50 Hz).**
* Evidence: the rolling-shutter and strip-wise methods show the same bias (4.35 and 4.34 mHz).
  On synthetic data the extractor bias is at most 0.03 mHz.
* Interpretation: this is a timebase mismatch, not an extraction error. Either the phone's PTS
  clock or the reference ADC's 1 kHz sample clock runs about 87 ppm off. We cannot tell which.
* Consequence: for absolute-frequency claims, report the debiased RMSE (1.07 mHz) or let
  the matcher fit an offset. Correlation-based matching is unaffected.

**F3. The naive whole-frame mean fails on this clip (r = 0.38, median q 14 dB).**
* Cause:
  * T_ro = 28.25 ms, so the frame mean integrates 2.8 flicker cycles, and the 100 Hz term is
    scaled by |sinc(2.825)| ≈ 0.06.
  * Whole-frame averaging also lets the walking person's brightness changes in.
* The strip-wise alias baseline avoids both problems and matches the rolling-shutter extractor
  at 30 fps (r = 0.9967). **The rolling-shutter extractor is therefore not uniquely necessary
  on this real clip.** Its advantage on real data is a 15 dB higher q and an explicit T_ro
  estimate.

**Limits of what was tested.**
* Only **one** real video was processed, the smallest of eight (1.2 GB). We did not download the
  other 20 GB, by instruction.
* All Zenodo videos appear to be from the same set-up, so lamp, camera and room do not vary.
* No 25 fps real video was available, so the main claimed advantage of the rolling-shutter
  method rests on synthetic data only.

## Method failure modes (SYNTH evidence)

**F4. The read-out direction is ambiguous at degenerate frame rates.**
* At 25 fps on a 50 Hz grid, the T_ro search scores +T_ro and −T_ro identically (ratio
  0.9999999999).
  * In synthetic run 1 the bidirectional search picked −25.25 ms and returned a
    **sign-flipped ENF (r = −0.949)**; archived in `synth/old_pm_search_hp/`.
  * At 30 fps the mirror scores only 0.005 of the true direction (real and synthetic), so the
    direction is identifiable there.
* Mitigation: the default prior is top-to-bottom read-out (T_ro > 0).
* Residual risk: video rotated or transposed after capture, or a sensor mounted upside down. In
  those cases a 25 fps trace may be mirrored around 50 Hz. Report both candidates when fps
  divides 2·f_grid.

**F5. The degenerate frame rate (25/50 fps) is also a scene-removal problem.**
* The static scene lands on 0 Hz together with the signal, so only the whole-clip mean can be
  removed.
* ENF deviations that stay near nominal for the whole clip, or a clip much shorter than
  1/|2δ|, are suppressed.
* The extractor can lock onto exactly 100.000 Hz, which is the frame-rate comb. Wyton & Rehman
  (arXiv:2610.20549) describe this confound.
* On synthetic data (OU ENF wandering ±tens of mHz) it worked: r = 0.986. This is not
  validated on real 25 fps footage.
* **A trace that sits at exactly 50.000 Hz from a 25/50 fps clip should be treated as "no
  information".**

**F6. Anti-banding exposure kills the signal (negative control).**
* With T_exp = 10 ms, sinc(100·0.01) = 0. All methods fail:
  * rolling-shutter r = −0.22;
  * the T_ro estimate is meaningless (6.25 ms against a true 25 ms);
  * q collapses to 3.9 dB.
* This is the default behaviour of phone auto-exposure in dim 50 Hz-lit rooms (METHOD §4).

**F7. Weak flicker plus heavy compression gives no signal.**
* SYNTH case: 1 % modulation at CRF 28 gives r = 0.11 and q = 3.6 dB.
* For comparison, the real clip shows bands of about ±1–3 grey levels and gives q = 45 dB.
* **Gate on q.** On synthetic data, working cases have q ≥ 42 dB and failing cases have
  q ≤ 4 dB. A 20 dB threshold is a reasonable start, but it is **not calibrated on real
  negatives**.

**F8. The first implementation's 60 s high-pass on the baseband hurt accuracy.**
* SYNTH fps30: RMSE 3.27 mHz with the high-pass, 0.34 mHz without it.
* Fixed: whole-clip mean removal, and only at degenerate fps. Ablation is in progress.md.

**F9. Timing assumptions.**
* The extractor fits a straight line to the PTS. On the real clip the residual is 0.30 ms RMS
  with no steps.
* True VFR could break the row-time model: phone thermal throttling, dropped frames, or
  re-encoding by messaging apps. At 100 Hz, a 1 ms timing error is 0.63 rad of phase.
* The extractor reports PTS jitter in its output. It does **not** yet detect dropped frames.

**F10. Motion.**
* A median across 16 column blocks tolerates movers that cover less than half of a row.
* Frame-wide motion is not handled: camera pans or a person filling the frame.
* The per-frame motion score is computed but not yet used to down-weight frames.
* MOV3 ("almost all frames contain movement") was **not** tested.

**F11. Other things not handled.**
* Lighting:
  * LED lamps with constant-current drivers produce no 100 Hz ripple.
  * Mixed daylight dilutes the modulation.
* Camera processing:
  * Auto-exposure steps mid-clip (sudden changes in amplitude and phase).
  * HDR or multi-frame phone video pipelines that fuse exposures.
* Rotation metadata is not checked by `rs_enf.py`. The extractor assumes the stored rows are
  the sensor rows.

## Conditions for a judge's phone video to work (derived from the above)

1. **A mains-powered lamp lights the scene** and it has 100 Hz ripple. Incandescent or halogen
   is best (Frijters & Geradts 2022). Cheap LED or CFL may work. Avoid daylight.
2. **Short exposure, which defeats anti-banding.**
   * Use a pro or manual mode with a shutter of 1/500–1/2000 s, or a scene bright enough that
     auto-exposure goes below 1/100 s.
   * Lock auto-exposure and ISO.
   * Never use exactly 1/100, 1/50 or 1/33 s.
3. **30 fps (or 60/24 fps), constant frame rate.**
   * Avoid 25/50 fps on a 50 Hz grid. The rolling-shutter method can handle it in principle,
     but the result is sign-ambiguous and fragile (F4, F5).
4. **A static camera on a tripod**, pointed at a plain, matte, evenly lit wall or ceiling. Keep
   it unclipped (no lamp in frame) and not dark. Movers may cross part of the frame.
5. **Duration of at least 5–10 minutes.**
   * The ENF wanders only about 10–20 mHz per minute, so a unique time match needs several
     minutes of trace. The real clip was 10.8 min and its peak correlation was unique.
   * Our window is 16 s.
6. **Keep the original file.**
   * Send it as a file, not through WhatsApp or Instagram re-encoding.
   * Keep its PTS and do not rotate or crop it.
7. **Check q before claiming anything.** Median q should be at least about 20 dB, and the trace
   must not be pinned at exactly 50.000 Hz.
