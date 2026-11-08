# W14 Adversarial Red Team — Experimental Plan (`PLAN.md`)

## 1. Mission & Role
Worker **W14** is the adversarial red team and stress-tester for **GhostClock**. Our objective is to:
1. Systematically attack the ENF extraction and matching pipeline across **7 distinct attack families (a–g)** on both authentic recordings (**ENF-WHU dev split**) and labelled synthetic recordings generated from real **NESO 1-second GB grid frequency traces**.
2. Quantify when and how an unguarded baseline pipeline produces a **WRONG confident decision** (specifically: a `MATCH_SUPPORTED` status at an incorrect timestamp $|\hat{t} - t_{\text{true}}| > 30\text{ s}$, or a confident match on a forged/tampered recording, or a false `MATERIAL_DISCREPANCY_REVIEW` on an authentic recording at its true claimed timestamp).
3. Design, implement, and evaluate **6 deterministic code-enforced guards (`G1`–`G6`)** that intercept adversarial manipulations and degraded edge cases, shifting dangerous wrong-confident verdicts to safe abstentions (`INCONCLUSIVE`) or human-review escalations (`MATERIAL_DISCREPANCY_REVIEW` / `TAMPER_SUSPECTED_REVIEW`).
4. Measure the **False-Alarm Cost (FPR)** of each guard individually and jointly on unmodified authentic dev clips, ensuring guards do not destroy legitimate utility.
5. Deliver `work/W14/ATTACK_MATRIX.md` with the complete `attack × outcome × guard × residual risk` table and an honest accounting of **what we cannot defend against** for the pitch deck.

---

## 2. Literature Grounding (Step B Summary)
1. **Chuang, Garg, & Wu (2013)**, *"Anti-Forensics and Countermeasures of Electrical Network Frequency Analysis"*, IEEE TIFS, 8(12), 2073–2088, DOI: `10.1109/TIFS.2013.2287082`. Establishes notch-filter removal, FM-sinusoid trace spoofing, and countermeasures via harmonic inconsistency and boundary artefacts.
2. **Nicolalde-Rodríguez, Apolinário, & Biscainho (2010)**, *"Audio Authenticity: Detecting ENF Discontinuity With High Precision Phase Analysis"*, IEEE TIFS, 5(3), 534–543, DOI: `10.1109/TIFS.2010.2051270`, and **Esquef et al. (2014)**, IEEE TIFS, 9(12), 2314–2326, DOI: `10.1109/TIFS.2014.2363524`. Establishes phase/instantaneous-frequency jump detection and segment-wise lag consistency for audio splicing/concatenation.
3. **Hua, Liao, Zhang, Ye, & Ma (2021)**, *"Robust ENF Estimation Based on Harmonic Enhancement and Maximum Weight Clique"*, IEEE TIFS, 16, 3874–3887, DOI: `10.1109/TIFS.2021.3099697`, and **Hua et al. (2021)**, IEEE TIFS, 16, 236–248, DOI: `10.1109/TIFS.2020.3009579`. Shows ENF-WHU recordings carry ENF across harmonics $h \in \{2..7\}$ ($100\text{–}350\text{ Hz}$) and that pairwise inter-harmonic correlation isolates uncorrupted harmonics.
4. **Hua (2018)**, *"Error Analysis of Forensic ENF Matching"*, IEEE WIFS 2018, DOI: `10.1109/WIFS.2018.8630786`, and **Hajj-Ahmad, Garg, & Wu (2013)**, IEEE SPL, 20(9), 885–888, DOI: `10.1109/LSP.2013.2279112`. Quantifies how short clip durations and low SNR inflate false peak correlations over 24-hour search windows due to ENF autocorrelation.

---

## 3. Dataset Split & Reference Data Hygiene
To guarantee **zero holdout contamination**:
- We load `eval/splits/enf_whu_split.json` and `datasets/manifests/enf_whu_cases.csv` (from `W03`) directly and filter strictly to `split == "dev"`. Zero `holdout` files are ever read or evaluated.
- **Clean Dev False-Alarm Evaluation Set (`dev` split):**
  - Evaluated across **all 36 exact-waveform and trace-aligned `H1` dev clips** from distinct recording sessions (including the 12 core attack-matrix clips `001, 002, 003, 006, 008, 014, 026, 035, 064, 070, 089, 118` spanning 10 distinct dev days and both alignment regimes) plus **all 6 parent `H0` dev clips** (`O01, O02, O03, O04, O07, O10`).
