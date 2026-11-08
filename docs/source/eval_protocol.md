# GhostClock — Frozen Evaluation & Statistical Audit Protocol (`eval/protocol.md`)

**Owner:** W10 (Forensic Statistician & Independent Critical Authority)  
**Version:** 1.0 (Frozen 2026-11-08 prior to holdout evaluation)  
**Authority:** Any worker claim, extractor promotion, or demo case that violates this protocol is subject to formal veto in `agents/reviews/W10_*.md`.

---

## 1. Epistemic Scope & Allowed Forensic Claims

1. **What GhostClock May Claim**:
   - That an extracted narrowband time-frequency sequence around nominal mains frequency ($50\,\text{Hz}$ or harmonics in audio; $100\,\text{Hz}$ illumination aliasing in rolling-shutter video) exhibits statistically calibrated correspondence (`MATCH_SUPPORTED`) or discrepancy (`MATERIAL_DISCREPANCY_REVIEW`) against an named, independent grid-frequency reference series over a stated search window `[search_start_utc, search_end_utc]`, or that the evidence is insufficient (`INCONCLUSIVE`).
2. **What GhostClock Must Never Claim**:
   - Categorical fraud, claimant dishonesty, complete media authenticity, physical location proof beyond grid interconnect compatibility, or automated claim denial/approval.
   - Any numerical "99.9% confidence" percentage not derived from an explicit, look-elsewhere-corrected null distribution (`p_empirical`).

---

## 2. Primary Evaluation Metrics & Statistical Uncertainty

Every experimental table and `RESULTS.json` across GhostClock workers must report denominators ($N_{\text{total}}$, $N_{\text{supported}}$, $N_{\text{inconclusive}}$, $N_{\text{discrepancy}}$) alongside point estimates and **95% Wilson score confidence intervals** for all proportions.

### 2.1 Core Metrics (Blind Discovery Mode: `claimed_start_utc = None`)
Let $\mathcal{D}_1$ be a set of positive recordings with known ground-truth start time $t_i^*$ within the search window, and $\mathcal{D}_0$ be a set of negative trials (either $H_0$ recordings with no ENF, or $H_1$ recordings matched against a **wrong** reference day/grid where the true timestamp is absent).

1. **Coverage (Support Rate on $H_1$)**:
   $$\text{Coverage} = \frac{1}{|\mathcal{D}_1|} \sum_{i \in \mathcal{D}_1} \mathbb{I}\left(\text{status}_i = \texttt{MATCH\_SUPPORTED}\right)$$
2. **Abstention Rate**:
   $$\text{Abstention Rate} = \frac{1}{|\mathcal{D}|} \sum_{i \in \mathcal{D}} \mathbb{I}\left(\text{status}_i = \texttt{INCONCLUSIVE}\right)$$
3. **Raw Top-1 Accuracy within Tolerance $\tau_{\text{tol}}$** ($\tau_{\text{tol}} \in \{5\,\text{s}\text{ (primary)}, 10\,\text{s}, 60\,\text{s}\}$; plus $\pm 1\,\text{s}$ secondary against per-file refined GT):
   $$\text{Acc}_{\text{raw}}(\tau_{\text{tol}}) = \frac{1}{|\mathcal{D}_1|} \sum_{i \in \mathcal{D}_1} \mathbb{I}\left(|\hat{t}_{i,1} - t_i^*| \le \tau_{\text{tol}}\right)$$
   - **Primary Timestamp Tolerance ($\pm 5\,\text{s}$)**: Independent alignment audit (`work/C1/DATASET_NOTES.md`, `work/W06/diagnose_lag.py`) established that ENF-WHU's recording-vs-`H1_ref` offset varies per file across $[-4.95, +4.47]\,\text{s}$ (bimodal near $-1..0\,\text{s}$ and $+3..+4\,\text{s}$ due to manual start-logging precision). Therefore, **$\pm 5\,\text{s}$ against README ground truth (`lag_ref`) is the mandatory primary tolerance**. Any $\pm 1\,\text{s}$ accuracy claim must be evaluated against the per-file refined ground truth ($t_{i,\text{refined}}^* = \text{lag\_ref}_i - d_i$ on reliable recordings with $r \ge 0.90$) and explicitly labelled as refined-GT.
   - **Ambiguous Reference Exclusion (`089-107_ref.wav`)**: In ENF-WHU Dev day `089-107_ref.wav`, repeated 1-hour blocks cause recordings `090` and `091` to match 7 distinct lags with $r = 1.000$ (`margin = 0.000`). A calibrated matcher must abstain (`INCONCLUSIVE` via uniqueness gate) when reference duplication destroys identifiability; accuracy metrics must report both all-Dev and unambiguous-GT denominators.
