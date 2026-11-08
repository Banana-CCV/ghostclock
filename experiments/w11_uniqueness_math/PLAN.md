# W11 Plan: Uniqueness & Feasibility Mathematics (NESO-based)

## 1. Orientation: Physical Constraints, Assumptions, and Falsification Criteria

### Physical & Statistical Constraints
1. **GB Grid Frequency Dynamics**: Great Britain's synchronous grid operates at nominal $f_0 = 50.0\text{ Hz}$ (operational band $\pm 0.2\text{ Hz}$, statutory band $\pm 0.5\text{ Hz}$). Instantaneous frequency deviations $x(t) = f(t) - 50.0\text{ Hz}$ reflect the real-time imbalance between generation and load damped by rotational turbine inertia and governor control.
2. **Autocorrelation vs. Naive Sample Count**: Because the grid has large inertia and continuous primary/secondary control, $x(t)$ is strongly autocorrelated with characteristic damping time $\tau_{\text{OU}} = 1/\gamma \approx 30\text{--}60\text{ s}$. Consequently, a segment of duration $D$ sampled at $R = 1\text{ s}$ ($N = D/R$ samples) does **not** possess $N$ independent degrees of freedom. Its effective degrees of freedom $N_{\text{eff}}(D, \sigma, R) \ll N$ govern the variance of cross-correlation scores against unrelated windows.
3. **Look-Elsewhere Effect in Search Windows $W$**: Searching a window of span $W$ at cadence $R$ evaluates $M = (W - D)/R + 1$ candidate lag positions. Because adjacent lags are themselves correlated, the maximum spurious correlation $r_{\max,\text{null}} = \max_{|t - t_0| > D} r(t)$ follows an extreme-value distribution determined by $N_{\text{eff}}$ and the effective number of independent candidate shifts $M_{\text{eff}}(W, D)$. Ignoring this look-elsewhere effect produces catastrophic false-positive rates on short clips ($D \le 1\text{ min}$) or wide windows ($W \ge 1\text{ day}$).
4. **Reference Cadence Constraint ($R = 1\text{ s}$ NESO vs. $R = 15\text{ s}$ Elexon)**: At $R = 15\text{ s}$, a $30\text{ s}$ clip contains only $N = 2$ samples (degenerate for zero-mean Pearson correlation, where $N=2$ always yields $r = \pm 1$), and a $1\text{ min}$ clip contains only $N = 4$ samples ($N - 2 = 2$ algebraic degrees of freedom). Whether Elexon $15\text{ s}$ data represents instantaneous point samples or $15\text{ s}$ averages further alters aliasing vs. smoothing of fast grid fluctuations.

### What Result Would Falsify Our Approach
- **Falsification of Analytic Theory**: If the Ornstein–Uhlenbeck / Bartlett effective-DoF + extreme-value analytic approximation fails to predict empirical Monte Carlo top-1 accuracy ($\text{MAE} > 0.08$) or the $95\text{th}$ percentile of best wrong-candidate scores ($\text{MAE} > 0.05$) on the unseen holdout month.
- **Falsification of Short-Clip / Same-Day Elexon Feasibility**: If at $R = 15\text{ s}$ (Elexon cadence), recordings of practical demo duration ($D \le 5\text{ min}$) under realistic extractor noise ($\sigma \ge 2\text{ mHz}$) fail to achieve $\ge 90\%$ accuracy or exhibit high false-match overlap against a $W = 1\text{ day}$ window, proving that same-day Elexon demos require longer durations ($D \ge 10\text{ min}$) or local $1\text{ s}$ reference monitoring.

---

## 2. Primary Literature Grounding (Step B Research)

1. **Grigoras, C. (2007)**. "Applications of ENF criterion in forensic audio, video, computer and telecommunication analysis." *Forensic Science International*, 167(2–3), 136–145. DOI: `10.1016/j.forsciint.2006.06.033`.
   - *Claim*: ENF traces matched via Pearson correlation or minimum MSE against reference databases can authenticate recording time, but short durations ($< 1\text{--}2\text{ min}$) risk false matches.
   - *Our Verification*: Quantify the exact probability of top-1 identification and false match across $D \in [30\text{ s}, 20\text{ min}]$ and $W \in [1\text{ h}, 1\text{ month}]$ on GB NESO data.
