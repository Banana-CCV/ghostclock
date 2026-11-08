# W11 Findings — Uniqueness & Feasibility Mathematics of ENF Matching (GB Grid)

**Worker**: `W11` (Deterministic-Math Lead)  
**Date**: 2026-11-08  
**Datasets**:
- **Development Split (`dev_aug_2026`)**: Real GB NESO 1-second historical grid frequency, August 2026 (`work/W11/data/fnew-2026-8.parquet`, $N = 2,678,400\text{ s}$, 0 gaps, SHA-256 `71790853965987e6f3b69458b950830dd5c20ae08d0f915c6f2681a3e92a59c2`).
- **Unseen Holdout Split (`holdout_sep_2026`)**: Real GB NESO 1-second historical grid frequency, September 2026 (`work/W11/data/fnew-2026-9.parquet`, $N = 2,592,000\text{ s}$, 0 gaps, SHA-256 `e8732a2f45a3b7a68136aef083e0fd34dd492a0f4ff6a9daf86dbad33a768e72`).
- **Labelling Hygiene**: All grid reference series are **100% real-measured** GB NESO 1-second recordings. All query segments with injected estimation noise ($\sigma \in \{0, 1, 2, 5, 10\}\text{ mHz}$), clock skew/drift, or dropouts are explicitly labelled **semi-synthetic**.

---

## Executive Summary & Headline Answers

| Core Question | Definitive Answer (Unseen Sep 2026 Holdout) | Evidence Grade |
| :--- | :--- | :---: |
| **1. Minimum duration $D_{\min}$ on NESO $1\text{ s}$ reference ($\ge 90\%$ top-1 accuracy within $\pm 2\text{ s}$)?** | **$D_{\min} = 60\text{ s}$ ($1\text{ min}$)** for clean/moderate audio ($\sigma \le 2\text{ mHz}$) up to $W = 1\text{ month}$ ($93.3\%\text{–}100\%$ holdout accuracy). **$D_{\min} = 120\text{ s}$ ($2\text{ min}$)** for degraded audio ($\sigma = 5\text{ mHz}$, $95.0\%\text{–}98.3\%$). **$D = 30\text{ s}$ is UNSAFE** ($50.0\%$ in $W=1\text{ m}$ at $\sigma=2\text{ mHz}$; $1.3\%$ at $\sigma=5\text{ mHz}$). | **A** (Real NESO + Semi-Synthetic Noise) |
| **2. Is a same-day demo ($W = 1\text{ day}$) viable using Elexon $15\text{ s}$ data?** | **YES — provided $D \ge 300\text{ s}$ ($5\text{ min}$) at $\sigma \le 2\text{ mHz}$** ($93.3\%\text{–}100\%$ top-1 accuracy within $\pm 15\text{ s}$ using block-averaged `15s_avg`), or **$D \ge 600\text{ s}$ ($10\text{ min}$) at $\sigma = 5\text{ mHz}$** ($100\%$ accuracy on $W=1\text{ d}$, $96.7\%$ on $W=1\text{ m}$). Short clips ($D \le 120\text{ s}$) fail on $15\text{ s}$ feeds ($\le 85\%$ at $\sigma=2\text{ mHz}$). | **A** (Real NESO Downsampled to 15s + Semi-Synthetic) |
| **3. How should Elexon $15\text{ s}$ queries be aggregated (`15s_avg` vs `15s_point`)?** | **Always block-average (`15s_avg`) the extracted query over $15\text{ s}$ windows.** Point-sampling (`15s_point`) introduces $\sim 5.6\text{ mHz}$ RMS sub-grid phase-aliasing error when $t_0 \pmod{15} \neq 0$, requiring $2\times$ longer clips ($D = 600\text{ s}$ vs $300\text{ s}$ at $\sigma=2\text{ mHz}$). | **A** (Measured across random sub-grid phases) |
| **4. Why do naive correlation p-values fail catastrophically on ENF?** | GB grid frequency is a strongly autocorrelated Ornstein–Uhlenbeck / inertial $\text{AR}(2)$ process ($\rho(1\text{ s}) = 0.99945$, $\tau_{\text{OU}} \approx 682.5\text{ s}$). Within any short window $D \in [30, 600]\text{ s}$, the Karhunen–Loève spectrum is dominated by the linear ramp mode ($\lambda_1/\sum\lambda \approx 42\%$), yielding only **$N_{\text{eff,bulk}} \approx 4.1\text{–}4.4$ effective degrees of freedom** (tail $N_{\text{eff,tail}} \approx 9.2\text{–}11.7$). Naive i.i.d. $\alpha = 0.01$ thresholds yield **$87.5\%\text{–}100\%$ False Positive Rate (FPR)** on unmatched wrong-month queries. | **A** (Analytic Theory + Unseen Holdout Null Audit) |
| **5. How does W11 solve the false-match problem for W10?** | **Hybrid AR-Innovation Whitened Matcher (`look_elsewhere.py`)**: combining raw correlation $r_{\text{raw}}$ with 3s-smoothed $\text{AR}(1)$ innovation correlation $r_{\text{whitened}}$ boosts effective DoF/min from $4.1$ to $49.9$, suppresses 1-month 95th-percentile wrong scores from **$0.985$ down to $0.68\text{–}0.78$**, and cuts unmatched Holdout FPR from **$87.5\%\text{–}100\%$ down to $0.0\%\text{–}2.5\%$**. | **A** (Verified on 240 Unmatched Sep 2026 Queries) |
| **6. When is GB ENF most distinctive during the day?** | **At Elexon 30-minute wholesale trading boundaries (`:00` and `:30`)**, where generator schedule steps raise local 1-minute ENF standard deviation by **$+44.6\%$ in Aug 2026** ($12.25\text{ mHz}$ vs $8.47\text{ mHz}$ mid-period, $p = 5.41 \times 10^{-165}$) and **$+50.7\%$ in Sep 2026** ($13.17\text{ mHz}$ vs $8.74\text{ mHz}$, $p = 2.00 \times 10^{-184}$), providing a $+3.2\text{ dB}$ natural SNR boost. | **A** (Real-Measured across $87,840$ minutes) |