- **Real NESO GB 1-Second Reference Data (`[SYNTHETIC-NESO]` experiments):**
  - Loaded via `work/W02/gb_reference.py` from `datasets/raw/neso/`:
    - **Day A (Authentic Reference Day):** `2026-08-01` (`1785542400` to `1785628799` UTC, 86,400 s at 1 s cadence).
    - **Day B (Adversarial Spoof / Wrong Date Reference):** `2026-09-01` (`1788220800` to `1788307199` UTC, 86,400 s at 1 s cadence).
  - All audio clips synthesized from NESO traces are explicitly tagged `synthetic_neso=True` in manifests, JSON outputs, and plots.

---

## 4. Baseline Extractor & Matcher (Fallback + Sibling Integration)
Our harness (`work/W14/baseline_pipeline.py`) dynamically checks if `work/W06/audio_enf.py` and `work/W10/matcher.py` exist and are importable; when available, it runs them read-only alongside our built-in deterministic STFT multi-harmonic extractor + FFT sliding NCC matcher conforming strictly to `integration/interfaces.md` §1–4:
- **Extractor (`extract_enf_trace`):**
  - Decodes audio to float64, downsamples to $f_s = 1000\text{ Hz}$ via zero-phase anti-aliasing filter (`scipy.signal.resample_poly`), extracts STFT ridges ($W = 16\text{ s}$ Hann window, $H = 1\text{ s}$ hop, zero-padded to $0.005\text{ Hz}$ bin spacing with quadratic log-magnitude peak interpolation) around harmonics $h \in \{1, 2, 3, 4, 5, 6, 7\}$ ($50\text{–}350\text{ Hz}$).
  - Computes per-harmonic local SNR weight $w_h(t)$ relative to flanking noise bands $[50h \pm 1.5, 50h \pm 4.0]\text{ Hz}$, yielding SNR-weighted fundamental-equivalent trace $f(t) = \sum_h w_h(t) (f_h(t)/h)$ and per-harmonic matrix $F_{h}(t)$ for guard inspection.
- **Unguarded Baseline Matcher (`match_ungated`):**
  - Sliding FFT-based normalized cross-correlation (NCC) over the full 24-hour reference (86,400 candidate lags at 1 s cadence).
  - Unguarded baseline decision rule: issues `MATCH_SUPPORTED` whenever peak correlation $r_{\text{peak}} \ge 0.45$ and median SNR $\ge 3.0\text{ dB}$ (representing a typical naive ENF matcher without adversarial guards).

---

## 5. Attack Matrix Specification (Attacks a–g)
Every attack is implemented in `work/W14/attacks.py` with fixed random seed (`seed = 20261108`):

