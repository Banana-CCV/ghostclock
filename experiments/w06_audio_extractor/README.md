> **Release note.** Study by Gemini worker W06. **Not independently re-verified**, except the director's single-clip reproduction ([director_W06_smoke.md](../../reviews/director_W06_smoke.md)). Paths written `<WORKSPACE>` refer to the original pre-test workspace. Scratch audio (AWGN/codec WAV/MP3) and caches are excluded.

# GhostClock Worker W06: Audio ENF Extractor A (STFT Multi-Harmonic Family)

## Overview
Worker **W06** implements **Approach A (STFT Family)** for extracting Electrical Network Frequency (ENF) traces $f(t)$ and per-window quality scores $q(t) \in [0, 1]$ from audio/video media files, alongside a distinct **ENF-Presence Detector** ($H_1$: mains grid hum present vs. $H_0$: no grid hum present).

All interfaces strictly conform to `integration/interfaces.md` (§1 & §4) and `eval/protocol.md` (§3.2):
- **Zero metadata leakage**: `analyse_audio()` decodes raw audio samples via `ffmpeg` and hashes raw file bytes (`SHA-256`). It never reads file modification times (`mtime`), EXIF creation timestamps, or filename strings.
- **Fundamental-equivalent output**: Regardless of which harmonics ($50, 100, 150, 200, 250, 300\text{ Hz}$ for $50\text{ Hz}$ nominal; or $60\text{-Hz}$ family) carry the signal, the output trace `f` is always mapped to fundamental-equivalent frequency ($\approx 50.0\text{ Hz}$ or $\approx 60.0\text{ Hz}$), and `t` always reports window centers in seconds from media start (`t[0] = window_s / 2`).

---

## Architecture & DSP Pipeline (`work/W06/audio_enf.py`)

1. **Universal FFmpeg Decoding (`decode_audio_ffmpeg`)**:
   - Decodes any container format (`.wav`, `.mp3`, `.m4a`, `.aac`, `.mp4`, `.flac`, `.ogg`) via `ffmpeg -nostdin -v error -i <path> -vn -ac 1 -f f32le -acodec pcm_f32le pipe:1` to mono `float64`.
2. **Anti-Aliased Downsampling (`downsample_antialias`)**:
   - Decimates to `fs_proc = 1000.0 Hz` using polyphase FIR resampling (`scipy.signal.resample_poly`) with a Kaiser-windowed anti-alias filter ($\beta = 8.0$, $>80\text{ dB}$ stopband attenuation).
3. **Zero-Phase Harmonic Band-Pass Filtering (`bandpass_harmonic`)**:
   - Filters each candidate harmonic $h \in \{1, 2, 3, 4, 5, 6\}$ ($50, 100, 150, 200, 250, 300\text{ Hz}$ for $50\text{ Hz}$ grids; $60, 120, 180, 240, 300, 360\text{ Hz}$ for $60\text{ Hz}$ grids) with a 4th-order zero-phase forward-backward Butterworth band-pass filter (`scipy.signal.sosfiltfilt`, exact $0.000\text{ s}$ group delay) with passband $h \cdot f_{\text{nom}} \pm 0.30 h\text{ Hz}$.
4. **Long-Window Zero-Padded STFT & Sub-Bin Peak Interpolation (`subbin_interpolate`)**:
   - Applies a $16.0\text{ s}$ Hann window with $1.0\text{ s}$ hop (`NFFT = 32768`) and performs 3-point Gaussian (quadratic log-magnitude) sub-bin peak interpolation inside $[h(f_{\text{nom}} - 0.12),\, h(f_{\text{nom}} + 0.12)]\text{ Hz}$ to obtain per-harmonic fundamental-equivalent trajectories $\hat{f}_h(t) = \tilde{f}_h(t) / h$.
5. **Unbiased Flanking-Bin Narrowband SNR & Robust Multi-Harmonic Fusion (`snr_robust_hybrid`)**:
   - Measures local narrowband SNR $\text{SNR}_h(t)$ (in dB) by comparing peak mainlobe energy against the robust median noise floor in flanking frequency bins ($[h f_{\text{nom}} \pm 0.25\text{–}2.50\text{ Hz}]$) of the un-bandpassed STFT (preventing filter-rolloff SNR inflation).
   - Combines local SNR weights (`snr_floor_db = 3.5`, exponent `1.5`), microphone $50\text{ Hz}$ attenuation prior (`prior(h=1) = 0.25`), temporal slow-variation smoothness, and inter-harmonic pairwise correlation/proximity consensus (inspired by Hua et al., *IEEE TIFS* 2021) with Tukey-style outlier suppression relative to the weighted spectral mode (`WMLE`, Hajj-Ahmad et al., *IEEE SPL* 2013).