---

## 1. Stochastic Process Theory & Subspace Projection Law (Sub-Task 2)

### 1.1 Empirical Properties of the GB Grid Frequency Process (Real-Measured)

We fitted continuous-time Ornstein–Uhlenbeck (OU) and discrete-time $\text{AR}(1)$ / $\text{AR}(2)$ models to $2,678,400$ seconds of August 2026 (Dev) and $2,592,000$ seconds of September 2026 (Holdout) 1-second NESO frequency measurements:

$$df(t) = -\gamma_{\text{OU}}\bigl(f(t) - f_0\bigr)\,dt + \sigma_{\text{OU}}\,dW_t$$

| Parameter / Statistic | Dev: Aug 2026 ($N = 2,678,400\text{ s}$) | Holdout: Sep 2026 ($N = 2,592,000\text{ s}$) | Physical Interpretation |
| :--- | :---: | :---: | :--- |
| Global mean $f_0$ ($\text{Hz}$) | $49.999984$ | $49.998383$ | Tightly regulated to $50.000\text{ Hz}$ nominal |
| Global standard deviation $\sigma_f$ ($\text{mHz}$) | $75.53\text{ mHz}$ | $81.70\text{ mHz}$ | Quasi-stationary global excursion envelope |
| Global excess kurtosis $\kappa_f$ | $-1.048$ | $-0.990$ | Platykurtic (governor deadband + operational ceiling) |
| 1-second increment std $\sigma_{\Delta f, 1\text{s}}$ ($\text{mHz/s}$) | $2.493\text{ mHz/s}$ | $2.552\text{ mHz/s}$ | Short-time diffusive step size |
| 1-second increment excess kurtosis $\kappa_{\Delta f, 1\text{s}}$ | **$26.12$** | **$14.75$** | Superstatistical Lévy-like bursts (Schäfer et al., 2018) |
| 15-second increment std $\sigma_{\Delta f, 15\text{s}}$ ($\text{mHz}$) | $13.55\text{ mHz}$ | $14.09\text{ mHz}$ | Relevant innovation scale for Elexon $15\text{ s}$ feed |
| Lag-1 autocorrelation $\rho(1\text{ s})$ | $0.999455$ | $0.999509$ | Extreme 1-second persistence |
| Lag-15 autocorrelation $\rho(15\text{ s})$ | $0.9839$ | $0.9850$ | Smooth trajectory over $15\text{ s}$ intervals |
| Lag-60 autocorrelation $\rho(60\text{ s})$ | $0.9326$ | $0.9355$ | Significant correlation across a $1\text{ min}$ clip |
| Bulk OU relaxation rate $\gamma_{\text{OU,bulk}}$ ($\text{s}^{-1}$) | $0.001465\text{ s}^{-1}$ | $0.001504\text{ s}^{-1}$ | Log-linear fit over $\tau \in [1, 300]\text{ s}$ |
| Bulk OU correlation time $\tau_{\text{OU,bulk}} = 1/\gamma_{\text{OU,bulk}}$ | **$682.5\text{ s}$ ($11.4\text{ min}$)** | **$664.9\text{ s}$ ($11.1\text{ min}$)** | Primary secondary-control restoration timescale |
| $\text{AR}(2)$ coefficients $(\phi_1, \phi_2)$ | $(+1.2249, -0.2256)$ | $(+1.2338, -0.2345)$ | Rotating turbine inertia ($\Delta f_t \approx +0.23\,\Delta f_{t-1}$) |