| ID | Attack Family | Parameter Variants Tested | Target Outcome |
|---|---|---|---|
| **(a)** | **ENF Removal (Notch Filtering)** | Cascade of narrowband IIR notch filters ($Q=35$ and $Q=15$) at: (a1) $50\text{ Hz}$ only; (a2) $50, 100, 150\text{ Hz}$; (a3) all harmonics $50, 100, 150, 200, 250, 300, 350\text{ Hz}$. | Strip true ENF to evade dating or trigger a false match on residual noise. |
| **(b)** | **ENF Injection (Spoofing)** | Continuous-phase FM sinusoid $\cos(2\pi \int f_{\text{spoof}}(\tau)d\tau)$ from a **wrong date's reference** (Day B NESO or another day's ENF-WHU ref) injected into: (b1) `H0` (no-ENF clip) as single-tone 100 Hz at SNR $\in \{-15, -5, +5\}\text{ dB}$; (b2) `H0` as multi-harmonic ($h=1..4$, fixed amplitude) at $+5\text{ dB}$; (b3) `H1` (authentic clip with true ENF) at SNR $\in \{-5, 0, +5, +10\}\text{ dB}$ relative to original hum. | Force `MATCH_SUPPORTED` at the attacker's chosen fake timestamp $t_{\text{spoof}}$. |
| **(c)** | **Double ENF (Two Concurrent Traces)** | Simultaneous presence of two real grid traces: (c1) `H1` clip mixed with a second real `H1_ref` trace at equal ($0\text{ dB}$) and $+3\text{ dB}$ harmonic power; (c2) Harmonic split double-ENF (true trace at $h=2,4,6$, spoof trace injected at $h=1,3$). | Confuse weighted harmonic combiner into matching the wrong timestamp or producing a chimeric trace. |
| **(d)** | **Re-encoding, Noise Suppression & Pitch/Time Transforms** | (d1) `ffmpeg` AAC 32 kbps; (d2) `ffmpeg` VoIP codec 20 kbps (WhatsApp voice-note profile, VoIP application + 8 kHz/16 kHz); (d3) `ffmpeg` MP3 64 kbps; (d4) Phone noise suppression simulated via heavy spectral gating (`SNRfloor` suppression of stationary narrowband tones); (d5) Resampling chain ($8000 \to 11025 \to 8000\text{ Hz}$ and $+0.2\%$ clock drift); (d6) Time-stretch without pitch change (`ffmpeg -af atempo=1.05` and `atempo=1.25`); (d7) Pitch shift without duration change (`asetrate` + `atempo` by $+2\%$ and $+5\%$). | Degrade or warp $f(t)$ to cause false contradiction (`MATERIAL_DISCREPANCY_REVIEW`) on an authentic clip or wrong timestamp match. |
| **(e)** | **Cropping to Short Durations** | Crop authentic `H1` clips to $D \in \{10, 20, 30, 60, 120, 300\}\text{ s}$ and search across a 24-hour (86,400 s) reference window. | Exploit look-elsewhere effect so a short clip matches a wrong timestamp with high $r_{\text{peak}}$. |
| **(f)** | **Concatenating Clips from Different Times (Splicing)** | (f1) 50/50 butt-splice of two 180 s clips from different timestamps ($t_A \neq t_B$, total 360 s); (f2) 70/30 asymmetric splice (210 s from $t_A$ + 90 s from $t_B$); (f3) Insertion splice (120 s $t_A$ + 60 s $t_B$ + 120 s $t_A$). | Make the global matcher return `MATCH_SUPPORTED` at $t_A$ while overlooking the forged segment $t_B$. |
| **(g)** | **Metadata Spoofing** | Embed forged creation timestamps (`creation_time="2024-01-01T00:00:00Z"`, WAV `ICRD` chunk, spoofed filename `2024-01-01_120000_claim.wav`, and mismatched `claimed_start_utc`). | Verify bit-for-bit that `extract_enf_trace` and blind `match` produce identical numerical outputs (`Δscore = 0.0`, `Δlag = 0`), while the post-search policy flags `MATERIAL_DISCREPANCY_REVIEW` when `claimed_start_utc` contradicts the verified ENF timestamp. |

---

## 6. Deterministic Guards (`work/W14/guards.py`)
We design and evaluate 6 code-enforced guards:
1. **`G1: spectral_notch_guard` (Defends Attack a & d4):**
   - Measures the power spectral density dip at nominal harmonic bins $50h \pm 0.25\text{ Hz}$ relative to immediate flanking shoulders $[50h - 3.0, 50h - 0.5] \cup [50h + 0.5, 50h + 3.0]\text{ Hz}$. If narrowband power is suppressed significantly *below* the local background noise floor ($\text{dip} < -4.5\text{ dB}$ across $\ge 2$ harmonics) or stationary spectral gating zeroed out sub-bands, flags `NOTCH_OR_SUPPRESSION_DETECTED` and blocks `MATCH_SUPPORTED`.
2. **`G2: too_clean_injector_guard` (Defends Attack b1, b2):**
   - Real mains hum captured acoustically or inductively exhibits natural temporal amplitude modulation (coefficient of variation $\text{CV}_A = \sigma_A / \mu_A$), multi-harmonic energy distribution, and micro-phase jitter. A naive synthetic FM sinusoid injected at constant amplitude has abnormally low amplitude CV ($\text{CV}_A < 0.08$), abnormally high concentration in a single harmonic ($>96\%$ of total harmonic energy at high SNR $>12\text{ dB}$), or unnatural harmonic envelope correlation. Flags `SYNTHETIC_INJECTION_SUSPECTED`.
