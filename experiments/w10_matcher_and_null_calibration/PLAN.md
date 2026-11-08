# W10 Plan — Forensic ENF Matcher, Empirical Calibration & Decision Policy

## 1. Literature & Prior Art Synthesis (Step B)
We ground our matcher, statistical calibration, and evaluation protocol in five primary sources and two open-source baselines verified on disk:

1. **Hua et al. (2021)** — G. Hua, H. Liao, H. Zhang, D. Ye, and J. Ma, *"Robust ENF estimation based on harmonic enhancement and maximum weight clique,"* IEEE Trans. Inf. Forensics Security (TIFS), vol. 16, pp. 3874–3886, 2021, DOI: `10.1109/TIFS.2021.3099697`.
   - **Verified on disk** (`datasets/raw/enf-whu/repo/ENF_Enhancement_Estimation/main_comparison_recording_all.m` & `func_empirical_coeff_thre.m`): Uses $16\,\text{s}$ STFT frames with $1\,\text{s}$ step size ($f_s = 800\,\text{Hz}$ for audio, $400\,\text{Hz}$ for reference) and quadratic FFT interpolation (`fun_STFT_interpo.m`). Crucially, we audited `func_empirical_coeff_thre.m` and line 119 of `main_comparison_recording_all.m`: their empirical correlation threshold generates i.i.d. white Gaussian noise `randn(1, N)` over 10,000 trials and then **multiplies the max correlation by an ad-hoc factor of 4** (`*4`) because i.i.d. noise ignores the strong temporal autocorrelation of ENF traces.
2. **Hua et al. (2021b)** — G. Hua, H. Liao, Q. Wang, H. Zhang, and D. Ye, *"Detection of electric network frequency in audio recordings – From theory to practical detectors,"* IEEE Trans. Inf. Forensics Security (TIFS), vol. 16, pp. 236–248, 2021, DOI: `10.1109/TIFS.2020.3009579`.
   - **Verified on disk** (`datasets/raw/enf-whu/repo/ENF_Detection/Fig12_and_13_real_world_recording_acc_vs_length.m`): Introduces the ENF-WHU dataset (130 $H_1$ positive audio clips, 130 $H_1$ aligned reference WAVs, 28 $H_1$ 24-hour reference WAVs, and 50 $H_0$ negative audio clips without ENF). Demonstrates that time-frequency variance and LRT detectors require clip durations $\ge 30\text{–}120\,\text{s}$ on real-world recordings to separate $H_1$ from $H_0$.
3. **Hua (2018)** — G. Hua, *"Error analysis of forensic ENF matching,"* Proc. 2018 IEEE Int. Workshop on Information Forensics and Security (WIFS), Hong Kong, pp. 1–7, Dec. 2018, DOI: `10.1109/WIFS.2018.8630786`.
   - Establishes that ENF matching via maximum cross-correlation (MCC) and minimum mean squared error (MMSE) over a search window of size $M$ is governed by the SNR of the extracted trace, the clip length $L$, the temporal autocorrelation of grid frequency fluctuations, and the competing peak distribution across the $M$ candidate lags.