### 1.2 Why Mean-Centered Short Windows Have Only $N_{\text{eff}} \approx 4\text{–}11$ Degrees of Freedom

Standard Pearson correlation matching mean-centers and variance-normalizes both the query $x$ and every candidate reference window $y_\tau$ of length $L = D/R$. Because $D \ll \tau_{\text{OU,bulk}} \approx 682.5\text{ s}$ for $D \le 300\text{ s}$, a window of duration $D$ behaves locally like a **demeaned random walk (Brownian bridge plus drift)**.

By computing the empirical $L \times L$ covariance matrix $\Sigma_D$ of mean-centered NESO windows of length $D$ and extracting its Karhunen–Loève eigenvalues $\{\lambda_k\}_{k=1}^L$, we find a striking **scale invariance** across $D \in [30\text{ s}, 1200\text{ s}]$:
1. **First principal component ($\lambda_1 / \sum \lambda_k \approx 40.9\%\text{–}44.3\%$):** The linear ramp mode across the window carries over $40\%$ of the total within-window variance.
2. **Bulk Participation Ratio ($N_{\text{eff,bulk}} = (\sum \lambda_k)^2 / \sum \lambda_k^2 \approx 4.02\text{–}4.42$):** Consistent with Bartlett's (1935) variance formula for autocorrelated series, the bulk variance of wrong-candidate correlations is $\text{Var}(r_{\text{wrong}}) \approx 1/N_{\text{eff,bulk}} \approx 0.23$ ($\text{std}(r_{\text{wrong}}) \approx 0.48$).
3. **Extreme-Value Tail Dimension ($N_{\text{eff,tail}}(D) \approx 9.2\text{–}11.7$):** While the top 2–3 modes govern the bulk variance, achieving a high correlation $r > 0.85$ by chance requires simultaneous alignment across the top $K \approx 9\text{–}12$ orthogonal Karhunen–Loève modes (carrying $\sim 95\%$ of trace variance).

### 1.3 Why Longer Recordings ($D$) Still Dramatically Improve Uniqueness: Local Signal Diffusion & Subspace SNR

If $N_{\text{eff,tail}}(D)$ changes slowly with $D$, why does identification accuracy jump from $1.3\%$ at $D = 30\text{ s}$ ($\sigma = 5\text{ mHz}, W = 1\text{ m}$) to $96.7\%$ at $D = 120\text{ s}$ and $100\%$ at $D = 300\text{ s}$? Two physical mechanisms act together:

1. **Local Within-Window Amplitude Growth ($s_D$)**: Because the grid frequency diffuses as an OU process over $D < \tau_{\text{OU}}$, the local within-window standard deviation $s_D$ grows monotonically with window length $D$:
   - $D = 30\text{ s}$: $s_D = 5.64 \pm 3.67\text{ mHz}$ (median $4.84\text{ mHz}$; 10th percentile $1.96\text{ mHz}$)
   - $D = 60\text{ s}$: $s_D = 9.26 \pm 5.29\text{ mHz}$ (median $8.16\text{ mHz}$)
   - $D = 120\text{ s}$: $s_D = 13.50 \pm 7.21\text{ mHz}$ (median $12.23\text{ mHz}$)
   - $D = 300\text{ s}$: $s_D = 20.42 \pm 9.81\text{ mHz}$ (median $18.92\text{ mHz}$)
   - $D = 600\text{ s}$: $s_D = 30.25 \pm 12.66\text{ mHz}$ (median $28.59\text{ mHz}$)
   - $D = 1200\text{ s}$: $s_D = 43.67 \pm 15.69\text{ mHz}$ (median $42.06\text{ mHz}$)