2. **Garg, R., Varna, A. L., & Wu, M. (2012)**. "Modeling and Analysis of Electric Network Frequency Signal for Timestamp Verification." *2012 IEEE International Workshop on Information Forensics and Security (WIFS)*, pp. 67–72. DOI: `10.1109/WIFS.2012.6412627`.
   - *Claim*: ENF fluctuations are well-modeled by an autoregressive $\text{AR}(p)$ process; raw cross-correlation suffers elevated false-alarm probability ($P_f$) due to ENF autocorrelation, whereas matching AR innovation (whitened/differenced) sequences increases effective degrees of freedom and lowers $P_f$ at shorter durations.
   - *Our Verification*: Implement both raw Pearson FFT cross-correlation (Baseline) and first-difference/AR(1)-whitened FFT cross-correlation (Iteration) to measure the empirical gain on real GB NESO data.
3. **Schäfer, B., Beck, C., Aihara, K., Witthaut, D., & Timme, M. (2018)**. "Non-Gaussian power grid frequency fluctuations characterized by Lévy-stable laws and superstatistics." *Nature Energy*, 3, 119–126. DOI: `10.1038/s41560-017-0058-z`.
4. **Gorjão, L. R., Jumar, R., Maass, H., Hagenmeyer, V., Yalcin, G. C., Kruse, J., Timme, M., Beck, C., Witthaut, D., & Schäfer, B. (2020)**. "Open database analysis of scaling and spatio-temporal properties of power grid frequencies." *Nature Communications*, 11, 6362. DOI: `10.1038/s41467-020-19732-7`.
   - *Claim*: GB grid frequency exhibits continuous-time Ornstein–Uhlenbeck mean reversion ($\text{d}x = -\gamma x\,\text{d}t + \sigma_{\text{OU}}\,\text{d}W_t$) at short lags, overlaid with deterministic power-trading dispatch steps every 30 and 60 minutes (GB Elexon half-hourly settlement periods).
   - *Our Verification*: Fit the OU damping rate $\gamma$, diffusion $\sigma_{\text{OU}}$, and full empirical autocorrelation function $\rho_{XX}(\tau)$ on NESO $1\text{ s}$ data, and test whether ENF segments spanning hourly/half-hourly settlement boundaries have higher variance and higher identification accuracy.
5. **Bartlett, M. S. (1935)**. "Some Aspects of the Time-Correlation Problem in Regard to Tests of Significance." *Journal of the Royal Statistical Society*, 98(3), 536–543. DOI: `10.2307/2342284`; and **Pyper, B. J., & Peterman, R. M. (1998)**. "Comparison of methods to account for autocorrelation in correlation analyses of fish data." *Canadian Journal of Fisheries and Aquatic Sciences*, 55(9), 2127–2140. DOI: `10.1139/f98-104`.
   - *Claim*: The variance of the sample cross-correlation $r$ between two uncorrelated series $X, Y$ of length $N$ with autocorrelations $\rho_{XX}(k), \rho_{YY}(k)$ is $\text{Var}(r) = 1/N_{\text{eff}}$, where:
     $$\frac{1}{N_{\text{eff}}} = \frac{1}{N} + \frac{2}{N^2}\sum_{k=1}^{N-1} (N - k)\rho_{XX}(k)\rho_{YY}(k)$$
   - *Our Verification*: Combine Bartlett's $N_{\text{eff}}$ with extreme-value statistics over $M_{\text{eff}}$ independent lag windows to predict the null maximum distribution $r_{\max,\text{null}}$ and compare directly against Monte Carlo simulations.

---

## 3. Dataset Acquisition & Dev/Holdout Split

