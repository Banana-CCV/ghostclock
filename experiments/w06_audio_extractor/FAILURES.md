# W06 Failure Analysis, Critiques & Risk Controls (`work/W06/FAILURES.md`)

**Evidence Grade:** `B` (Executed with reproducible logs across the full 108-case ENF-WHU Dev split; smoke test independently reproduced by Director in `agents/reviews/director_verify_w06.py`).

---

## 1. Dataset Alignment Discovery: Per-File Lag Offsets in ENF-WHU (`H1` vs. `H1_ref`)

### Phenomenon Observed
During independent verification of our smoke test on `ENF-WHU H1/003.wav` vs. `H1_ref/003_ref.wav` (`agents/reviews/director_verify_w06.py`), zero-lag comparison at matching window centers $t_m = m \cdot \text{hop\_s} + \frac{\text{window\_s}}{2}$ yielded $r = 0.9760$ and $\text{RMSE} = 5.48\text{ mHz}$, whereas shifting by $4\text{ s}$ increased correlation to $r = 0.9986\text{–}0.9994$ and reduced demeaned RMSE to $< 1.5\text{ mHz}$.

### Root-Cause Diagnosis (`work/W06/diagnose_lag.py` & `work/W06/lag_diagnosis.json`)
We tested three competing hypotheses: (a) a window-center convention error in `t`, (b) filter group delay in downsampling or bandpass filtering, or (c) an intrinsic per-file start-time trimming offset between `H1/<id>.wav` and `H1_ref/<id>_ref.wav` in the ENF-WHU dataset:
1. **Synthetic Ground-Truth FM Verification (Hypotheses A & B Falsified)**:
   - On a $300\text{ s}$, $8000\text{ Hz}$ synthetic multi-harmonic FM signal ($h \in \{2, 4, 6\}$) with known instantaneous frequency $f_{\text{true}}(t)$, the complete `work/W06/audio_enf.py` pipeline (`ffmpeg` decode $\rightarrow$ `resample_poly` anti-alias decimation to $1000\text{ Hz}$ $\rightarrow$ zero-phase `sosfiltfilt` Butterworth bandpass $\rightarrow$ $16\text{ s}$ Hann STFT at window centers $t_m$) peaks at **exact lag $0\text{ s}$** (`corr_by_lag_s`: `-1s: 0.9761`, **`0s: 0.9937`**, `+1s: 0.9758`). Zero-phase forward-backward filtering (`sosfiltfilt`) and centered polyphase FIR decimation introduce **$0.000\text{ s}$ group delay**.
2. **Unfiltered Raw STFT Verification on `H1/003.wav` (Hypothesis C Confirmed)**:
   - Running `scipy.signal.stft(..., boundary=None, padded=False)` directly on raw $8000\text{ Hz}$ `H1/003.wav` ($200\text{ Hz}$ 4th harmonic, with zero W06 code, no downsampling, and no bandpass filter) against `H1_ref/003_ref.wav` ($50\text{ Hz}$) exhibits the **exact same $3\text{–}4\text{ s}$ lag** (`r = 0.9675` at lag $0\text{ s}$ vs. `r = 0.9863` at lag $-3\text{ to }-4\text{ s}$), and the raw file durations themselves differ by $0.93\text{ s}$ (`652.9306 s` vs. `652.0025 s`).
3. **Full Dev Split Lag Distribution (`75/78` Dev `H1` recordings with $r \ge 0.70$)**:
   - Histogram of optimal lag (in seconds): `{"-5": 1, "-4": 8, "-3": 18, "-2": 6, "-1": 7, "0": 13, "1": 14, "2": 3, "3": 3, "4": 2}`.
   - `100.0%` (`75/75`) fall within $\pm 5\text{ s}$ (`median_lag_s = -1.0 s`, `median_abs_lag_s = 2.0 s`, `p90_abs_lag_s = 4.0 s`, `frac_within_1s = 45.3%`, `frac_within_2s = 57.3%`, `frac_within_5s = 100.0%`).
   - Across all 78 Dev `H1` clips, accounting for this per-file dataset offset improves median Pearson $r$ from **`0.9841` (strict lag 0)** to **`0.9956` (per-file refined lag within $\pm 5\text{ s}$)** and lowers median RMSE from **`3.47 mHz` (strict lag 0)** to **`1.92 mHz`**.
   - **Rule Enforced**: Primary evaluation uses $\pm 5\text{ s}$ as the timestamp tolerance on ENF-WHU; both strict zero-lag and per-file lag-refined metrics are explicitly separated and labeled in `RESULTS.json`.

---

## 2. Real Dev `H1` Failure Cases (`H1/014.wav`, `H1/128.wav`, `H1/035.wav`)