4. **Selective Accuracy Conditional on Output (`Acc | MATCH_SUPPORTED`)**:
   $$\text{Acc}_{\text{cond}}(\tau_{\text{tol}}) = \frac{\sum_{i \in \mathcal{D}_1} \mathbb{I}\left(\text{status}_i = \texttt{MATCH\_SUPPORTED} \;\wedge\; |\hat{t}_{i,1} - t_i^*| \le \tau_{\text{tol}}\right)}{\sum_{i \in \mathcal{D}_1} \mathbb{I}\left(\text{status}_i = \texttt{MATCH\_SUPPORTED}\right)}$$
   *(Note: If the denominator is 0, report `null` with $0/0$ denominator.)*
5. **False Positive Rate (FPR) on Negative Controls ($\mathcal{D}_0$)**:
   $$\text{FPR}_{H_0} = \frac{1}{|\mathcal{D}_0|} \sum_{j \in \mathcal{D}_0} \mathbb{I}\left(\text{status}_j \neq \texttt{INCONCLUSIVE}\right)$$
   Broken down separately into:
   - $\text{FPR}_{\text{no-ENF}}$: $H_0$ recordings (no mains hum/flicker) matched against real 24h grid references.
   - $\text{FPR}_{\text{wrong-day}}$: Authentic $H_1$ recordings matched against a 24h reference from the wrong date.
   - $\text{FPR}_{\text{surrogate}}$: Authentic $H_1$ recordings matched against circularly shifted or Fourier phase-randomized (AAFT) grid references.

### 2.2 Verification Mode Metrics (`claimed_start_utc` Supplied to Policy Only)
Each positive recording $i \in \mathcal{D}_1$ is tested under two claim scenarios:
- **Truthful Claim ($C_{\text{true}}$)**: `claimed_start_utc` $= t_i^*$.
- **Discrepant Claim ($C_{\text{false}}$)**: `claimed_start_utc` $= t_i^* + \Delta_{\text{shift}}$ with $|\Delta_{\text{shift}}| \ge 3600\,\text{s}$ (or another date).

1. **False Contradiction Rate (FCR) on Truthful Claims** *(The Harm That Hurts Most)*:
   $$\text{FCR} = \Pr\left(\text{status} = \texttt{MATERIAL\_DISCREPANCY\_REVIEW} \;\middle|\; C_{\text{true}}\right)$$
   *Why this is paramount:* In insurance claims investigation, an uncorroborated noisy recording should yield `INCONCLUSIVE`. Issuing `MATERIAL_DISCREPANCY_REVIEW` on a truthful claim wastes specialist investigation budget and risks unfair treatment of honest policyholders.
2. **True Discrepancy Detection Rate (TDDR) on Shifted Claims**:
   $$\text{TDDR} = \Pr\left(\text{status} = \texttt{MATERIAL\_DISCREPANCY\_REVIEW} \;\middle|\; C_{\text{false}}\right)$$
3. **Truthful Corroboration Rate (TCR)**:
   $$\text{TCR} = \Pr\left(\text{status} = \texttt{MATCH\_SUPPORTED} \;\middle|\; C_{\text{true}}\right)$$