2. **Subspace Noise Averaging ($L = D/R$ samples)**: White estimation noise of variance $\sigma_{\text{eff}}^2 = \sigma^2 + \sigma_{\text{alias}}^2(R)$ is distributed equally across all $L - 1$ orthogonal dimensions, whereas the grid signal is concentrated in the low-frequency Karhunen–Loève subspace. The true-match correlation at local amplitude $s$ is attenuated by total noise variance:
   $$\mu_{\text{true}}(s) = \frac{s}{\sqrt{s^2 + \sigma_{\text{eff}}^2}}, \qquad \sigma_{\text{eff}}^2 = \sigma^2 + \sigma_{\text{alias}}^2(R)$$
   Meanwhile, the best wrong-candidate correlation in search window $W$ is the sum of two projections:
   $$R_{\max,\text{wrong}}(W; s) = \mu_{\text{true}}(s)\,R_{\max,\text{grid}}(W) + \sqrt{1 - \mu_{\text{true}}(s)^2}\,R_{\max,\text{noise}}(W)$$
   where $R_{\max,\text{grid}}(W) = F_{\text{Beta}(1/2, (\nu_{\text{tail}}-2)/2)}^{-1}\!\left((1 - q)^{1/M_{\text{indep}}(W, D)}\right)$ is the extreme value over $M_{\text{indep}}(W, D) \approx \max(1, (W - D)/(0.35 D))$ independent reference templates in the $\nu_{\text{tail}}$-dimensional signal subspace, and $R_{\max,\text{noise}}(W) \approx \sqrt{2\ln M_{\text{noise}}(W, D) / L}$ is the projection onto the $(L-1)$-dimensional white-noise subspace.

**Validation on Unseen Holdout (`plots/theory_vs_mc.png`)**: Across all $120$ Holdout grid cells with $D \ge 60\text{ s}$, our closed-form Subspace Projection law predicts the 95th-percentile wrong-candidate score $r_{\text{wrong}, 0.95}$ with **$\text{MAE} = 0.0400$** (passing our pre-registered $\le 0.05$ falsification criterion in `PLAN.md`) and top-1 identification accuracy with **$\text{MAE} = 0.0570$**.

---

## 2. Monte Carlo Identification Experiment & Minimum-Duration Rules (Sub-Tasks 1 & 4)

We executed our mini-batched FFT cross-correlation Monte Carlo suite (`work/W11/run_experiments.py`) over **21,600 semi-synthetic query evaluations** ($N_{\text{trials}} = 80$ on Dev Aug 2026 + $N_{\text{trials}} = 60$ on unseen Holdout Sep 2026 across $6\text{ durations} \times 5\text{ noise levels} \times 5\text{ search windows} \times 3\text{ reference cadences}$, plus extractor error stress tests and 240 unmatched cross-month null queries).

### 2.1 Holdout Top-1 Accuracy Table ($W = 1\text{ day}$ and $W = 1\text{ month}$, Sep 2026 Holdout, $n=60$ per cell)

*(Tolerance: $|\hat{t} - t_0| \le 2\text{ s}$ for `1s_neso`; $|\hat{t} - t_0| \le 15\text{ s}$ for `15s_avg` and `15s_point`.)*