6. **Distinct ENF-Presence Detector (`compute_enf_presence`)**:
   - Computes a dedicated clip-level ENF-presence score in $[0, 1]$ (`presence_threshold = 0.48`) from three physical signatures: (i) narrowband SNR excess at harmonics $h \ge 2$, (ii) temporal slow-variation stability (TF ridge variance and frame-to-frame step MAD, Hua et al., *IEEE TIFS* 2021), and (iii) inter-harmonic trajectory coherence.

---

## Exact Run Commands (from Repo Root `<WORKSPACE>`)

### 1. Extract ENF Trace from Any Audio/Video File (CLI)
```powershell
python work/W06/audio_enf.py --in datasets/raw/enf-whu/repo/ENF-WHU-Dataset/H1/003.wav --out work/W06/smoke_traces --nominal 50
```
Outputs:
- `work/W06/smoke_traces/003.trace.npz` (`t`, `f`, `q` as `float64` 1D arrays)
- `work/W06/smoke_traces/003.trace.json` (metadata, harmonic weights, SNR, and `enf_present` flag)

### 2. Python API Usage
```python
from work.W06.audio_enf import analyse_audio

npz_path, json_path = analyse_audio(
    "datasets/raw/enf-whu/repo/ENF-WHU-Dataset/H1/003.wav",
    config={"out_dir": "work/W06/traces", "nominal_hz": 50},
)
```

### 3. Reproduce Full Dev Split Evaluation, Ablations, Codec/Noise Sweeps & Plots
```powershell
python work/W06/evaluate_dev.py
```
Reads `eval/splits/enf_whu_split.json` (78 Dev `H1` + 30 Dev `H0` recordings; holdout is never touched), runs all ablations and robustness experiments, writes `work/W06/RESULTS.json` and `work/W06/lag_diagnosis.json`, and generates all 4 diagnostic figures in `work/W06/plots/`.

### 4. Regenerate Diagnostic Plots Only
```powershell
python work/W06/generate_plots.py
```

### 5. Run Standalone Lag & Zero Group-Delay Verification
```powershell
python work/W06/diagnose_lag.py
```

---

## Frozen Configuration (`work/W06/config_default.json`)
| Parameter | Frozen Value | Justification (Tuned on ENF-WHU Dev Only) |
| :--- | :--- | :--- |
| `nominal_hz` | `50` | GB (NESO/Elexon) and Central China (ENF-WHU) grid nominal frequency ($60\text{ Hz}$ supported via `--nominal 60`). |
| `harmonics` | `[1, 2, 3, 4, 5, 6]` | Covers $50, 100, 150, 200, 250, 300\text{ Hz}$ ($60\text{–}360\text{ Hz}$ for $60\text{ Hz}$). |
| `harmonic_priors["1"]` | `0.25` | Smartphone microphones strongly high-pass attenuate $50\text{ Hz}$ while room rumble sits near $50\text{ Hz}$; $h \in \{2..6\}$ receive prior $0.85\text{–}1.0$. |
| `fs_proc` | `1000.0` | $500\text{ Hz}$ Nyquist comfortably covers up to the 6th/7th harmonic with fast integer decimation from $8000\text{ Hz}$. |
| `window_s` / `hop_s` | `16.0` / `1.0` | Window sweep ($4\text{–}24\text{ s}$) shows $16\text{ s}$ maximizes frequency concentration while tracking grid dynamics ($1\text{ s}$ cadence). |
| `window_type` | `"hann"` | $-32\text{ dB}$ first sidelobe ($-18\text{ dB/oct}$ rolloff) suppresses out-of-band speech/music leakage far better than rectangular windows. |
| `peak_interp` | `"gaussian_log"` | Quadratic fit on $\ln|X[k]|$ achieves $<0.02\text{ mHz}$ bias on tapered windows at `NFFT = 32768`. |
| `combination_mode` | `"snr_robust_hybrid"` | Combines local flanking-bin SNR, temporal smoothness, and inter-harmonic consensus to reject corrupted harmonics. |
| `presence_threshold` | `0.48` | Youden-optimal threshold on Dev `H1` vs. Dev `H0` composite presence score. |

## Dependencies
Uses the shared Python 3.12 virtual environment (`numpy`, `scipy`, `soundfile`, `matplotlib`) and `ffmpeg` / `ffprobe` on `PATH`. No additional packages were installed.