- **Data Source**: NESO Historical 1-Second System Frequency Data (`https://api.neso.energy/api/3/action/datapackage_show?id=system-frequency-data`), Open Government / NESO Open Data Licence.
- **Storage**: If `datasets/raw/neso/` is not yet populated by W02, download directly via Python (`requests`) into `work/W11/data/` and record SHA-256 checksums, byte counts, URLs, and coverage in `work/W11/data/manifest.json`.
- **Strict Temporal Split**:
  - **Development Month (`dev`)**: **August 2026** (`fnew-2026-8.csv`, `2026-08-01T00:00:00Z` to `2026-08-31T23:59:59Z`, $2,678,400$ seconds). Used for OU/AR process fitting, autocorrelation estimation, look-elsewhere parameter calibration, and dev experiments.
  - **Holdout Month (`holdout`)**: **September 2026** (`fnew-2026-9.csv`, `2026-09-01T00:00:00Z` to `2026-09-30T23:59:59Z`, $2,592,000$ seconds). Held out completely from parameter fitting; used to evaluate the analytic model, minimum-duration rules, and abstention gates on unseen grid history.
- **Labelling Rule**: All reference series are **real** GB NESO 1 s measurements. All query segments with injected AWGN ($\sigma$), linear clock drift, or dropouts are explicitly labelled **`semi-synthetic`**.

---

## 4. Experimental Matrix & Methodology

### Parameter Grid
- **Segment duration $D$**: $\{30\text{ s}, 60\text{ s}, 120\text{ s}, 300\text{ s}, 600\text{ s}, 1200\text{ s}\}$ ($0.5, 1, 2, 5, 10, 20\text{ min}$).
- **Estimation noise $\sigma$ (AWGN)**: $\{0, 1, 2, 5, 10\}\text{ mHz}$ ($\{0.0, 0.001, 0.002, 0.005, 0.010\}\text{ Hz}$).
- **Extractor-like non-idealities (semi-synthetic stress suite)**:
  1. `awgn_only`: Zero-mean Gaussian white noise with standard deviation $\sigma$.
  2. `drift_50ppm`: Linear clock drift of $50\text{ ppm}$ (time-axis stretch by $1 + 5\times 10^{-5}$, causing up to $60\text{ ms}$ lag drift over $20\text{ min}$, plus $+2.5\text{ mHz}$ mean shift and slow random-walk wander of $1.5\text{ mHz}$ RMS).
  3. `dropouts_30pct`: $30\%$ of samples missing in random contiguous bursts ($5\text{--}20\text{ s}$ each), masked by zero-filling after mean-centering valid windows.
  4. `combined_realistic`: $\sigma = 2\text{ mHz}$ AWGN + $25\text{ ppm}$ drift + $20\%$ burst dropouts + $1\%$ impulse outliers ($\pm 15\text{ mHz}$).
- **Search window $W$**: $\{1\text{ h (3,600 s)}, 6\text{ h (21,600 s)}, 1\text{ day (86,400 s)}, 1\text{ week (604,800 s)}, 1\text{ month (full month)}\}$.
- **Reference cadence $R$**:
  1. `1s_neso`: Native $1\text{ s}$ resolution (query and reference at $1\text{ s}$).
  2. `15s_point`: Point-sampled every $15\text{ s}$ ($t \equiv 0 \pmod{15}$), testing instantaneous Elexon-like readings.
  3. `15s_avg`: Block-averaged over $15\text{ s}$ intervals, testing smoothed $15\text{ s}$ readings.
- **Monte Carlo Sample Size**: $N_{\text{trials}} = 250$ random true start times per $(D, \sigma, W, R)$ cell on the dev month (and $N_{\text{trials}} = 200$ on the holdout month), using FFT-accelerated sliding cross-correlation (`scipy.signal.fftconvolve` / `numpy.fft.rfft`) so full-month searches ($2.68 \times 10^6$ lags) execute rapidly.

