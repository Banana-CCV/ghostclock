# W14 Orientation (`ORIENT.md`) — Adversarial Red Team & Stress-Testing

## 1. Context & Objective
Worker **W14** serves as the adversarial red team for **GhostClock**. An insurance claims corroboration system faces an explicit adversarial threat model: a claimant or third party may manipulate a recording to:
1. **Evade a timestamp discrepancy** by stripping or corrupting the real ENF signal so the system abstains (`INCONCLUSIVE`) instead of flagging a contradiction, or matches a random noise peak.
2. **Spoof a false timestamp** by injecting a synthetic ENF signal corresponding to the claimed date/time (using publicly available NESO 1-second historical grid frequency data) into a recording made on a different date or in an environment without mains hum.
3. **Splice or edit a recording** by concatenating an authentic ambient recording from the claimed time with a short edited/inserted segment containing the disputed statement or event.
4. **Launder media through lossy codecs, noise suppression, or speed/pitch transforms** (WhatsApp voice notes (VoIP codec), AAC 32 kbps, MP3 64 kbps, smartphone stationary noise suppression, resampling, WSOLA time-stretching, or pitch shifting).
5. **Spoof container metadata, filenames, or EXIF creation timestamps** while leaving the underlying audio/video untouched.

Our goal is twofold:
- **Break the pipeline first:** Demonstrate quantitatively where an unguarded STFT + NCC pipeline (`M0_naive`) and the current `W06 + W10` pipeline (`W06_W10_base`) produce **WRONG confident answers** (`MATCH_SUPPORTED` at an incorrect or forged timestamp, or `MATCH_SUPPORTED` on a spliced/manipulated clip).
- **Harden the pipeline with deterministic code guards (`G1`–`G6`):** Design, implement, and calibrate 6 physical and statistical consistency guards that catch these attacks in code (never relying on LLM prompt instructions), measure their **False-Alarm Cost (FPR)** on unmodified authentic `dev` recordings, and document the **honest residual risk** (what cannot be defended against) for the competition pitch deck.

---

## 2. Physical & Statistical Assumptions
1. **Multi-Harmonic Capture Physics:** Authentic acoustic and electromagnetic mains hum in 50 Hz environments rarely appears as a pure single sinusoid with constant envelope. Nonlinear transformer core saturation ($B\text{-}H$ hysteresis), bridge rectifiers, and acoustic room transfer functions distribute energy across multiple harmonics ($h \in \{1..7\}$, i.e., $50\text{–}350\text{ Hz}$) with time-varying amplitude envelopes ($\text{CV}_A = \sigma_A / \mu_A > 0.08$) driven by room motion and background acoustics.
2. **Harmonic Trajectory Coherence:** All genuine grid harmonics $h \in \{1..7\}$ originate from the same synchronous generator rotor angle $\theta(t)$:
   $$f_h(t) = h \cdot f_1(t) + \epsilon_h(t)$$
   Consequently, their fundamental-equivalent traces $f_h(t)/h$ must exhibit positive pairwise correlation and near-zero mean frequency offset across all active harmonics.
3. **Temporal Affine Continuity:** In an unedited continuous recording with nominal sample rate $f_s$, any sub-segment $S_k = [t_k, t_k + L]$ must align to the reference grid at lag $\hat{\tau}(S_k) \approx \tau_0 + t_k$. A splice violates piecewise constant lag offset ($\hat{\tau}(S_j) - t_j \neq \hat{\tau}(S_i) - t_i$), while resampling or WSOLA time-stretching introduces a linear lag drift $\Delta \hat{\tau}(t) \approx (\alpha - 1)t$ or sideband phase instability.
4. **Look-Elsewhere Effect on Short Clips:** Because grid frequency $f(t)$ is a narrowband Ornstein-Uhlenbeck-like random process with strong autocorrelation ($\tau_{\text{corr}} \approx 15\text{–}30\text{ s}$), searching a short clip ($D \le 30\text{ s}$, effective degrees of freedom $N_{\text{eff}} < 10$) across 86,400 candidate lags produces high spurious correlations ($r_{\text{peak}} > 0.65$) purely by chance.

---

## 3. Available Data & Sibling Code Verified on Disk
- **ENF-WHU Dataset (`datasets/raw/enf-whu/repo/ENF-WHU-Dataset/`):**
  - 130 `H1` authentic recordings (8 kHz WAV, 5–16 min), 130 `H1_ref` synchronized reference files (400 Hz), 28 `H1_ref_one_day` 24-hour reference files (400 Hz), and 50 `H0` non-ENF recordings.
  - Frozen split at `eval/splits/enf_whu_split.json` and `datasets/manifests/enf_whu_cases.csv` (78 `H1` dev, 30 `H0` dev; 52 `H1` holdout, 20 `H0` holdout). **W14 touches ONLY `dev` rows.**
- **NESO GB 1-Second Historical Reference (`datasets/raw/neso/`):**
  - `neso_2026-08.parquet` and `neso_2026-09.parquet` verified on disk via `work/W02/gb_reference.py`. We use `2026-08-01` (Day A) and `2026-09-01` (Day B) for `[SYNTHETIC-NESO]` experiments.
- **Sibling Pipeline Modules (Imported Read-Only):**
  - `work/W03/enf_whu.py` (`_fast_baseband_enf_50hz` for 24-hour reference trace extraction).
  - `work/W06/audio_enf.py` (`extract_audio_enf_detailed`, `analyse_audio`).
  - `work/W07/audio_enf_b.py` (`extract_audio_enf_b`).
  - `work/W10/matcher.py` and `work/W10/policy.py` (`match`, `evaluate_policy`).
  - `work/W13/splice_check.py` and `work/W13/speed_check.py` (`check_splice_array`, `check_speed_audio_array`).

---

## 4. What Result Would Falsify Our Approach?
1. **Baseline Vulnerability Falsification (`H1`):** If the unguarded baseline pipeline (`M0_naive`) or `W06 + W10` without W14 guards already blocks $\ge 80\%$ of attacks across (a)–(f) without issuing wrong `MATCH_SUPPORTED` decisions, then our claim that adversarial red-teaming is necessary would be falsified.
2. **Guard Efficacy Falsification (`H2`):** If adding guards `G1`–`G6` fails to reduce the wrong-confident `MATCH_SUPPORTED` rate across attacks (a)–(f) by at least $80\%$ relative to the unguarded baseline, our guard design is insufficient.
3. **False-Alarm Cost Falsification (`H3`):** If enabling `G1`–`G6` causes $>15\%$ of clean, unmodified authentic dev `H1` clips (that otherwise pass baseline matching) to be falsely flagged as tampered/anomalous, then the guards are over-sensitive and destroy practical utility.
4. **White-Box Spoofing Limit:** If a white-box attacker who synthesizes a full harmonic family ($h=1..7$) with realistic $1/h$ spectral roll-off, stochastic room-impulse-response (RIR) envelope modulation, and phase jitter into an ENF-free (`H0`) recording *were* claimed to be 100% detectable from audio alone, that claim would violate physical identifiability. We explicitly test this white-box attack (`b4_whitebox_multi_rir`) to demonstrate the true boundary of what ENF forensics can and cannot defend against.
