# GhostClock W06 — Handoff & Integration Guide (Audio ENF Extractor A: Multi-Harmonic STFT)

- **Worker**: `W06` (Audio DSP Engineer — Approach A, STFT Multi-Harmonic Family)
- **Status**: `DONE` (`evidence_grade: "B"`, independently verified on smoke by Director in `agents/reviews/director_verify_w06.py`; evaluated on full official ENF-WHU Dev split `N = 78 H1`, `N = 30 H0` in `work/W06/RESULTS.json`).

---

## 1. What to Promote to the Final GhostClock Build

### Recommended Primary Production Modules (`work/W06/`)
1. **`work/W06/audio_enf.py`** — **Promote to `ghostclock/audio_enf.py` (or primary audio extractor in `W12`)**.
   - **Why**:
     - Implements `analyse_audio(path, config) -> (trace_npz_path, trace_json_path)` strictly conforming to `integration/interfaces.md` (`t, f, q` 1-D `float64` arrays at 1 Hz hop, `meta` dict in `<stem>.trace.json`, plus per-harmonic diagnostics and `enf_presence` metadata).
     - **Zero group delay (`0.000 s`)**: Uses forward-backward `scipy.signal.sosfiltfilt` anti-alias and harmonic band-pass filters and exact window-center timestamps (`t = k * hop_sec + win_sec / 2.0`), introducing zero timestamp bias for `W10`.
     - **Fast & dependency-light**: Runs in **`0.71 s` per 6-minute audio file** on CPU using only `numpy`, `scipy`, and `ffmpeg`.
     - **High accuracy on authentic ambient recordings**: Achieves **median $r = 0.9841$** ($\text{RMSE} = 3.469\text{ mHz}$) at strict lag `0 s` and **median $r = 0.9956$** ($\text{RMSE} = 1.920\text{ mHz}$) within $\pm 5\text{ s}$ across all `78` Dev `H1` clips, with **`96.15%` (`75/78`)** exceeding $r \ge 0.70$.
     - **Built-in ENF-presence gate (`compute_enf_presence`)**: Separates `H1` vs `H0` with **ROC AUC = `0.9910`** (`0.9927` via `multi_harmonic_snr_db`) and **`96.15%` TPR at `5%` FPR**, preventing false-positive dating on recordings that contain no grid hum.
     - **Lossy codec invariance**: `< 0.0002` correlation loss under `32 kbps` and `64 kbps` MP3 and AAC re-encoding.
2. **`work/W06/config_default.json`** — **Promote as default audio extraction configuration**.
   - Frozen Dev-tuned defaults: `nominal_hz: 50.0`, `harmonics: [1, 2, 3, 4, 5, 6]`, `fs_proc: 1000.0`, `win_sec: 16.0`, `hop_sec: 1.0`, `nfft: 32768`, `combination_mode: "snr_robust_hybrid"`, `presence_threshold: 0.56`.

### Integration Call Signature for `W10` (Matcher) & `W12` (Pipeline)
```python
from work.W06.audio_enf import analyse_audio, load_default_config

cfg = load_default_config()
cfg["output_dir"] = "path/to/output_traces"
npz_path, json_path = analyse_audio("path/to/evidence.mp3", cfg)
```
- **Note for `W10` (Matcher / Alignment Scoring)**:
  - Check `meta["enf_presence"]["is_present"]` (or `meta["enf_presence"]["score"] >= 0.56`) before attempting grid alignment; if `False`, report `INSUFFICIENT_ENF` rather than forcing a spurious timestamp match.
  - Pass `q` (saved in `<stem>.trace.npz["q"]`) directly as frame weights $w(t) = q(t)$ in weighted normalized cross-correlation so transient low-SNR frames (`q < 0.2`) do not pull the correlation peak.
  - When evaluating timestamp accuracy on ENF-WHU (`H1` vs `H1_ref`), account for the dataset's intrinsic $\pm 2\text{ s}$ median ($\pm 4\text{ s}$ p90, `100%` within $\pm 5\text{ s}$) recording start-time offset documented in `work/W06/RESULTS.json["lag_and_group_delay_diagnosis"]`.

---

## 2. Deck-Worthy Headline Numbers (All Real-Measured on Official Dev Split)