### Baseline vs. Iteration (Step G)
- **Baseline Matcher**: Zero-mean unit-norm Pearson cross-correlation $r(k)$ computed via FFT over raw frequency series.
- **Iteration Matcher**: Hybrid / AR(1)-whitened cross-correlation combining raw Pearson $r_{\text{raw}}(k)$ and first-difference (velocity) cross-correlation $r_{\text{diff}}(k)$ (or innovation matching $x_t - \hat{\phi}_1 x_{t-1}$), which suppresses slow walk autocorrelation and sharpens lag localization.

---

## 5. Metrics, Schemas, and Falsifiable Success Thresholds

### Metrics Reported in `RESULTS.json`
- `acc_2s`: Fraction of trials where top-1 candidate start time $\hat{t}_0$ satisfies $|\hat{t}_0 - t_0| \le 2\text{ s}$ (for $R = 1\text{ s}$).
- `acc_15s`: Fraction of trials where $|\hat{t}_0 - t_0| \le 15\text{ s}$ (applicable to both $R = 1\text{ s}$ and $R = 15\text{ s}$).
- `wrong_score_mean`, `wrong_score_std`, `wrong_score_p95`, `wrong_score_p99`: Summary statistics of $r_{\max,\text{null}} = \max_{|t - t_0| > \max(D, 60\text{s})} r(t)$.
- `analytic_acc_pred`, `analytic_wrong_p95_pred`: Closed-form analytic predictions from our OU/Bartlett + Gumbel/Gaussian-maxima theory.
- `hourly_distinctiveness`: Per-minute-of-hour signal standard deviation $\sigma_f(m)$, step energy $\|\Delta f\|$, and top-1 accuracy near top-of-hour / half-hour boundaries vs. mid-hour.

### Falsifiable Success Thresholds
1. **Analytic Model Accuracy**: On the unseen holdout month (September 2026), the analytic approximation for $P(\text{top-1 correct})$ and $r_{\max,\text{null}}^{(95\%)}$ must achieve $\text{MAE} \le 0.08$ and $\text{MAE} \le 0.05$ respectively across all $(D \ge 60\text{ s}, W, \sigma)$ cells.
2. **Look-Elsewhere Calibration & Abstention Gate (for W10)**: The calibrated look-elsewhere threshold ($p_{\text{corrected}} < 0.01$ and peak margin $\Delta r \ge \Delta r_{\min}$) must keep the empirical false-positive rate under null/unmatched queries $\le 1.0\%$ on the unseen holdout month across all search windows $W \in \{1\text{ h}, \dots, 1\text{ month}\}$.
3. **Minimum-Duration Rule**: Identify the exact boundary $(D_{\min}(\sigma, W, R))$ required for $\ge 95\%$ top-1 identification accuracy on `dev` and verify that those cells achieve $\ge 90\%$ accuracy on `holdout`.

### Expected Failure Modes
- **Ultra-short clips ($D = 30\text{ s}$)**: With characteristic grid correlation time $\tau_{\text{OU}} \approx 40\text{ s}$, a $30\text{ s}$ segment has $N_{\text{eff}} < 5$ effective degrees of freedom; against $W \ge 1\text{ day}$, random segments easily achieve spurious correlations $r_{\max,\text{null}} > 0.90$.
- **Elexon $R = 15\text{ s}$ cadence on clips $D \le 2\text{ min}$**: Only $N = 2\text{--}8$ points exist; point-sampled Elexon suffers high-frequency aliasing, requiring $D \ge 5\text{--}10\text{ min}$ for unique matching over $W \ge 1\text{ day}$.
- **Uncompensated clock drift**: At $50\text{ ppm}$ drift over $D = 20\text{ min}$, the accumulated time shift is $1200 \times 5\times 10^{-5} = 0.06\text{ s}$ (benign for $1\text{ s}$ ENF), whereas larger drifts ($> 500\text{ ppm}$, e.g. $0.6\text{ s}$ over $20\text{ min}$) or VFR frame drops smear the correlation peak unless time-warping or segment chunking is applied.
