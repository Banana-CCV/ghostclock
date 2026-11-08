# W06 Experimental & Engineering Plan: Audio ENF Extractor A (STFT Family)

## 1. Orientation: Physical Constraints, Assumptions & Falsification Criteria

### Physical & Forensic Constraints
1. **Nominal Grid Frequency & Variations:** In Great Britain (NESO/Elexon) and China (ENF-WHU), the nominal mains frequency is $f_{\text{nom}} = 50\text{ Hz}$ (North America: $60\text{ Hz}$). Under normal interconnected grid operations, instantaneous frequency fluctuations rarely exceed $\pm 0.20\text{ Hz}$ around $f_{\text{nom}}$ (and on ENF-WHU, typically stay within $[49.90, 50.10]\text{ Hz}$).
2. **Harmonic Distribution in Audio:** Electromagnetic and acoustic mains hum couples into audio recordings at $f_0(t)$ and integer harmonics $h \cdot f_0(t)$ ($h \in \{1, 2, 3, 4, 5, 6, \dots\}$, i.e., $50, 100, 150, 200, 250, 300\text{ Hz}$). Smartphone and voice-recorder microphones strongly attenuate $50\text{ Hz}$ via front-end high-pass filters, making $100\text{ Hz}$ ($h=2$) and higher odd/even harmonics critical for recovery.
3. **ENF Presence vs. ENF Dating:** Detecting a narrowband tone near $50/100\text{ Hz}$ proves only that a periodic hum is present (**ENF presence**), *not* when the recording was made. Conversely, a clean $50\text{ Hz}$ electronic tone or inverter hum has high narrowband SNR but zero correlation with historical grid fluctuations.
4. **Blinded Provenance:** File timestamps, EXIF metadata, and filenames must never enter `analyse_audio()` or the output `.trace.npz`/`.trace.json`.

### Falsification Criteria (Pre-Declared Goalposts)
Our STFT-family multi-harmonic approach (`W06`) will be falsified or deemed insufficient if on the **ENF-WHU dev split**:
- **Trace Quality Gate:** Weighted multi-harmonic combination fails to outperform single-harmonic ($100\text{ Hz}$) STFT extraction on median Pearson correlation $r$ or median RMSE (mHz) against the paired ground-truth reference traces `H1_ref`.
- **Accuracy Target:** Median Pearson correlation across dev `H1` recordings falls below $r = 0.70$, or median fundamental-equivalent RMSE exceeds $15.0\text{ mHz}$.
- **Presence Detection Gate:** ENF-presence detection ROC AUC on dev `H1` (with ENF) vs. dev `H0` (without ENF) falls below $0.85$.
- **Codec Robustness Gate:** Re-encoding dev recordings with FFmpeg to MP3/AAC at $64\text{ kbps}$ degrades median correlation by more than $0.15$ (catastrophic collapse).

---

## 2. Literature Synthesis (Step B)

All methods in `work/W06/audio_enf.py` are grounded in primary peer-reviewed literature and verified against the reference MATLAB code in `datasets/raw/enf-whu/repo/`:

| Reference | DOI / URL | Method & Parameters in Source | What W06 Verified & Adopts |
| :--- | :--- | :--- | :--- |
| **Bykhovsky & Cohen (2013)**, "Electrical network frequency (ENF) maximum-likelihood estimation via a multitone harmonic model," *IEEE Trans. Inf. Forensics Security*, 8(5):744–753. | `10.1109/TIFS.2013.2253459` | Multi-tone MLE maximizing $\sum_{h} \|X(h f)\|^2$ over fundamental frequency grid $f \in [f_{\text{nom}}-\Delta, f_{\text{nom}}+\Delta]$. | Verified implementation in `func_STFT_multi_tone_search.m` ($f_s=800\text{ Hz}$, harmonics $2\text{–}7$, $16\text{ s}$ window, $1\text{ s}$ hop). Unweighted sum degrades when a single harmonic is corrupted by narrowband noise. |
| **Hajj-Ahmad, Garg & Wu (2013)**, "Spectrum combining for ENF signal estimation," *IEEE Signal Process. Lett.*, 20(9):885–888. | `10.1109/LSP.2013.2272526` | Weighted MLE (WMLE) weighting each harmonic $h$ by local SNR $w_h = P_{\text{sig},h} / P_{\text{noise},h}$ measured around $h f_{\text{nom}}$. | Verified implementation in `func_STFT_multi_tone_search_weighted.m` (signal band $[49.98, 50.02]\cdot h\text{ Hz}$, noise band $[49.90, 50.10]\cdot h\text{ Hz}$). We generalize to per-window local SNR weights with sub-bin peak interpolation. |
| **Hua, Liao, Wang, Zhang & Ye (2021)**, "Detection of electric network frequency in audio recordings – From theory to practical detectors," *IEEE Trans. Inf. Forensics Security*, 16:236–248. | `10.1109/TIFS.2020.3009579` | Derives LS-LRT, naive-LRT, and TF-domain variance detector $T_{\text{TF}} = \text{Var}(\hat{f}(t))$ exploiting slow variation of ENF vs random peaks under $H_0$. | Verified in `Fig14_real_world_recording_ROC.m` and `fun_STFT_interpo.m`. Note that TF variance alone can be fooled by stationary non-ENF tones, while SNR alone can be fooled by impulsive broadband energy; combining narrowband harmonic SNR with temporal stability and harmonic agreement gives a stronger detector. |
| **Hua, Liao, Zhang, Ye & Ma (2021)**, "Robust ENF estimation based on harmonic enhancement and maximum weight clique," *IEEE Trans. Inf. Forensics Security*, 16:3874–3887. | `10.1109/TIFS.2021.3099697` | Shows that pairwise correlation between harmonic traces identifies uncorrupted harmonics; evaluates on the 130-clip ENF-WHU dataset. | Verified in `main_comparison_recording_all.m`. Inspires our Iteration 1 enhancement: combining local SNR weights with inter-harmonic consistency weighting. |
| **Jacobsen & Kootsookos (2007)**, "Fast, accurate frequency estimators," *IEEE Signal Process. Mag.*, 24(3):123–125. | `10.1109/MSP.2007.361611` | Sub-bin DFT peak interpolation via quadratic/Gaussian log-magnitude fit and complex Jacobsen estimator. | Verified complex estimator in `fun_STFT_interpo.m` and compared against log-magnitude quadratic (Gaussian) peak interpolation on zero-padded Hann/Gaussian windows. |