4. **Bartlett (1946) / Bayley & Hammersley (1946)** — M. S. Bartlett, *"On the theoretical specification and sampling properties of autocorrelated time-series,"* Supplement to the Journal of the Royal Statistical Society, vol. 8, no. 1, pp. 27–41, 1946, DOI: `10.2307/2983611`; G. V. Bayley and J. M. Hammersley, *"The 'effective' number of independent observations in an autocorrelated time series,"* Suppl. J. Roy. Stat. Soc., vol. 8, no. 2, pp. 184–197, 1946.
   - Provides the variance of sample cross-correlation between two independent, autocorrelated stationary processes $x_t, y_t$:
     $$\text{Var}(r) \approx \frac{1}{N_{\text{eff}}} = \frac{1}{N} \sum_{k=-K}^{K} \left(1 - \frac{|k|}{N}\right) \hat{\rho}_{xx}(k)\hat{\rho}_{yy}(k)$$
     Replacing ad-hoc multipliers (like Hua's `*4`) with Bartlett's $N_{\text{eff}}$ directly accounts for both grid autocorrelation and STFT window overlap.
5. **Garg, Varna, & Wu (2011) / Hajj-Ahmad et al. (2013)** — R. Garg, A. L. Varna, and M. Wu, *"Seeing ENF: Natural time-stamp for digital video via optical sensing and signal processing,"* Proc. ACM Multimedia, pp. 23–32, 2011, DOI: `10.1145/2072298.2072303`; A. Hajj-Ahmad, R. Garg, and M. Wu, *"Spectrum combining for ENF signal estimation,"* IEEE Signal Process. Lett., vol. 20, no. 9, pp. 885–888, 2013, DOI: `10.1109/LSP.2013.2272522`.
   - Demonstrates SNR-weighted harmonic combining and highlights that audio and visual ENF sense the same underlying power grid waveform (thus sharing environmental/grid confounds).
6. **Open-Source Baselines Audited on Disk (`work/W05/third_party/`)**:
   - **`nate-griff/enf` (`enf_compare.py`)**: Uses unweighted FFT Pearson correlation + raw uncentered threshold coverage (`0.4 * corr + 0.6 * coverage`), drops `NaN` rows via `dropna()` (breaking time alignment when interior windows are invalid!), uses only `5.0 s` peak separation (allowing sidelobes of the same peak as "second-best"), and provides no p-values, no $N_{\text{eff}}$, and no abstention gate.
   - **`CoRoe/enf-matching` (`scripts/correlate.py`)**: Toy $O(R \cdot L)$ loop calling `np.corrcoef` per lag with no statistical calibration or gap handling.

---

## 2. Algorithmic Design of `work/W10/matcher.py`
We implement `match(trace, reference, search_start_utc, search_end_utc, config)` adhering strictly to `integration/interfaces.md` §3:

1. **Common Cadence Resampling & Masking**:
   - Regularise `reference` (`ts_utc`, `f_hz`) onto a uniform grid with step $\Delta t = \text{cadence\_s}$ (default $1.0\,\text{s}$ for NESO / ENF-WHU; $15.0\,\text{s}$ for Elexon) over `[search_start_utc, search_end_utc]`. Missing reference intervals are marked with mask $m_y[n] = 0$ and never bridged across gaps $> 5\,\text{s}$.
   - Resample `trace` (`t`, `f`, `q`) onto the same relative step $\Delta t$ from $0$ to $D$. Windows with `NaN` frequency, $|f - f_0| > \text{max\_dev\_hz}$ (default $0.5\,\text{Hz}$), or $q < q_{\min}$ (default $0.05$) receive weight $w_x[k] = 0$ while **preserving their exact temporal index $k$** (never dropping rows and shifting lags). Valid windows receive weight $w_x[k] = \text{clip}(q[k], 0, 1)$.

2. **Fast FFT-Based Weighted Normalized Cross-Correlation (WNCC) & Offset-Adjusted MMSE**:
   - For query $x[0..L-1]$ with weights $w[0..L-1]$ ($\sum w > 0$) and reference $y[0..R-1]$ with validity mask $m[0..R-1]$:
   - At every candidate lag $\tau \in [0, R - L]$, the effective joint weight is $W_\tau[k] = w[k] \cdot m[\tau + k]$.
   - Using six 1D real FFT convolutions (`scipy.signal.fftconvolve` / `np.fft.rfft`), we compute in $O(R \log R)$ time for **all lags simultaneously**:
     - Effective weight sum: $S_W(\tau) = \sum_k W_\tau[k]$
     - Weighted query sums: $S_{WX}(\tau) = \sum_k W_\tau[k] x[k]$, $S_{WX^2}(\tau) = \sum_k W_\tau[k] x[k]^2$
     - Weighted reference sums: $S_{WY}(\tau) = \sum_k W_\tau[k] y[\tau+k]$, $S_{WY^2}(\tau) = \sum_k W_\tau[k] y[\tau+k]^2$
     - Weighted cross-product: $S_{WXY}(\tau) = \sum_k W_\tau[k] x[k] y[\tau+k]$
   - From these exact sufficient statistics at every lag $\tau$:
     - Local weighted means: $\mu_x(\tau) = S_{WX}(\tau)/S_W(\tau)$, $\mu_y(\tau) = S_{WY}(\tau)/S_W(\tau)$
     - Relative frequency offset (Hz): $\text{offset\_hz}(\tau) = \mu_x(\tau) - \mu_y(\tau)$
     - Centered weighted variances: $V_x(\tau) = S_{WX^2}(\tau) - S_W(\tau)\mu_x(\tau)^2$, $V_y(\tau) = S_{WY^2}(\tau) - S_W(\tau)\mu_y(\tau)^2$
     - Centered weighted covariance: $C_{xy}(\tau) = S_{WXY}(\tau) - S_W(\tau)\mu_x(\tau)\mu_y(\tau)$
     - **Weighted NCC**:
       $$r(\tau) = \frac{C_{xy}(\tau)}{\sqrt{V_x(\tau) V_y(\tau)}}$$
     - **Offset-Adjusted Weighted RMSE (mHz)** (equivalent to MMSE after removing crystal offset $\text{offset\_hz}(\tau)$):
       $$\text{rmse\_mhz}(\tau) = 1000 \times \sqrt{\frac{\max\left(0,\, V_x(\tau) + V_y(\tau) - 2 C_{xy}(\tau)\right)}{S_W(\tau)}}$$
   - Lags where valid overlap fraction $S_W(\tau) / \sum w < \text{min\_overlap\_frac}$ (default $0.70$) or $\sqrt{V_y(\tau)/S_W(\tau)} < \sigma_{y,\min}$ (default $0.5\,\text{mHz}$, flat-reference guard) are masked out ($r(\tau) = -\infty$).

3. **Optional Clock-Rate / Speed-Drift Search ($\pm 0.5\%$)**:
   - When `clock_drift_search=True` in `config`, we evaluate a grid of time-stretch factors $\alpha \in [-\alpha_{\max}, +\alpha_{\max}]$ (default $\pm 0.005$, i.e. $\pm 0.5\%$, across $K_\alpha = 21$ steps of $0.05\%$, or customizable).
   - For each $\alpha$, the query trace is resampled at $t' = t \cdot (1 + \alpha)$ and its frequency adjusted by $f' = f / (1 + \alpha)$ (or mean-centered before WNCC).
   - The number of drift hypotheses $K_\alpha$ multiplies the effective trial count $M_{\text{eff}}$ in the look-elsewhere p-value calculation so clock-drift search cannot inflate false positives!

4. **Non-Maximum Suppression (NMS) & Top-$K$ Candidates**:
   - Because ENF cross-correlation peaks have width $\sim 15\text{–}30\,\text{s}$, we apply greedy NMS with exclusion radius $\Delta_{\text{NMS}} = \max(\text{nms\_min\_s}, \text{nms\_frac} \times D)$ (default $\max(30\,\text{s}, 0.25 D)$).
   - Returns top-$K$ (default $K=5$) distinct non-overlapping candidates, plus `uniqueness`:
     - `margin_vs_second`: $r_1 - r_2$ (and ratio $r_1 / \max(r_2, \epsilon)$ in diagnostics)
     - `second_best_distance_s`: $|t_1 - t_2|$ in seconds.

5. **Sub-Sample Refinement**:
   - Around each top-$K$ peak $\tau_k$, fit a 3-point parabola to $(r(\tau_k-1), r(\tau_k), r(\tau_k+1))$:
     $$\delta = \frac{r(\tau_k-1) - r(\tau_k+1)}{2\left(r(\tau_k-1) - 2r(\tau_k) + r(\tau_k+1)\right)} \in [-0.5, +0.5]$$
     reporting integer `start_utc` in `best` (per `interfaces.md` §3 `int` schema) and `sub_sample_offset_s: float` in `diagnostics`.

6. **Split-Half Temporal Consistency Check**:
   - Split the query trace into first half $x_{1} = x[0:\lfloor L/2 \rfloor]$ and second half $x_{2} = x[\lfloor L/2 \rfloor : L]$.
   - Independently find the best lag $\tau^{(1)}$ for $x_1$ and $\tau^{(2)}$ for $x_2$ (adjusted by $\lfloor L/2 \rfloor \Delta t$) across the full search window.
   - Compute `split_half_agreement_s = abs(tau_1 - tau_2_adjusted)` and `split_half_consistent = (split_half_agreement_s <= tolerance_s)` (default $5\,\text{s}$), plus local correlations $r^{(1)}(\tau^*)$ and $r^{(2)}(\tau^*)$ at the full-trace best lag $\tau^*$.

7. **Empirical + Analytical Look-Elsewhere Calibration (`null` dict)**:
   - **Analytical Bartlett + Extreme-Value Null**:
     - Estimate autocorrelation $\hat{\rho}_{xx}(k)$ and $\hat{\rho}_{yy}(k)$ up to lag $K_{\text{acf}} = \min(120\,\text{s}, \lfloor L/2 \rfloor)$.
     - Compute Bartlett effective sample size:
       $$N_{\text{eff}} = \frac{N_{\text{valid}}}{1 + 2 \sum_{k=1}^{K_{\text{acf}}} \left(1 - \frac{k}{N_{\text{valid}}}\right) \hat{\rho}_{xx}(k)\hat{\rho}_{yy}(k)}$$
       clamped to $[4, N_{\text{valid}}]$.
     - Compute effective number of independent candidate peaks across the search window:
       $$\tau_{\text{decorr}} = 1 + 2 \sum_{k=1}^{K_{\text{acf}}} \max(0, \hat{\rho}_{xx}(k)\hat{\rho}_{yy}(k)), \qquad M_{\text{eff}} = \max\left(1,\, \frac{N_{\text{lags}}}{\tau_{\text{decorr}}} \times K_\alpha\right)$$
   - **Empirical Circular-Shift / Block-Permutation Null (computed per match)**:
     - Generate $N_{\text{null}}$ (default $\ge 200$, configurable) empirical null scores by matching the query against circularly shifted, time-reversed, and phase-randomized (AAFT / Fourier phase-scrambled preserving exact power spectrum and autocorrelation!) surrogates of the reference, plus off-peak background lags outside $\pm 2 D$ of top peaks.
     - Fit the null distribution $(\mu_0, \sigma_0)$ of individual lag correlations and verify against $1/\sqrt{N_{\text{eff}}}$.
     - Using Fisher $z$-transform $z = \text{arctanh}(r) \sim \mathcal{N}(0, \sigma_z^2)$ where $\sigma_z = \max(\sigma_{0,z}, 1/\sqrt{\max(N_{\text{eff}} - 3, 1)})$:
       - Single-lag tail probability: $p_{\text{local}} = 1 - \Phi(z_{\max} / \sigma_z)$
       - Look-elsewhere corrected p-value over $M_{\text{eff}}$ independent candidates:
         $$p_{\text{empirical}} = 1 - (1 - p_{\text{local}})^{M_{\text{eff}}} \approx \min\left(1.0,\, M_{\text{eff}} \cdot p_{\text{local}}\right)$$
       - Also compute direct Monte Carlo extreme-value p-value from phase-randomized reference surrogates when requested, and set `score_threshold` to the score required to achieve $p_{\text{empirical}} \le \alpha_{\text{target}}$ (default $\alpha_{\text{target}} = 0.01$).

---

## 3. Deterministic Decision Policy (`work/W10/policy.py`)
`evaluate_policy(match_result, trace_meta, claimed_start_utc=None, tolerance_s=60, config=None) -> dict`
- **Blindness**: `claimed_start_utc` is **never** passed to `match(...)` search; it is evaluated solely in `policy.py` after candidates and p-values are frozen.
- **Hard Numerical Gates (tuned on Dev only, never overridden by LLM)**:
  1. `min_valid_duration_s` $\ge 30.0\,\text{s}$ and `min_valid_fraction` $\ge 0.50$.
  2. `min_trace_std_mhz` $\ge 0.8\,\text{mHz}$ and `max_trace_std_mhz` $\le 150.0\,\text{mHz}$ (rejects flat synthetic tones and wild non-ENF random walk noise).
  3. `p_empirical` $\le 0.01$ (look-elsewhere corrected).
  4. `best.score` $\ge \max(\text{score\_threshold}, 0.45)$.
  5. `uniqueness.margin_vs_second` $\ge 0.08$ (or $r_1 / r_2 \ge 1.15$).
  6. `best.rmse_mhz` $\le 35.0\,\text{mHz}$ (after crystal offset removal).
  7. `split_half_consistent == True` (required for traces $\ge 120\,\text{s}$, or both halves $r^{(1)}, r^{(2)} \ge 0.35$ for shorter clips).
- **Decision Mapping**:
  - If any gate 1–7 fails $\rightarrow$ **`INCONCLUSIVE`** (even if a `claimed_start_utc` is supplied! Weak evidence can neither corroborate nor contradict a claim).
  - If all gates 1–7 pass:
    - If `claimed_start_utc is None` $\rightarrow$ **`MATCH_SUPPORTED`** (blind timestamp discovery supported).
    - If `claimed_start_utc is not None`:
      - Let $\Delta_{\text{claim}} = |\text{best.start\_utc} - \text{claimed\_start\_utc}|$.
      - If $\Delta_{\text{claim}} \le \text{tolerance\_s}$ $\rightarrow$ **`MATCH_SUPPORTED`**.
      - If $\Delta_{\text{claim}} > \text{tolerance\_s}$ $\rightarrow$ **`MATERIAL_DISCREPANCY_REVIEW`** (requires human review; never labels fraud).
- Every decision populates `status_reasons: list[str]` (exact numbers vs thresholds) and `what_would_change_this: list[str]` (exact counterfactual deltas needed to flip the status).

---

## 4. Datasets, Splits & Experiments
1. **Experiment 1 — GB NESO 1-Second Synthetic Benchmark & Calibration Curve**:
   - Load real GB NESO 1-second reference data (from W02's `datasets/raw/neso/` or direct NESO fetch).
   - **Dev Split**: First 15 days of the month; **Holdout Split**: Last 15 days of the month (strictly non-overlapping).
   - Cut synthetic traces across durations $D \in \{30, 60, 120, 300, 600\}\,\text{s}$, noise levels $\sigma \in \{1, 5, 10, 20, 50\}\,\text{mHz}$ (pink/AR(1) + white noise), missing/NaN dropout fractions $\{0\%, 20\%, 40\%\}$, and clock drifts $\alpha \in \{0\%, +0.2\%\}$.
   - Evaluate against 24-hour ($86,400\,\text{s}$) and 7-day ($604,800\,\text{s}$) search windows, plus wrong-month negative controls.
2. **Experiment 2 — ENF-WHU Real-World Audio Dataset (Dev vs Holdout)**:
   - Use W03's session-grouped split (or our verified 28-day-grouped split if W03 is still running, ensuring all recordings sharing the same `H1_ref_one_day` file stay in the same split, and all `H0` crops stay with their parent `O01..O10` recording).
   - **Positive controls ($H_1$)**: Match extracted traces (using W06/W07 audio extractor + our STFT harmonic baseline) against their true 24-hour reference (`H1_ref_one_day`).
   - **Negative controls ($H_0$ & Wrong-Day $H_1$)**:
     - Match all $H_0$ (no-ENF) recordings against 24-hour references.
     - Match $H_1$ recordings against **wrong** 24-hour reference days (`H1_ref_one_day` from a different day) and circularly shifted / phase-randomized references.
3. **Experiment 3 — Head-to-Head Baseline Comparison**:
   - Compare our `W10` matcher + policy against:
     - **Baseline 1 (`nate-griff/enf` matcher logic)**: Composite `0.4 * corr + 0.6 * uncentered_coverage` with `5s` separation and top-1 argmax (no abstention / fixed threshold).
     - **Baseline 2 (Naive i.i.d. Fisher-$z$ matcher)**: Standard Pearson correlation using nominal $N$ instead of Bartlett $N_{\text{eff}}$.

---

## 5. Falsifiable Success Thresholds
1. **False Positive Rate (FPR) on Negative Controls ($H_0$ + Wrong-Day $H_1$)**:
   - Our `W10` policy must achieve **FPR $\le 5.0\%$** (target $\le 2.0\%$) across all negative trials ($H_0$ and wrong-day $H_1$), whereas the naive i.i.d. baseline and uncalibrated open-source matcher are predicted to suffer FPR $> 25\%$ on wrong-day/H0 trials.
2. **Conditional Accuracy on Supported Matches (`Acc | MATCH_SUPPORTED`)**:
   - On NESO synthetic traces ($D \ge 120\,\text{s}, \sigma \le 10\,\text{mHz}$) and ENF-WHU Dev/Holdout clips where `status == MATCH_SUPPORTED`, timestamp accuracy within $|\hat{t} - t_{\text{true}}| \le 5\,\text{s}$ must be **$\ge 90.0\%$**.
3. **False Contradiction Rate (FCR) on Authentic Claimed Timestamps**:
   - When an authentic clip ($H_1$) is supplied with its true timestamp (`claimed_start_utc = t_true`), the rate of `MATERIAL_DISCREPANCY_REVIEW` (false contradiction) must be **$\le 2.0\%$** (noisy clips must abstain as `INCONCLUSIVE` rather than falsely contradicting a true claim!).

---

## 6. Expected Failure Modes
- **Very Short Clips ($D < 60\,\text{s}$) in Large Windows ($W \ge 24\,\text{h}$)**: Because grid frequency has decorrelation time $\tau_c \approx 15\text{–}25\,\text{s}$, a $30\,\text{s}$ clip has only $N_{\text{eff}} \approx 2\text{–}4$ effective degrees of freedom. Any random segment in a 24h window can correlate at $r > 0.90$ with a 3-DOF curve! Our Bartlett $N_{\text{eff}}$ + split-half gate is designed to catch this and force `INCONCLUSIVE`.
- **Harmonic Interference / Voice Formants**: In noisy outdoor or speech-heavy clips (several ENF-WHU $H_1$ clips), speech or fan motor tones corrupt individual STFT windows. Weighted NCC using per-window quality $q(t)$ mitigates burst corruption; if total valid duration drops below gate, the system abstains.
- **15-Second Reference Cadence (Elexon)**: At $\Delta t = 15\,\text{s}$, a $120\,\text{s}$ clip has only $9$ samples, making matching over 24 hours statistically underpowered unless clip duration is $\ge 600\,\text{s}$.