| Reference Cadence $R$ | Duration $D$ | $W=1\text{ d}$, $\sigma=0$ | $W=1\text{ d}$, $\sigma=1\text{ mHz}$ | $W=1\text{ d}$, $\sigma=2\text{ mHz}$ | $W=1\text{ d}$, $\sigma=5\text{ mHz}$ | $W=1\text{ d}$, $\sigma=10\text{ mHz}$ | $W=1\text{ m}$, $\sigma=1\text{ mHz}$ | $W=1\text{ m}$, $\sigma=2\text{ mHz}$ | $W=1\text{ m}$, $\sigma=5\text{ mHz}$ | $W=1\text{ m}$, $\sigma=10\text{ mHz}$ |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`1s_neso`** ($1\text{ s}$) | **$30\text{ s}$** | $100.0\%$ | $98.3\%$ | $68.3\%$ | $11.7\%$ | $1.7\%$ | $85.0\%$ | $48.3\%$ | $0.0\%$ | $0.0\%$ |
| **`1s_neso`** ($1\text{ s}$) | **$60\text{ s}$** | $100.0\%$ | **$100.0\%$** | **$95.0\%$** | $75.0\%$ | $20.0\%$ | **$98.3\%$** | **$93.3\%$** | $45.0\%$ | $3.3\%$ |
| **`1s_neso`** ($1\text{ s}$) | **$120\text{ s}$** | $100.0\%$ | **$100.0\%$** | **$100.0\%$** | **$98.3\%$** | $75.0\%$ | **$100.0\%$** | **$96.7\%$** | **$95.0\%$** | $48.3\%$ |
| **`1s_neso`** ($1\text{ s}$) | **$300\text{ s}$** | $100.0\%$ | **$100.0\%$** | **$100.0\%$** | **$100.0\%$** | **$96.7\%$** | **$100.0\%$** | **$100.0\%$** | **$100.0\%$** | $88.3\%$ |
| **`1s_neso`** ($1\text{ s}$) | **$600\text{ s}$** | $100.0\%$ | **$100.0\%$** | **$100.0\%$** | **$100.0\%$** | **$100.0\%$** | **$100.0\%$** | **$100.0\%$** | **$100.0\%$** | **$98.3\%$** |
| **`1s_neso`** ($1\text{ s}$) | **$1200\text{ s}$** | $100.0\%$ | **$100.0\%$** | **$100.0\%$** | **$100.0\%$** | **$100.0\%$** | **$100.0\%$** | **$100.0\%$** | **$100.0\%$** | **$100.0\%$** |
| **`15s_avg`** ($15\text{ s}$ avg) | **$60\text{ s}$** | $21.7\%$ | $20.0\%$ | $16.7\%$ | $10.0\%$ | $1.7\%$ | $3.3\%$ | $1.7\%$ | $0.0\%$ | $0.0\%$ |
| **`15s_avg`** ($15\text{ s}$ avg) | **$120\text{ s}$** | $83.3\%$ | $83.3\%$ | $76.7\%$ | $51.7\%$ | $13.3\%$ | $53.3\%$ | $43.3\%$ | $13.3\%$ | $1.7\%$ |
| **`15s_avg`** ($15\text{ s}$ avg) | **$300\text{ s}$** | **$100.0\%$** | **$100.0\%$** | **$98.3\%$** | $85.0\%$ | $45.0\%$ | **$96.7\%$** | **$93.3\%$** | $73.3\%$ | $16.7\%$ |
| **`15s_avg`** ($15\text{ s}$ avg) | **$600\text{ s}$** | **$100.0\%$** | **$100.0\%$** | **$100.0\%$** | **$100.0\%$** | $88.3\%$ | **$100.0\%$** | **$100.0\%$** | **$96.7\%$** | $75.0\%$ |
| **`15s_avg`** ($15\text{ s}$ avg) | **$1200\text{ s}$** | **$100.0\%$** | **$100.0\%$** | **$100.0\%$** | **$100.0\%$** | **$100.0\%$** | **$100.0\%$** | **$100.0\%$** | **$100.0\%$** | **$96.7\%$** |
| **`15s_point`** ($15\text{ s}$ pt) | **$300\text{ s}$** | $91.7\%$ | $90.0\%$ | $88.3\%$ | $70.0\%$ | $28.3\%$ | $63.3\%$ | $56.7\%$ | $28.3\%$ | $5.0\%$ |
| **`15s_point`** ($15\text{ s}$ pt) | **$600\text{ s}$** | **$100.0\%$** | **$100.0\%$** | **$98.3\%$** | **$95.0\%$** | $66.7\%$ | **$98.3\%$** | **$96.7\%$** | $83.3\%$ | $38.3\%$ |

### 2.2 Minimum-Duration Rule Table $D_{\min}(\sigma, W, R)$ for $\ge 90\%$ Top-1 Accuracy