| Claim / Metric | Measured Value | Denominator / Split | Source in `work/W06/RESULTS.json` |
| :--- | :--- | :--- | :--- |
| **Multi-Harmonic vs 50 Hz Fundamental** | Median $r$: **`0.9841` vs `0.1108`** (`+0.8733`); $r \ge 0.80$: **`85.9%` (`67/78`) vs `0.0%` (`0/78`)** | `N = 78` Dev `H1` (strict lag `0 s`) | `experiment_1_harmonic_combination_ablation` |
| **Multi-Harmonic vs Single-100 Hz Baseline** | Median RMSE: **`3.47 mHz` vs `4.82 mHz`** (`-28.0%` error); $r \ge 0.80$: **`85.9%` (`67/78`) vs `73.1%` (`57/78`)** (`+12.8 pp`) | `N = 78` Dev `H1` (strict lag `0 s`) | `experiment_1_harmonic_combination_ablation` |
| **Aligned Extraction Accuracy ($\pm 5\text{ s}$ dataset offset)** | Median $r = \mathbf{0.9956}$ (IQR `0.9693–0.9980`), Median RMSE = **`1.92 mHz`** (`1.49 mHz` centered), $r \ge 0.80$: **`91.0%` (`71/78`)** | `N = 78` Dev `H1` | `experiment_1_harmonic_combination_ablation.snr_robust_hybrid_aligned_5s` |
| **ENF-Presence Detection (`H1` vs `H0`)** | **ROC AUC = `0.9910`** (`0.9927` multi-harmonic SNR); **TPR = `96.2%` (`75/78`) at `5%` FPR** | `78 Dev H1` vs `30 Dev H0` (`N = 108`) | `experiment_3_presence_detection_roc` |
| **MP3 & AAC Low-Bitrate Robustness (`32/64 kbps`)** | WAV: `0.9885` $\rightarrow$ MP3 32k: **`0.9885` ($\Delta r = 0.0000$)**; AAC 32k: **`0.9883` ($\Delta r = -0.0002$)** | `N = 10` Stratified Dev `H1` | `experiment_4a_codec_robustness` |
| **Algorithmic Group Delay** | **`0.000 s`** ($r = 0.9937$ at lag `0 s`) | Synthetic FM verification + 75 Dev `H1` lag audit | `lag_and_group_delay_diagnosis` |

---

## 3. Deck-Worthy Figures in `work/W06/plots/` (With Required Provenance Captions)

All 4 figures exist on disk in `work/W06/plots/` at 180 DPI in the GhostClock dark forensic palette:

1. **`work/W06/plots/spectrogram_tracked_ridge.png`** (`1,066,497` bytes)
   - **Caption**: `REAL-MEASURED` — Six-harmonic zero-padded STFT spectrograms (`50–300 Hz`) on authentic ENF-WHU Dev recording `H1/003.wav` showing complete absence of fundamental 50 Hz (`-0.2 dB` SNR, $r = 0.085$), noisy 100 Hz (`+1.6 dB`, $r = 0.246$), and high-SNR 200/300 Hz ridges (`+17.0/+17.8 dB`) fused by W06 into a `r = 0.9760` (`0.9994` aligned) trace.
2. **`work/W06/plots/extracted_vs_reference_overlays.png`** (`698,879` bytes)
   - **Caption**: `REAL-MEASURED` — Extracted W06 audio ENF traces vs ground-truth power-grid reference (`H1_ref`) across four representative ENF-WHU Dev clips (`H1/012` clean indoor $r = 0.9990$, `H1/003` multi-harmonic rescue $r = 0.9760 \rightarrow 0.9994$, `H1/092` moderate SNR $r = 0.9756$, and `H1/005` low-SNR failure mode $r = 0.6596$).
3. **`work/W06/plots/error_histograms_and_ablations.png`** (`278,607` bytes)
   - **Caption**: `REAL-MEASURED` — Full ENF-WHU Dev split (`N = 78 H1`) empirical CDF of Pearson $r$, error/RMSE distributions across 5 harmonic combination methods, STFT window length trade-off (`4 s` to `24 s`), and per-file `H1` vs `H1_ref` dataset start-time offset histogram (`100%` within $\pm 5\text{ s}$).
4. **`work/W06/plots/presence_roc_and_robustness.png`** (`246,802` bytes)
   - **Caption**: `REAL-MEASURED` (Panels A–B) / `SEMI-SYNTHETIC` (Panel C: real ENF-WHU Dev `H1` audio mixed with calibrated broadband AWGN) — ENF-presence ROC curves (`78 Dev H1` vs `30 Dev H0`, AUC = `0.9910–0.9927`), `H1` vs `H0` score distributions, and robustness to FFmpeg MP3/AAC (`32/64 kbps`) re-encoding and additive white Gaussian noise (`+10 dB` to `-15 dB`).

---

## 4. Complete File Inventory (`work/W06/`)

- `work/W06/audio_enf.py` — Core extractor & CLI (`analyse_audio`, `extract_audio_enf_detailed`, `extract_reference_enf`, `compute_enf_presence`).
- `work/W06/config_default.json` — Frozen Dev-tuned defaults.
- `work/W06/diagnose_lag.py` & `work/W06/lag_diagnosis.json` — Zero-group-delay proof and raw STFT lag audit.
- `work/W06/evaluate_dev.py` & `work/W06/RESULTS.json` — Full Dev evaluation suite and structured results (`N = 78 H1`, `N = 30 H0`).
- `work/W06/generate_plots.py` & `work/W06/plots/*.png` — Publication-grade visualization suite (4 PNGs).
- `work/W06/PLAN.md`, `work/W06/README.md`, `work/W06/FINDINGS.md`, `work/W06/FAILURES.md`, `work/W06/HANDOFF.md`, `work/W06/progress.md` — Full documentation deliverables.