### Case A: `ENF-WHU H1/014.wav` — Total Extraction Breakdown under Low Harmonic SNR ($r = 0.0883$, $\text{RMSE} = 52.28\text{ mHz}$)
- **Measured Metrics**: On `H1/014.wav` (the single worst recording in the 78-clip Dev `H1` split), W06 yields $r = 0.0883$ (`r_best_lag = 0.0883`) and $\text{RMSE} = 52.28\text{ mHz}$.
- **Physical Cause**: `014.wav` has the lowest effective harmonic SNR (`8.61 dB`), lowest median frame quality (`median_q = 0.7118` vs. Dev median `0.989`), and lowest ENF-presence score (`0.5294`) in Dev `H1`. Broadband environmental noise and voice formants mask the mains harmonics across most of the recording, causing the local STFT peak to wander across the $\pm 120\text{ mHz}$ search band.
- **Downstream Protection**: Because the extracted trace has no coherent trajectory correlation with the reference, `W10`'s Bartlett-calibrated matcher (`p_empirical <= 0.01`, `best.score >= 0.45`, `split_half_consistent`) cleanly routes `014.wav` to **`INCONCLUSIVE`** rather than a false match or false contradiction.

### Case B: `ENF-WHU H1/128.wav` & `H1/035.wav` — Partial Masking & Larger Start-Trimming Offset ($r = 0.500\text{–}0.540$)
- **Measured Metrics**:
  - `H1/128.wav`: Zero-lag $r = 0.4999$, $\text{RMSE} = 12.95\text{ mHz}$ (improves to $r = 0.5539$, $\text{RMSE} = 12.28\text{ mHz}$ at lag $+6\text{ s}$).
  - `H1/035.wav`: Zero-lag $r = 0.5405$, $\text{RMSE} = 19.17\text{ mHz}$ (improves to $r = 0.6142$, $\text{RMSE} = 17.70\text{ mHz}$ at lag $-6\text{ s}$).
- **Physical Cause**: Intermittent foreground acoustic transients corrupt interior segments of the trace while both files also sit at the $\pm 6\text{ s}$ tail of ENF-WHU's manual start-time trimming offset.

---

## 3. Real Dev `H0` False-Positive Case: Parent Recording `O07` Crops (`31.wav–36.wav`)

### Phenomenon Observed
In Experiment 3 (ENF-Presence Detection on 78 Dev `H1` vs. 30 Dev `H0`), while W06's composite detector achieves **`ROC AUC = 0.9910`** and **`TPR = 96.15%` (`75/78`) at `5%` FPR**, inspecting `hardest_5_dev_h0` in `RESULTS.json` reveals that the highest-scoring negative files (`33.wav`: score `0.7596`; `36.wav`: `0.7495`; `31.wav`: `0.7466`; `35.wav`: `0.7183`; `34.wav`: `0.7050`) **all originate from the same parent recording `O07.wav`**.

### Root-Cause Diagnosis & Architectural Lesson
- Inspecting the per-component scores on `31.wav–36.wav` (`O07` crops) shows:
  - `best_harmonic = 4` ($200\text{ Hz}$) with `best_harmonic_snr_db = 9.04–9.81 dB` and low single-band variance (`tf_variance_hz2 = 0.00056–0.00096`), giving high `snr_score` (`0.81–0.87`) and `stability_score` (`0.77–0.85`).
  - **Crucially, however, `coherence_score` is very low (`0.295–0.309`)** compared to genuine multi-harmonic `H1` recordings (`0.70–0.92`)!
- **Why**: `O07.wav` contains a single stationary narrowband electronic/mechanical whine near $200\text{ Hz}$ that is **not** accompanied by coherent $100\text{ Hz}$ or $300\text{ Hz}$ grid harmonics.
- **Why Presence $\neq$ Dating (Scientific Ground Truth #2)**: Even though `O07`'s $200\text{ Hz}$ stationary whine triggers a narrowband presence alert at the permissive `0.48` screening threshold, a stationary tone has zero correlation with historical grid frequency fluctuations (`W10` matcher rejects flat/uncorrelated traces via `min_trace_std_mhz` and Bartlett $p_{\text{empirical}} \le 0.01$).

---

## 4. Failure Mode: Corrupted Harmonics & Fundamental $50\text{ Hz}$ Attenuation

1. **Fundamental $50\text{ Hz}$ Collapse (`single_50hz`)**:
   - Across all 78 Dev `H1` recordings, `single_50hz` achieves a median correlation of only **`r = 0.1108`** and median **`RMSE = 68.12 mHz`** (`0/78` clips with $r \ge 0.80$), because smartphone microphones strongly high-pass filter $50\text{ Hz}$.
2. **Unweighted Multi-Harmonic Collapse (`unweighted_mean`)**:
   - Averaging harmonics $[1..6]$ with equal weights yields median **`r = 0.4679`** and median **`RMSE = 23.32 mHz`** (`9/78` clips with $r \ge 0.80$), because noisy/absent harmonics ($h=1, 3, 5$) corrupt the clean harmonics ($h=2, 4, 6$).
3. **Severe Broadband Noise Breakdown (`AWGN -15 dB`)**:
   - Under synthetic additive white Gaussian noise at `-15 dB` broadband SNR, median correlation drops from `0.9727` (at `-10 dB`) to `0.6370` (RMSE `18.32 mHz`) as weaker secondary harmonics fall below the STFT noise threshold before the dominant $100\text{ Hz}$ component.
