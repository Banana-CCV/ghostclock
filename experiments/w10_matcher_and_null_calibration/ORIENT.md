# W10 Orientation — Matcher, Statistics, Calibration & Evaluation Protocol (AUDITOR)

## 1. Role & Scope
As **W10**, our role is the **forensic statistician and independent critical authority (Auditor)**.
- We own:
  1. `work/W10/matcher.py`: High-speed, statistically calibrated ENF time-series matcher (`match(...)` per `integration/interfaces.md` §3).
  2. `work/W10/policy.py`: Deterministic decision policy (`MATCH_SUPPORTED`, `INCONCLUSIVE`, `MATERIAL_DISCREPANCY_REVIEW`) with explicit reasons and counterfactuals (`what_would_change_this`).
  3. `eval/protocol.md`: Project-wide evaluation protocol, dev/holdout governance, leakage prevention rules, baseline definitions, and multimodal dependence rules.
  4. `agents/reviews/W10_*.md`: Independent statistical critiques and vetoes of dubious claims across sibling workers (`W01`–`W20`).

## 2. Core Physical & Statistical Assumptions
1. **Grid Frequency Process**: Mains frequency $f(t)$ around nominal $f_0 \in \{50, 60\}\,\text{Hz}$ behaves locally like a mean-reverting stochastic process (Ornstein–Uhlenbeck / ARMA) with strong short-lag autocorrelation ($\tau_c \approx 5\text{–}30\,\text{s}$ in GB/continental grids) and deadband/governor dynamics.
2. **Effective Degrees of Freedom ($N_{\text{eff}}$)**: Because both the extracted ENF trace $x(t)$ and the grid reference $y(t)$ are strongly autocorrelated, a clip of duration $D$ seconds sampled at $1\,\text{s}$ cadence does **not** have $D$ independent samples. By Bartlett's formula (1946) / Bayley & Hammersley (1946), the variance of the sample cross-correlation under the null $H_0$ is approximately:
   $$\text{Var}(r) \approx \frac{1}{N_{\text{eff}}} = \frac{1}{N} \sum_{k=-(N-1)}^{N-1} \left(1 - \frac{|k|}{N}\right) \rho_{xx}(k)\rho_{yy}(k)$$
   Ignoring autocorrelation grossly underestimates null variance and produces catastrophic false-positive rates when using standard $t$-distribution or Fisher-$z$ p-values with naive $N$.
3. **Look-Elsewhere / Multiple-Testing Penalty ($M_{\text{eff}}$)**: Searching a window of length $W$ seconds at cadence $\Delta t$ tests $M = (W - D)/\Delta t + 1$ candidate lags. Nearby lags are correlated; the effective number of independent candidate peaks $M_{\text{eff}}$ scales roughly with $W / \tau_{\text{decorr}}$. A raw peak correlation $r_{\max}$ must be calibrated against the extreme-value distribution of the maximum of $M_{\text{eff}}$ correlated null trials:
   $$p_{\text{global}} \approx 1 - (1 - p_{\text{local}})^{M_{\text{eff}}}$$
   confirmed empirically against non-matching reference days, circular shifts, and $H_0$ (no-ENF) traces.
4. **DC Offset & Scale Invariance vs. Amplitude Fidelity**:
   - Local clock crystal offset ($\delta_c$, typically $\pm 10\text{–}100\,\text{ppm}$, i.e., $\pm 0.5\text{–}5\,\text{mHz}$ at $50\,\text{Hz}$) shifts the mean frequency of an extracted trace. Thus, mean-removed Normalized Cross-Correlation (NCC) is invariant to constant crystal offset, whereas raw RMSE is sensitive to offset unless evaluated after removing the relative mean offset (`offset_hz`).
   - Conversely, NCC alone is scale-invariant and can match a tiny noise fluctuation or flat line if not guarded by minimum signal variance, RMSE in mHz (`rmse_mhz`), and quality weights $q(t)$. Both NCC and offset-adjusted RMSE (in mHz) must be jointly gated.
5. **Clock Drift / Speed Warp**: Recording crystal drift or resampling inaccuracies can stretch/compress the time axis by $\alpha \in [-0.005, +0.005]$ ($\pm 0.5\%$). Over a $600\,\text{s}$ clip, even a $0.1\%$ drift shifts alignment by $0.6\,\text{s}$ (enough to degrade 1-second correlation). Searching a small grid of stretch factors $\alpha$ can recover drifted signals, **provided** the extra trials $K_\alpha$ are accounted for in the look-elsewhere correction.
6. **Non-Independence of Audio and Video ENF**: Audio hum ($50\,\text{Hz}$ + harmonics) and video rolling-shutter flicker ($100\,\text{Hz}$) in the same recording observe the **same underlying local mains waveform**. Naive multiplication of $p$-values ($p_{\text{audio}} \times p_{\text{video}}$) violates conditional independence under environmental/grid confounds and is strictly forbidden.

## 3. Missing Data & Dependencies
- **ENF-WHU Dataset**: Present at `datasets/raw/enf-whu/repo/ENF-WHU-Dataset/` (`H1`: 130 clips, `H1_ref`: 130 aligned reference WAVs at $400\,\text{Hz}$, `H1_ref_one_day`: 28 full-day 24h reference WAVs at $400\,\text{Hz}$, `H0`: 50 negative clips). Note that `H1_ref` and `H1_ref_one_day` are $400\,\text{Hz}$ raw voltage waveform WAV files around $50\,\text{Hz}$—their instantaneous frequency trajectories can be extracted directly at high SNR to test our matcher immediately, even before W03/W06/W07 finish!
- **GB NESO 1-second Reference**: W02 is currently fetching NESO 1-second historical CSVs. We can also fetch a verified NESO 1-second CSV directly or read W02's output once available so we are never blocked.

## 4. Falsification Criteria
Our matching and calibration framework would be falsified if:
1. **Uncalibrated False Alarms**: On negative controls ($H_0$ recordings, wrong-day references, circular shifts), `policy.py` outputs `MATCH_SUPPORTED` at a rate exceeding our target false-alarm bound ($\alpha_{\text{FPR}} \le 5\%$ on dev, target $0\%$ on $H_0$).
2. **Failure on Clean Synthetic/Reference Traces**: On synthetic traces cut from real NESO / ENF-WHU 24h references with moderate additive noise ($\sigma \le 5\,\text{mHz}$, duration $D \ge 120\,\text{s}$), the matcher fails to recover the true timestamp within $\pm 2\,\text{s}$.
3. **Blindness Violation**: Any part of `matcher.py` or `policy.py` inspects `claimed_start_utc`, filenames, or metadata during the candidate search phase.