---

## 3. Dataset Split & Ground-Truth Reference Protocol

1. **Split Consumption:**
   - Primary path: Read `eval/splits/enf_whu_split.json` produced by W03.
   - Fallback until W03's file lands: Use a deterministic session-stratified split (`seed = 42`, grouping `H1` by shared 24-hour reference `H1_ref_one_day` and `H0` crops `01–40` by their parent recording `O01–O10`, assigning $\approx 60\%$ to `dev` and $\approx 40\%$ to `holdout`), and automatically re-verify against `eval/splits/enf_whu_split.json` once available.
   - **Strict Holdout Discipline:** Only `dev` recordings are used for parameter sweeps, ablation studies, ROC threshold selection, and codec/noise robustness tuning. `holdout` is never touched during tuning.
2. **Reference ENF Extraction (`H1_ref`):**
   - Each `H1/<id>.wav` ($8000\text{ Hz}$) has a synchronous, same-duration power-mains reference recording `H1_ref/<id>_ref.wav` ($400\text{ Hz}$) centered at the $50\text{ Hz}$ fundamental.
   - Following `main_comparison_recording_all.m` (line 103) and `integration/interfaces.md`, the ground-truth reference trace $f_{\text{ref}}(t)$ at window centers $t_m$ is extracted from `H1_ref/<id>_ref.wav` around $50\text{ Hz}$ using a clean single-tone STFT with quadratic peak interpolation and mapped to fundamental-equivalent Hz ($\approx 50.0\text{ Hz}$).

---

## 4. Input/Output Schema & Architecture (`work/W06/audio_enf.py`)

### Frozen API (`integration/interfaces.md`)
- Function: `analyse_audio(path, config=None) -> (trace_npz_path, trace_json_path)`
- CLI: `python work/W06/audio_enf.py --in <media> --out <dir> [--nominal 50] [--config work/W06/config_default.json]`
- Output `<stem>.trace.npz`:
  - `t`: `float64` array $(M,)$, window centers in seconds from start of media.
  - `f`: `float64` array $(M,)$, fundamental-equivalent frequency in Hz ($\approx 50.0\text{ Hz}$), `NaN` where unusable.
  - `q`: `float64` array $(M,)$, per-window quality score in $[0, 1]$.
- Output `<stem>.trace.json`:
  - Matches `integration/interfaces.md` §1 exactly (`source`, `method`, `nominal_hz`, `harmonics_used`, `window_s`, `hop_s`, `fs_media`, `duration_s`, `media_sha256`, `params`, `quality_summary`, `provenance`, plus `enf_presence` diagnostics inside `quality_summary` / `params`).

---

## 5. Planned Experiments & Ablations (Steps E, F, G)

1. **Baseline vs. Multi-Harmonic Weighted Combination (Dev Split):**
   - Compare single-harmonic ($50\text{ Hz}$ only, $100\text{ Hz}$ only) vs. unweighted multi-harmonic average vs. SNR-weighted multi-harmonic combination (`WMLE-Trace` and `WMLE-Spectral+Trace` with harmonic consistency).
   - Metrics: Pearson correlation $r$ (mean, median, IQR, fraction $r > 0.8$), RMSE in mHz (mean, median, IQR).
2. **Window Length Sweep (Dev Split):**
   - Evaluate `window_s` $\in \{4.0, 8.0, 12.0, 16.0, 24.0\}\text{ s}$ with `hop_s = 1.0 s` against synchronous reference traces.
3. **ENF-Presence Detection (Dev H1 vs. Dev H0):**
   - Compare (a) narrowband harmonic SNR alone, (b) TF ridge variance alone (Hua et al. 2021), and (c) W06 composite presence detector (narrowband harmonic SNR + temporal first-difference stability + inter-harmonic coherence). Report ROC curve, AUC, TPR at $5\%$ and $10\%$ FPR.
4. **Codec & Noise Robustness (Dev Subset):**
   - Re-encode dev audio clips via `ffmpeg` to **MP3 (32 kbps, 64 kbps)** and **AAC (32 kbps, 64 kbps)**.
   - Inject synthetic additive white Gaussian noise (AWGN) at SNR $\in \{+10, 0, -10, -15\}\text{ dB}$ (explicitly labeled as synthetic noise perturbation on authentic recordings).
   - Measure degradation in correlation $r$ and RMSE (mHz).
5. **Critique & Failure Analysis:**
   - Identify worst-performing dev `H1` recordings and false-positive dev `H0` recordings; inspect their spectrograms and harmonic SNRs to explain why they fail and how $q(t)$ / presence gating behaves.
