# W11 Critique & Failure Analysis (`FAILURES.md`)

**Worker:** `W11` (Uniqueness & Feasibility Mathematics, NESO-Based)  
**Evidence Grade:** **A** (verified on real GB NESO 1-second data, Aug & Sep 2026) / **B** (semi-synthetic stress suite)

---

## 1. Executive Summary of Audited Failure Modes

In accordance with Step F (Critique) of the GhostClock contract, we actively hunted for false positives, statistical illusions, numerical traps, and physical regimes where ENF timestamp matching fails. Below we document **five verified failure mechanisms**—four physical/statistical and one numerical implementation trap—along with the exact code-enforced controls handed off to `W10` (`matcher.py` / `policy.py`).

| # | Failure Mode | Physical / Mathematical Root Cause | Quantitative Impact (Holdout Sep 2026) | Enforced Mitigation Gate (`W10` / `W11`) |
| :- | :--- | :--- | :--- | :--- |
| **F1** | **Ultra-short clips ($D = 30\text{ s}$) in wide search windows ($W \ge 1\text{ day}$)** | Ornstein–Uhlenbeck correlation time ($\tau_{\text{OU}} \approx 790\text{ s}$) collapses within-window bulk DoF to $N_{\text{eff,bulk}} = 4.00$ (first Karhunen–Loève ramp mode carries $44.4\%$ of variance). | Best wrong-candidate score reaches $r_{\max,\text{null}}^{(95\%)} = 0.984$ ($W=1\text{ d}$) and $0.990$ ($W=1\text{ m}$); accuracy drops to $50\%$ at $\sigma=2\text{ mHz}$ and $1.3\%$ at $\sigma=5\text{ mHz}$. | Hard minimum-duration gate $D_{\min} \ge 60\text{ s}$ for $R=1\text{ s}$ (and $D_{\min} \ge 120\text{ s}$ when $\sigma \ge 5\text{ mHz}$); mandatory `INCONCLUSIVE` abstention below gate. |
| **F2** | **Naive i.i.d. Fisher-$z$ / Student-$t$ significance thresholds** | Assuming $N = D/R$ independent samples ignores grid autocorrelation ($\rho(1\text{ s}) = 0.99945$), underestimating null correlation variance by $6\times\text{–}120\times$. | On unmatched wrong-month queries (Aug 2026 segments searched in Sep 2026), naive i.i.d. $\alpha = 0.01$ thresholds suffer **$97.5\%\text{–}100\%$ False Positive Rate (FPR)**! | Replace nominal $N$ with W11's Karhunen–Loève / Bartlett $N_{\text{eff,tail}}$ + Hybrid AR-Innovation whitening gate, reducing Holdout Null FPR to **$\le 2.5\%$ ($0.0\%$ at $D \ge 120\text{ s}$)**. |
| **F3** | **Elexon $R = 15\text{ s}$ point-sampling aliasing & short-clip degeneracy ($D \le 120\text{ s}$)** | At $R=15\text{ s}$, $D=30\text{ s}$ has $N=2$ samples ($N-2=0$ DoF, so $r \equiv \pm 1.000$!). For $D \le 120\text{ s}$ ($N \le 8$), arbitrary-second recording start times $t_0 \pmod{15} \neq 0$ cause $\sim 5.6\text{ mHz}$ sub-grid aliasing error in point-sampled Elexon (`15s_point`). | At $R=15\text{ s}$, $D=30\text{ s}$ and $D=60\text{ s}$ fail completely ($0\%\text{–}13\%$ accuracy in $W \ge 1\text{ d}$). Even at $D=300\text{ s}$ ($\sigma=2\text{ mHz}, W=1\text{ d}$), `15s_point` trails `15s_avg` due to sub-grid phase jitter. | Enforce $D_{\min} \ge 300\text{ s}$ ($5\text{ min}$) for Elexon $15\text{ s}$ feeds at $\sigma \le 2\text{ mHz}$ ($D_{\min} \ge 600\text{ s}$ at $\sigma = 5\text{ mHz}$) and use 15-second block averaging (`15s_avg`) to low-pass filter sub-grid offsets. |
| **F4** | **Uncompensated severe clock / VFR speed drift ($\ge 1000\text{ ppm} = 0.1\%$)** | Time-axis stretch $\alpha = 10^{-3}$ shifts the query phase by $\alpha D = 0.30\text{ s}$ at $D=300\text{ s}$ and $0.60\text{ s}$ at $D=600\text{ s}$, de-synchronizing high-frequency grid innovations across the window. | While normal quartz drift ($100\text{ ppm}$) preserves $100\%$ accuracy at $D \ge 120\text{ s}$, severe $1000\text{ ppm}$ drift degrades $\pm 2\text{ s}$ localization on longer windows ($D=600\text{ s}$) as the correlation peak shifts by $+0.5 \alpha D$. | Enable W10's `clock_drift_search` grid (multiplying $M_{\text{eff}}$ by $K_\alpha$ in the look-elsewhere correction) or W13's piecewise speed-change detector when clip duration $D \ge 300\text{ s}$. |
| **F5** | **Catastrophic IEEE-754 float64 cancellation in uncentered `cumsum(f^2)`** | Directly summing $f^2 \approx 2500\text{ Hz}^2$ over $2.68 \times 10^6$ seconds reaches $6.7 \times 10^9$, leaving only $\sim 10^{-6}\text{ Hz}^2$ precision when subtracting $(\sum f)^2/N$; during flat deadband windows ($\sigma_y < 0.2\text{ mHz}$), variance underflows and $r$ explodes ($>1000$). | Caught in our pilot script (`test_theory_calibration.py`, task-41) where $D=30\text{ s}$ produced spurious `r > 4992` on a flat 30s grid deadband interval. | Always center grid frequency around nominal ($y = (f - 50.0)\times 1000\text{ mHz}$) before computing cumulative sums (recovering $5.5$ orders of magnitude of precision) and enforce a physical flat-reference variance floor $\sigma_{y,\min} \ge 0.25\text{ mHz}$. |