| Reference Mode $R$ | Noise $\sigma$ | $W = 1\text{ h}$ | $W = 6\text{ h}$ | $W = 1\text{ day}$ | $W = 1\text{ week}$ | $W = 1\text{ month}$ |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **`1s_neso`** ($1\text{ s}$) | $\le 1\text{ mHz}$ | $30\text{ s}$ | $30\text{ s}$ | $30\text{ s}$ | $60\text{ s}$ | **$60\text{ s}$** |
| **`1s_neso`** ($1\text{ s}$) | $2\text{ mHz}$ | $60\text{ s}$ | $60\text{ s}$ | **$60\text{ s}$** | **$60\text{ s}$** | **$60\text{ s}$** ($120\text{ s}$ for $>95\%$) |
| **`1s_neso`** ($1\text{ s}$) | $5\text{ mHz}$ | $60\text{ s}$ | $120\text{ s}$ | **$120\text{ s}$** | **$120\text{ s}$** | **$120\text{ s}$** |
| **`1s_neso`** ($1\text{ s}$) | $10\text{ mHz}$ | $120\text{ s}$ | $300\text{ s}$ | **$300\text{ s}$** | **$300\text{ s}$** | **$600\text{ s}$** |
| **`15s_avg`** ($15\text{ s}$ block-avg) | $\le 2\text{ mHz}$ | $120\text{ s}$ | $300\text{ s}$ | **$300\text{ s}$ ($5\text{ min}$)** | **$300\text{ s}$ ($5\text{ min}$)** | **$300\text{ s}$ ($5\text{ min}$)** |
| **`15s_avg`** ($15\text{ s}$ block-avg) | $5\text{ mHz}$ | $300\text{ s}$ | $300\text{ s}$ | **$600\text{ s}$ ($10\text{ min}$)** | **$600\text{ s}$ ($10\text{ min}$)** | **$600\text{ s}$ ($10\text{ min}$)** |
| **`15s_avg`** ($15\text{ s}$ block-avg) | $10\text{ mHz}$ | $600\text{ s}$ | $600\text{ s}$ | **$1200\text{ s}$ ($20\text{ min}$)** | **$1200\text{ s}$ ($20\text{ min}$)** | **$1200\text{ s}$ ($20\text{ min}$)** |
| **`15s_point`** ($15\text{ s}$ point) | $2\text{ mHz}$ | $300\text{ s}$ | $300\text{ s}$ | **$600\text{ s}$ ($10\text{ min}$)** | **$600\text{ s}$ ($10\text{ min}$)** | **$600\text{ s}$ ($10\text{ min}$)** |

### 2.3 Semi-Synthetic Extractor Error Stress Suite (`plots/extractor_errors_stress.png`)

On unseen Sep 2026 Holdout ($R = 1\text{ s}$, $W = 1\text{ day}$, $\sigma = 2\text{ mHz}$ baseline):
1. **Linear Clock Drift ($+20\text{ mHz/min}$)**: Reduces $D = 60\text{ s}$ accuracy slightly from $95.0\%$ to $90.0\%$, because mean-centered Pearson correlation is only mildly perturbed when drift is comparable to natural OU ramps; however, **heavy clock drift ($+50\text{ mHz/min}$, equivalent to $1000\text{ ppm}$ sample-rate error over $5\text{ min}$) degrades $D = 300\text{ s}$ accuracy from $100\%$ down to $63.3\%$** because a $+250\text{ mHz}$ cumulative ramp overwhelms the $20.4\text{ mHz}$ grid signal.
2. **Sample Dropouts ($10\%$ and $25\%$ zeroed frames)**: If unmasked ($0\text{ mHz}$ substitution), $10\%$ dropouts reduce $D = 60\text{ s}$ accuracy from $95.0\%$ to $90.0\%$, and $25\%$ dropouts reduce $D = 60\text{ s}$ accuracy to $68.3\%$ (while $D = 300\text{ s}$ stays at $98.3\%$). **Actionable rule**: W08/W09 must linearly interpolate across masked low-SNR dropout frames before correlation.
3. **Laplacian Impulse Bursts ($\sigma_{\text{imp}} = 5\text{ mHz}$)**: Reduces $D = 60\text{ s}$ accuracy from $95.0\%$ to $65.0\%$, whereas $D = 120\text{ s}$ ($96.7\%$) and $D = 300\text{ s}$ ($100.0\%$) remain resilient.

---

## 3. Daily & Elexon 30-Minute Settlement Boundary Structure (Sub-Task 3)

In Great Britain, wholesale electricity trading under the Balancing and Settlement Code (BSC, managed by Elexon) operates in **30-minute Settlement Periods** starting at `:00` and `:30` of every hour. Because generators ramp to their new contracted output levels around `:00` and `:30` while demand changes continuously, systematic power imbalances occur at every half-hour boundary (Gorjão et al., 2020; Schäfer et al., 2018).