### 2.3 Wilson Score 95% Confidence Interval Formula
For $k$ successes in $n$ trials ($p = k/n$, $z = 1.95996$):
$$\text{CI}_{95\%} = \frac{p + \frac{z^2}{2n} \pm z \sqrt{\frac{p(1-p)}{n} + \frac{z^2}{4n^2}}}{1 + \frac{z^2}{n}}$$
Every reported rate must include `[ci_low, ci_high]` via this exact formula.

---

## 3. Dataset Splits & Anti-Leakage Governance

### 3.1 Group-Preserving Dev / Holdout Splits
1. **ENF-WHU Dataset (`W03` / `W10`)**:
   - **Session Grouping ($H_1$)**: The 130 $H_1$ recordings map to 28 distinct 24-hour reference files (`H1_ref_one_day`, e.g., `003-004_ref.wav`, `005-014_ref.wav`). Splitting individual recordings from the same day across Dev and Holdout leaks day-specific grid dynamics and background environment. Therefore, the Dev/Holdout split **must partition the 28 reference days** ($\approx 60\%$ Dev, $40\%$ Holdout), assigning all recordings from a given day to the same split.
   - **Parent-Recording Grouping ($H_0$)**: The 40 cropped negative segments (`01.wav`–`40.wav`) in `H0` are exact waveforms cropped from the 10 parent recordings (`O01.wav`–`O10.wav`). Splitting crops separately from their parent `O01`–`O10` recordings is severe data leakage. The split **must partition the 10 parent recordings `O01`–`O10`** (6 Dev, 4 Holdout), placing every crop `01`–`40` into the same split as its parent recording.
2. **GB NESO Reference Series (`W02` / `C2` / `W10`)**:
   - Chronological split by non-overlapping calendar windows (e.g., Aug 2026 = Dev; Sep 2026 = Holdout).
   - **Mandatory Flat-Outage & Bad-Interval Masking**: C2 (`work/C2/FINDINGS.md`, `datasets/raw/gb/*.json`) identified flat-filled sensor outages in NESO 1-second data (e.g., `2026-09-15 07:30:03..10:35:59 UTC`, constant `49.895 Hz` for `11,158 s`; `2026-03-31 13:39:28 UTC`, constant `50.046 Hz` for `479 s`) and `0.0 Hz` placeholders in Elexon. Both the matcher (`work/W10/matcher.py`) and all null-sampling routines **must mask (`NaN` / weight `0`)** all sidecar `bad_intervals` AND any flat-filled stretch ($\ge 15$ consecutive constant samples), never matching or drawing null trials from flat stretches.
3. **Holdout Freeze Rule**:
   - All hyperparameters (STFT window/hop, harmonic weights, quality floor $q_{\min}$, correlation threshold, uniqueness margin, RMSE ceiling, split-half tolerance) **must be fixed exclusively on the Dev split**.
   - Holdout may be evaluated **once** per frozen method configuration to report unbiased generalization metrics. Tuning thresholds after inspecting Holdout results is an automatic veto offence.

### 3.2 Blindness & Anti-Leakage Rules
1. **No Metadata in Extraction or Search**:
   - Extractors (`W06`, `W07`, `W08`, `W09`) must never read filenames, file modification times (`mtime`), EXIF creation timestamps, or sidecar ground-truth labels.
   - Trace files (`.trace.npz` / `.trace.json`) must never contain wall-clock timestamps (`t` always starts at `0.0` seconds from media start).
2. **Blind Search Window**:
   - `matcher.match(...)` searches the entire `[search_start_utc, search_end_utc]` interval blindly.
   - `claimed_start_utc` is prohibited as an input to `match(...)` candidate generation; it may only be compared against the blind search result inside `policy.evaluate_policy(...)` after all candidates, scores, and p-values are computed.
   - Narrowing `search_start_utc` and `search_end_utc` around the ground-truth timestamp (e.g., searching only $\pm 5$ minutes around $t^*$ while claiming a 24-hour search) is prohibited and will be vetoed.