---

## 2. Deep-Dive on Failure Case F1 & F2: Why Raw Pearson Correlation Has a $0.90\text{–}0.98$ Spurious Floor

A critical question for any forensic ENF system is: *Why do two completely unrelated 5-minute or 10-minute grid frequency segments occasionally exhibit a raw Pearson correlation of $r = 0.95$?*

1. **Physical Cause (Governor Deadband & Half-Hourly Settlement Ramps):**  
   On the GB synchronous grid, NESO operates a $\pm 15\text{ mHz}$ governor deadband and Elexon clears wholesale generation in 30-minute settlement periods. As shown in our stochastic process fit (`work/W11/RESULTS.json`), the global frequency series has standard deviation $\sigma_f = 75.53\text{ mHz}$ (Aug 2026) and $81.70\text{ mHz}$ (Sep 2026), with a bulk Ornstein–Uhlenbeck damping timescale $\tau_{\text{OU}} = 790.1\text{ s}$ ($13.2\text{ minutes}$).
2. **Mathematical Cause (Scale-Invariant Karhunen–Loève Eigenvalues):**  
   When any segment of duration $D \le 600\text{ s}$ is mean-centered over its window, it behaves locally like an Ornstein–Uhlenbeck / Brownian bridge. Singular Value Decomposition of $400$ random windows across August 2026 proves that the top three Karhunen–Loève eigenmodes carry almost identical variance fractions across **all** durations from $30\text{ s}$ to $600\text{ s}$:
   - $D = 30\text{ s}$: $(\lambda_1, \lambda_2, \lambda_3) = (0.444,\, 0.188,\, 0.102) \implies N_{\text{eff,bulk}} = 1/\sum \lambda_k^2 = 4.00$
   - $D = 120\text{ s}$: $(\lambda_1, \lambda_2, \lambda_3) = (0.424,\, 0.177,\, 0.099) \implies N_{\text{eff,bulk}} = 4.37$
   - $D = 600\text{ s}$: $(\lambda_1, \lambda_2, \lambda_3) = (0.432,\, 0.178,\, 0.094) \implies N_{\text{eff,bulk}} = 4.27$
   Because the first eigenmode $\lambda_1$ (a monotonic linear ramp across the window) carries $\sim 43\%$ of the average variance—and up to $85\%$ of the variance during steep settlement ramps—any two windows in a 1-month search space that both experience a smooth monotonic frequency ramp and similar curvature will achieve raw Pearson correlation $r \approx 0.90\text{–}0.98$.
3. **Why Identification Still Succeeds for $D \ge 60\text{ s}$ (and How Step G Solves the Floor):**  
   As proven by our **Subspace Projection Theorem** (`work/W11/model_theory.py`), while raw wrong-candidate scores sit near $0.88\text{–}0.97$, the true match score $r_{\text{true}} = s_D / \sqrt{s_D^2 + \sigma^2}$ grows rapidly with $D$ because the within-window signal standard deviation $s_D$ increases from $6.04\text{ mHz}$ ($D=30\text{ s}$) to $21.02\text{ mHz}$ ($D=300\text{ s}$) and $43.79\text{ mHz}$ ($D=1200\text{ s}$), while white noise projected onto the smooth reference subspace shrinks as $\sqrt{d_{\text{KL}}/N}$.  
   Furthermore, our **Step G Iteration** (combining raw Pearson correlation with 3-second smoothed $\text{AR}(1)$ innovation correlation, $r_{\text{hybrid}} = 0.5 r_{\text{raw}} + 0.5 r_{\text{whitened}}$) strips out the shared linear ramp, increasing bulk effective degrees of freedom by **$3\times\text{–}8\times$** and crushing the 95th-percentile wrong-candidate score from **$0.97\text{–}0.98$ down to $0.62\text{–}0.78$**!

---

## 3. When GhostClock Must Abstain (`INCONCLUSIVE`)

Based on our falsification and stress experiments, GhostClock must enforce hard code-level abstention (`INCONCLUSIVE`) whenever any of the following conditions hold:
1. **Insufficient Duration for Reference Cadence:**
   - $R = 1\text{ s}$ (NESO): $D_{\text{valid}} < 60\text{ s}$ (or $D_{\text{valid}} < 120\text{ s}$ when estimated extractor noise $\hat{\sigma} > 3\text{ mHz}$ and $W \ge 1\text{ day}$).
   - $R = 15\text{ s}$ (Elexon): $D_{\text{valid}} < 300\text{ s}$ ($5\text{ minutes}$) at $\hat{\sigma} \le 2\text{ mHz}$, or $D_{\text{valid}} < 600\text{ s}$ ($10\text{ minutes}$) at $\hat{\sigma} \approx 5\text{ mHz}$.
2. **Flat / Deadband Grid Period:**  
   Local reference or query standard deviation $s_D < 1.5\text{ mHz}$ (occurs during quiet overnight deadband windows where grid frequency stays nearly constant).
3. **Look-Elsewhere Threshold & Peak Margin Failure:**  
   Look-elsewhere corrected $p_{\text{corrected}} > 0.01$ or peak margin $r_{(1)} - r_{(2)} < 0.04$ (raw) / $< 0.06$ (hybrid).