3. **`G3: harmonic_consistency_guard` (Defends Attack b3, c1, c2, d7):**
   - For all harmonics $h \in \{1..7\}$ with median local $\text{SNR}_h > 3.0\text{ dB}$, compares their fundamental-equivalent traces $f_h(t)/h$. Requires at least 2 active harmonics OR (if $\ge 2$ harmonics are active) requires pairwise correlation $r(f_{h_1}/h_1, f_{h_2}/h_2) \ge 0.45$ and inter-harmonic RMSE $\le 25\text{ mHz}$, and checks that the mean fundamental offset $|\bar{f}_h/h - 50.0| \le 0.25\text{ Hz}$ (catching pitch shifts). Flags `HARMONIC_INCONSISTENCY_OR_DOUBLE_ENF` or `PITCH_SHIFT_DETECTED`.
4. **`G4: split_half_and_splice_guard` (Defends Attack d5, d6, e, f1, f2, f3):**
   - Splits the extracted trace into First Half $S_1 = [0, T/2]$ and Second Half $S_2 = [T/2, T]$ (plus 3 overlapping sub-segments for clips $\ge 180\text{ s}$) and matches each independently against the 24-hour reference:
     - Requires $|\hat{t}(S_2) - (\hat{t}(S_1) + T/2)| \le 5\text{ s}$ (consistent lag progression).
     - If $\hat{t}(S_1)$ and $\hat{t}(S_2)$ both achieve strong individual peaks at *different* timeline offsets ($|\Delta \text{lag}| > 15\text{ s}$), flags `SPLICE_OR_CONCATENATION_DETECTED` (`MATERIAL_DISCREPANCY_REVIEW`).
     - If $\hat{t}(S_2) - \hat{t}(S_1)$ drifts proportionally to duration, flags `TIME_STRETCH_OR_RESAMPLE_DRIFT`.
5. **`G5: duration_and_uniqueness_guard` (Defends Attack e & low-SNR attacks):**
   - Enforces minimum valid ENF duration $T_{\text{valid}} \ge 60\text{ s}$ for blind 24-hour dating, peak-to-second-best non-overlapping peak margin $\Delta r = r_1 - r_2 \ge 0.08$ (and z-score against empirical null $z_{\text{null}} \ge 4.5$). Short clips ($<60\text{ s}$) are deterministically routed to `INCONCLUSIVE` for blind timestamping (though speed-check remains permitted).
6. **`G6: audio_video_agreement_guard` (Defends cross-modal audio replacement on video clips):**
   - When both an audio ENF trace $f_A(t)$ and a visual rolling-shutter ENF trace $f_V(t)$ are present for the same media file, checks that their matched timestamps agree ($|\hat{t}_A - \hat{t}_V| \le 5\text{ s}$) and direct trace correlation $r(f_A, f_V) \ge 0.35$. Tested on synthetic dual-modality pairs (authentic audio + authentic/spoofed video ENF trace).

---

## 7. Falsifiable Hypotheses & Success Thresholds
1. **H1 (Vulnerability of Unguarded Baseline):** Without guards `G1`–`G6`, at least 4 of the 7 attack families (specifically: (b) ENF injection, (c) Double ENF, (e) Short crops $\le 30\text{ s}$, and (f) Spliced concatenation) will cause the unguarded baseline to output a **WRONG confident `MATCH_SUPPORTED` decision** on $\ge 50\%$ of attacked test cases.
2. **H2 (Guard Effectiveness):** Enabling the deterministic guard suite (`G1`–`G6`) reduces the **Wrong Confident Match Rate (`MATCH_SUPPORTED` on wrong timestamp or forged trace)** across Attacks (a)–(f) by $\ge 80\%$ relative to the unguarded baseline (excluding physical-limit white-box full-harmonic room-convolved spoofing, which we explicitly prove is an unguarded residual risk).
3. **H3 (Bounded False-Alarm Cost on Clean Dev Clips):** On unmodified authentic ENF-WHU dev `H1` recordings that pass baseline matching, the combined false-alarm rate of the adversarial anomaly guards (`G1` Notch, `G2` Too-Clean, `G3` Harmonic Inconsistency, `G4` Splice) must be $\le 15\%$, and **0%** of clean `H1` or `H0` clips may be falsely matched to a wrong timestamp.
4. **H4 (Strict Blindness to Metadata Spoofing):** On Attack (g), the SHA-256 of the extracted frequency array `f` and blind match candidate scores must be identical (`max |Δf| == 0.0`, `max |Δscore| == 0.0`) before and after spoofing filenames, WAV header tags, and claimed timestamps.