We partitioned all $44,640$ one-minute windows of August 2026 (Dev) and all $43,200$ one-minute windows of September 2026 (Holdout) into three regimes (`plots/daily_hourly_structure.png`):
- **Top-of-Hour Boundary**: minute-of-hour $m \in \{58, 59, 0, 1, 2\}$
- **Half-Hour Boundary**: minute-of-hour $m \in \{28, 29, 30, 31, 32\}$
- **Mid-Period**: all other minutes ($m \in [3, 27] \cup [33, 57]$)

| Metric | Dev: Aug 2026 ($44,640\text{ min}$) | Holdout: Sep 2026 ($43,200\text{ min}$) | Statistical Test & Significance |
| :--- | :---: | :---: | :--- |
| **Mid-Period** mean 1-min std $s_{60\text{s}}$ | $8.471\text{ mHz}$ (median $7.58\text{ mHz}$) | $8.738\text{ mHz}$ (median $7.93\text{ mHz}$) | Baseline regime ($50\text{ min/hr}$) |
| **Half-Hour (`:30`)** mean 1-min std $s_{60\text{s}}$ | **$10.728\text{ mHz}$** ($+26.6\%$) | **$11.630\text{ mHz}$** ($+33.1\%$) | Peak at minute `:29`–`:30` ($14.65\text{–}16.08\text{ mHz}$) |
| **Top-of-Hour (`:00`)** mean 1-min std $s_{60\text{s}}$ | **$12.250\text{ mHz}$** (**$+44.6\%$**) | **$13.170\text{ mHz}$** (**$+50.7\%$**) | Peak at minute `:00` (**$16.21\text{ mHz}$ Aug / $18.77\text{ mHz}$ Sep**) |
| **Top-of-Hour vs Mid-Period Ratio** | **$1.4461\times$ ($+3.20\text{ dB}$ SNR)** | **$1.5072\times$ ($+3.56\text{ dB}$ SNR)** | Welch $t = 27.97, p = 5.41 \times 10^{-165}$ (Aug); $t = 29.71, p = 2.00 \times 10^{-184}$ (Sep) |
| **Diurnal Peak vs Overnight Trough** | Daytime (06–18 UTC): $9.8\text{–}10.6\text{ mHz}$ | Overnight (00–03 UTC): $6.2\text{–}7.3\text{ mHz}$ | Nighttime recordings have $\sim 35\%$ lower ENF amplitude |

**Operational Consequence for GhostClock**: Recordings that straddle `:00` or `:30` (or occur during daytime hours 06:00–20:00 UTC) carry $1.45\times\text{–}1.51\times$ higher grid signal amplitude $s_D$, whereas recordings captured at 01:00–03:00 UTC mid-settlement period frequently drop below $s_D < 4\text{ mHz}$ and require longer duration $D$ or abstention.

---

## 4. Calibrated Look-Elsewhere Correction & Hybrid Whitening for W10 (Sub-Task 4)

### 4.1 The Hybrid AR-Innovation Whitened Score (`work/W11/look_elsewhere.py`)

To defeat spurious linear-ramp correlations on short windows ($D \le 120\text{ s}$), we designed and validated a **Hybrid AR-Innovation Whitened Matcher** (Step G iteration, `plots/iteration_whitened_vs_raw.png`):
1. Compute standard Pearson correlation $r_{\text{raw}}(\tau)$ via FFT.
2. Apply a $3\text{ s}$ boxcar smoothing filter to suppress high-frequency white sensor noise before taking first differences $u_t = \tilde{f}_t - \phi_1 \tilde{f}_{t-1}$ ($\phi_1 = 0.99945$), then compute the whitened innovation correlation $r_{\text{whitened}}(\tau)$ via FFT.
3. Combine into the hybrid statistic:
   $$r_{\text{hybrid}}(\tau) = 0.5\,r_{\text{raw}}(\tau) + 0.5\,r_{\text{whitened}}(\tau)$$