---

## 4. Required Baselines

Every proposed extractor or matcher must be compared against at least two explicit baselines on the same split:
1. **Baseline M0 (Metadata-Only Check)**:
   - Reads only container/EXIF creation timestamp (if present) without inspecting physical waveform/frames. Fails (`INCONCLUSIVE`) on stripped files (like ENF-WHU WAVs) and is trivially spoofed (`100%` false acceptance) on timestamp-edited files.
2. **Baseline M1 (Open-Source Matcher: `nate-griff/enf` `enf_compare.py`)**:
   - Unweighted FFT Pearson correlation ($40\%$) + uncentered $\pm 10\,\text{mHz}$ threshold coverage ($60\%$), $5\,\text{s}$ candidate separation, top-1 argmax without Bartlett $N_{\text{eff}}$ or look-elsewhere calibration.
3. **Baseline M2 (Uncalibrated i.i.d. Fisher-$z$ Matcher)**:
   - Uses standard Pearson correlation $r$ with naive sample count $N$ ($z \sqrt{N-3}$) rather than Bartlett's autocorrelation-adjusted $N_{\text{eff}}$.

---

## 5. Multimodal Evidence Combination Rules (Audio + Video)

1. **Physical Non-Independence**:
   - Audio ENF ($50\,\text{Hz}$ acoustic hum or electromagnetic induction) and visual ENF ($100\,\text{Hz}$ illumination flicker aliased by rolling shutter) recorded in the same clip measure the **same local electrical grid waveform**.
   - While sensor noises (microphone acoustic noise vs. camera shot/motion noise) may have independent components, the underlying signal $f_{\text{grid}}(t)$ and local environmental confounds (e.g., local generator, HVAC fan, or electronic ballast) are shared.
2. **Prohibition on Naive Confidence Multiplication**:
   - Workers must **never** multiply p-values ($p_{\text{joint}} = p_{\text{audio}} \times p_{\text{video}}$) or add log-odds ($L_{\text{joint}} = L_{\text{audio}} + L_{\text{video}}$) under an independence assumption.
3. **Permitted Multimodal Fusion Rules**:
   - **Rule MM-1 (Cross-Sensor Consistency Gate)**: Run blind matching independently on audio trace $\hat{f}_A(t)$ and video trace $\hat{f}_V(t)$. If both pass quality screening, require internal cross-sensor agreement $|\hat{t}_A - \hat{t}_V| \le \tau_{\text{agree}}$ (default $5\,\text{s}$) and positive zero-lag trace-to-trace correlation $r(\hat{f}_A, \hat{f}_V)$. Disagreement between audio and video ENF within the same clip is a red flag for either non-grid periodic interference (e.g., mechanical fan vs LED driver) or audio-visual desynchronization/splicing, forcing `INCONCLUSIVE` or `MATERIAL_DISCREPANCY_REVIEW`.
   - **Rule MM-2 (Quality-Weighted Trace Fusion Before Matching)**: Fuse $\hat{f}_A(t)$ and $\hat{f}_V(t)$ at the trace level using per-window quality weights:
     $$\hat{f}_{\text{fused}}(t) = \frac{q_A(t)\hat{f}_A(t) + q_V(t)\hat{f}_V(t)}{q_A(t) + q_V(t)}, \qquad q_{\text{fused}}(t) = \max(q_A(t), q_V(t))$$
     and run a **single** calibrated match of $\hat{f}_{\text{fused}}(t)$ against the grid reference, thereby evaluating a single look-elsewhere p-value without double-counting the grid sequence.
   - **Rule MM-3 (Conservative Bonferroni / Simes Bound)**: If combining modality p-values, use the conservative bound $p_{\text{combined}} = \min(1, 2 \min(p_A, p_V))$ when $|\hat{t}_A - \hat{t}_V| \le \tau_{\text{agree}}$, never $p_A \cdot p_V$.