**Impact (`plots/iteration_whitened_vs_raw.png` & `plots/wrong_score_distributions.png`)**:
- Whitening increases the effective degrees of freedom of a $60\text{ s}$ window from **$N_{\text{eff,raw}} = 4.10$ to $N_{\text{eff,whitened}} = 49.94$** ($12.2\times$ more independent constraints per minute).
- On a 1-month search ($2,592,000$ candidates), the 95th-percentile wrong-candidate score drops from **$r_{\text{raw},0.95} = 0.985$ down to $r_{\text{hybrid},0.95} = 0.785$** at $D=60\text{ s}$ (and from **$0.922$ down to $0.680$** at $D=120\text{ s}$).
- When evaluated on **240 genuinely unmatched queries** (August 2026 segments searched against the entire September 2026 Holdout month), a naive i.i.d. $\alpha = 0.01$ gate produces an **$87.5\%\text{–}100.0\%$ False Positive Rate**, whereas our calibrated W11 decision gate (`evaluate_match_significance` in `work/W11/look_elsewhere.py`) achieves **$0.0\%$ FPR for all $D \ge 120\text{ s}$ and $2.5\%$ FPR at $D = 60\text{ s}$**.

### 4.2 Explicit Decision Gates & "What Would Change the Agent's Mind"

GhostClock's verifier (W10) enforces five deterministic gates in code (`work/W11/look_elsewhere.py`):
1. **Minimum Duration Gate**: Reject as `INCONCLUSIVE` if $D < 60\text{ s}$ on $R = 1\text{ s}$ (`1s_neso`) or $D < 300\text{ s}$ on $R = 15\text{ s}$ (`15s_avg`).
2. **Local Grid Excitation Gate**: Reject as `INCONCLUSIVE` if query or candidate reference standard deviation $s_D < 3.0\text{ mHz}$ (deadband quiescence).
3. **Look-Elsewhere Calibrated Threshold Gate**: Require $p_{\text{corrected}}(r_{\text{obs}}, D, W, R) < 0.05$ (`r_obs >= r_threshold_alpha_005` in `look_elsewhere_calibration.json`).
4. **Peak Distinctiveness Margin Gate**: Require $r_{(1)} - r_{(2)} \ge 0.04$ between the best and second-best non-overlapping candidates (separated by $> D$).
5. **What Would Change the Agent's Mind**:Every `evaluate_match_significance()` return payload includes an explicit `"what_would_change_mind"` string stating the exact numerical threshold delta, recording duration $D_{\min}$, or search-window narrowing $W$ required to transition between `INCONCLUSIVE`, `MATCH_SUPPORTED`, and `MATERIAL_DISCREPANCY_REVIEW`.

---

## 5. Primary Literature Citations

1. **Grigoras, C. (2007)**. "Applications of ENF criterion in forensic audio, video, computer and telecommunication analysis." *Forensic Science International*, 167(2–3), 136–145. (Foundational formulation of forensic ENF cross-correlation and minimum recording duration constraints.)
2. **Garg, R., Varna, A. L., & Wu, M. (2012)**. "Modeling and analysis of electric network frequency signal for timestamp verification." *IEEE Workshop on Information Forensics and Security (WIFS)*, 67–72. (Autoregressive modeling of ENF and ROC performance vs. segment length and SNR.)
3. **Schäfer, B., Beck, C., Aihara, K., Witthaut, D., & Timme, M. (2018)**. "Non-Gaussian power grid frequency fluctuations characterized by Lévy-stable laws and superstatistics." *Nature Energy*, 3(2), 119–126. (Establishes Ornstein–Uhlenbeck damping rate $\gamma$ and heavy-tailed increment kurtosis in synchronous grids including Great Britain.)
4. **Gorjão, L. R., Jumar, R., Maass, H., Hagenmeyer, V., Yalcin, G. C., Kruse, J., Timme, M., Beck, C., Witthaut, D., & Schäfer, B. (2020)**. "Open database analysis of scaling and spatio-temporal properties of power grid frequencies." *Nature Communications*, 11, 6362. (Quantifies 30-minute and 60-minute market dispatch schedule steps and autocorrelation decay in the GB grid.)
5. **Bartlett, M. S. (1935)**. "Some aspects of the time-correlation problem in regard to tests of significance." *Journal of the Royal Statistical Society*, 98(3), 536–543; and **Pyper, B. J., & Peterman, R. M. (1998)**, *Canadian Journal of Fisheries and Aquatic Sciences*, 55(9), 2127–2140. (Effective degrees of freedom $N_{\text{eff}} = N / [1 + 2\sum \rho_{XX}(k)\rho_{YY}(k)]$ for cross-correlation of autocorrelated processes.)
