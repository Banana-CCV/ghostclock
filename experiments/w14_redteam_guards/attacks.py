#!/usr/bin/env python3
"""
GhostClock Worker W14: Adversarial Attack Generator (`work/W14/attacks.py`)
===========================================================================
Implements all 7 adversarial attack families (a)-(g) on both authentic ENF-WHU
`dev` recordings and labelled `[SYNTHETIC-NESO]` GB grid recordings generated
from real NESO 1-second historical frequency data:

  (a) ENF Removal: Cascaded narrowband IIR notch filters at harmonics (50 Hz only,
      50/100/150 Hz, all harmonics 50..350 Hz at Q=35 and Q=15).
  (b) ENF Injection (Spoofing): Continuous-phase FM sinusoids synthesized from a
      different date's reference trace (NESO Day B 2026-09-01 or ENF-WHU alternate
      day reference), injected into H0 (no-ENF) and H1 (authentic ENF) clips across
      multiple SNRs, single- vs multi-harmonic profiles, and a white-box room-convolved
      multi-harmonic spoof (`b4_whitebox_multi_rir`).
  (c) Double ENF (Two Concurrent Traces): Simultaneous presence of two real grid
      traces mixed across all harmonics (0 dB and +3 dB) or split across odd vs
      even harmonics (`c3_harmonic_split_odd_even`).
  (d) Re-encoding Chains, Noise Suppression & Pitch/Time Transforms:
      - d1: FFmpeg AAC 32 kbps
      - d2: FFmpeg VoIP codec 20 kbps / WhatsApp voice-note profile
      - d3: FFmpeg MP3 64 kbps
      - d4: Heavy stationary spectral gating (phone noise suppression simulation)
      - d5: Resampling chain (8000 -> 11025 -> 8000 Hz) & +0.2% (2000 ppm) clock drift
      - d6: Time-stretch without pitch change (`ffmpeg -af atempo=1.05` and `1.25`)
      - d7: Pitch shift without duration change (+0.5% and +2.0%)
  (e) Cropping to Short Durations: D in {10, 20, 30, 60, 120, 300} s searched
      against a full 24-hour (86,400 s) reference.
  (f) Concatenating Clips from Different Times (Splicing):
      - f1: 50/50 butt-splice (180s Clip A + 180s Clip B)
      - f2: 70/30 asymmetric splice (210s Clip A + 90s Clip B)
      - f3a: Middle overdub replacement (120s Clip A + 60s Clip B + 120s Clip A continuation)
      - f3b: Middle insertion shift (120s Clip A + 60s Clip B + 120s Clip A shifted)
  (g) Metadata Spoofing: Forged container creation_time, RIFF INFO ICRD chunk,
      spoofed filename, and mismatched `claimed_start_utc`.

CLI usage from repo root:
    python work/W14/attacks.py --demo-out work/W14/demo_attacks
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import soundfile as sf
from scipy import fft as sp_fft
from scipy import signal

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_SEED = 20261108


def compute_sha256_bytes(arr: np.ndarray) -> str:
    """Compute deterministic SHA-256 hex digest of a contiguous numpy array."""
    c = np.ascontiguousarray(arr)
    return hashlib.sha256(c.tobytes()).hexdigest()


def measure_harmonic_band_powers(
    audio: np.ndarray,
    fs: float,
    nominal_hz: float = 50.0,
    harmonics: Sequence[int] = (1, 2, 3, 4, 5, 6, 7),
) -> Dict[int, Dict[str, float]]:
    """
    Measure narrowband signal power in [h*f0 - 0.25, h*f0 + 0.25] Hz and flanking
    background noise power per Hz in [h*f0 - 3.0, h*f0 - 0.5] U [h*f0 + 0.5, h*f0 + 3.0] Hz.
    """
    x = np.asarray(audio, dtype=np.float64) - np.mean(audio)
    nperseg = min(len(x), int(round(8.0 * fs)))
    nfft = max(32768, int(2 ** math.ceil(math.log2(max(16, nperseg * 4)))))
    freqs, psd = signal.welch(
        x,
        fs=fs,
        window="hann",
        nperseg=nperseg,
        noverlap=nperseg // 2,
        nfft=nfft,
        scaling="spectrum",
    )
    out: Dict[int, Dict[str, float]] = {}
    for h in harmonics:
        fc = h * nominal_hz
        if fc >= 0.48 * fs:
            continue
        sig_mask = (freqs >= fc - 0.25) & (freqs <= fc + 0.25)
        flank_mask = (
            ((freqs >= fc - 3.0) & (freqs <= fc - 0.5))
            | ((freqs >= fc + 0.5) & (freqs <= fc + 3.0))
        )
        p_sig_peak = float(np.max(psd[sig_mask])) if np.any(sig_mask) else 1e-20
        p_sig_sum = float(np.sum(psd[sig_mask])) if np.any(sig_mask) else 1e-20
        p_flank_med = (
            float(np.median(psd[flank_mask]) / math.log(2.0))
            if np.any(flank_mask)
            else 1e-20
        )
        snr_db = 10.0 * math.log10(max(p_sig_peak / max(p_flank_med, 1e-20), 1e-6))
        out[int(h)] = {
            "peak_power": p_sig_peak,
            "band_power": p_sig_sum,
            "flank_bin_power": p_flank_med,
            "snr_db": snr_db,
        }
    return out


def synthesize_enf_hum_waveform(
    f_trace: np.ndarray,
    t_trace: Optional[np.ndarray],
    fs: float,
    duration_s: float,
    harmonic_weights: Dict[int, float],
    nominal_hz: float = 50.0,
    amp_mod_cv: float = 0.0,
    indep_harmonic_fading: bool = False,
    phase_jitter_std_rad: float = 0.0,
    seed: int = DEFAULT_SEED,
) -> np.ndarray:
    """
    Synthesize a continuous-phase Frequency-Modulated (FM) multi-harmonic ENF hum
    waveform following fundamental-equivalent trajectory `f_trace` (~50.0 Hz).

    Parameters
    ----------
    f_trace : np.ndarray
        Fundamental-equivalent grid frequency sequence in Hz (~50.0 Hz).
    t_trace : np.ndarray, optional
        Timestamps (seconds) corresponding to `f_trace` samples. Defaults to 1.0s steps.
    fs : float
        Output audio sample rate in Hz.
    duration_s : float
        Output waveform duration in seconds.
    harmonic_weights : dict[int, float]
        Relative linear amplitude weights per harmonic number h.
    amp_mod_cv : float
        Coefficient of variation of slow Ornstein-Uhlenbeck amplitude modulation
        (0.0 for clean naive spoof; ~0.22 for white-box room-convolved spoof).
    indep_harmonic_fading : bool
        If True, applies independent room-like slow standing-wave envelope variations
        per harmonic (white-box physical limit model).
    phase_jitter_std_rad : float
        Random-walk phase jitter standard deviation per √second (rad).
    """
    rng = np.random.default_rng(seed)
    n_samples = int(round(duration_s * fs))
    t_audio = np.arange(n_samples, dtype=np.float64) / fs

    f_clean = np.asarray(f_trace, dtype=np.float64).ravel()
    valid = np.isfinite(f_clean)
    if not np.any(valid):
        f_clean = np.full(max(2, int(duration_s)), nominal_hz, dtype=np.float64)
    elif not np.all(valid):
        idx = np.arange(len(f_clean))
        f_clean = np.interp(idx, idx[valid], f_clean[valid])

    if t_trace is None:
        t_ref = np.arange(len(f_clean), dtype=np.float64)
    else:
        t_ref = np.asarray(t_trace, dtype=np.float64).ravel()

    # Interpolate fundamental frequency smoothly onto audio sample grid
    f_inst = np.interp(t_audio, t_ref, f_clean, left=f_clean[0], right=f_clean[-1])

    # Integrate instantaneous fundamental phase: phi_1(t) = 2*pi * \int f_inst(tau) dtau
    dphi = 2.0 * math.pi * f_inst / fs
    if phase_jitter_std_rad > 0.0:
        dphi += rng.normal(0.0, phase_jitter_std_rad / math.sqrt(fs), size=n_samples)
    phi_1 = np.cumsum(dphi)

    # Helper to generate smooth low-pass room envelope with target CV
    def _make_envelope(cv: float) -> np.ndarray:
        if cv <= 1e-6:
            return np.ones(n_samples, dtype=np.float64)
        # Generate white noise at 20 Hz and low-pass filter at 0.15 Hz (~7s room movement scale)
        fs_env = 20.0
        n_env = max(16, int(math.ceil(duration_s * fs_env)) + 4)
        raw_env = rng.standard_normal(n_env)
        sos_lp = signal.butter(2, 0.15 / (0.5 * fs_env), btype="low", output="sos")
        smooth = signal.sosfiltfilt(sos_lp, raw_env)
        smooth = (smooth - np.mean(smooth)) / (np.std(smooth) + 1e-12)
        t_env = np.arange(n_env, dtype=np.float64) / fs_env
        env_interp = np.interp(t_audio, t_env, smooth)
        env = np.clip(1.0 + cv * env_interp, 0.15, 2.5)
        return env / np.sqrt(np.mean(env ** 2))

    global_env = _make_envelope(amp_mod_cv)
    hum = np.zeros(n_samples, dtype=np.float64)

    for h, amp in sorted(harmonic_weights.items()):
        if amp <= 0.0 or (h * nominal_hz) >= 0.48 * fs:
            continue
        phi_0 = float(rng.uniform(0.0, 2.0 * math.pi))
        if indep_harmonic_fading and amp_mod_cv > 0.0:
            h_env = _make_envelope(amp_mod_cv * 0.85) * (0.5 + 0.5 * global_env)
            h_env = h_env / np.sqrt(np.mean(h_env ** 2))
        else:
            h_env = global_env
        hum += float(amp) * h_env * np.cos(float(h) * phi_1 + phi_0)

    rms = float(np.sqrt(np.mean(hum ** 2)))
    if rms > 1e-18:
        hum = hum / rms
    return hum


def generate_synthetic_neso_clip(
    neso_f_hz: np.ndarray,
    start_idx: int,
    duration_s: float = 300.0,
    fs: float = 8000.0,
    snr_db: float = -12.0,
    background_audio: Optional[np.ndarray] = None,
    seed: int = DEFAULT_SEED,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """
    Create a labelled `[SYNTHETIC-NESO]` audio clip whose ENF follows a real GB
    NESO 1-second grid frequency trace (`neso_f_hz[start_idx : start_idx + duration_s]`)
    embedded in realistic pink/room ambient background (or an H0 non-ENF recording)
    with natural multi-harmonic weights and room amplitude variation.
    """
    rng = np.random.default_rng(seed + start_idx)
    n_samples = int(round(duration_s * fs))
    n_sec = int(round(duration_s))
    f_slice = np.asarray(neso_f_hz[start_idx : start_idx + n_sec + 2], dtype=np.float64)
    t_slice = np.arange(len(f_slice), dtype=np.float64)

    # Realistic multi-harmonic weights with room envelope modulation
    harm_weights = {1: 0.25, 2: 1.00, 3: 0.55, 4: 0.35, 5: 0.20, 6: 0.12}
    hum_unit = synthesize_enf_hum_waveform(
        f_trace=f_slice,
        t_trace=t_slice,
        fs=fs,
        duration_s=duration_s,
        harmonic_weights=harm_weights,
        nominal_hz=50.0,
        amp_mod_cv=0.22,
        indep_harmonic_fading=True,
        phase_jitter_std_rad=0.008,
        seed=seed + start_idx,
    )

    if background_audio is not None and len(background_audio) >= n_samples:
        bg = np.asarray(background_audio[:n_samples], dtype=np.float64).copy()
        bg = bg - np.mean(bg)
    else:
        # Synthesize ambient room noise (pink-like 1/f roll-off + speech-band bursts)
        white = rng.standard_normal(n_samples)
        sos_pink = signal.butter(2, [65.0 / (0.5 * fs), 3400.0 / (0.5 * fs)], btype="bandpass", output="sos")
        bg = signal.sosfiltfilt(sos_pink, white) + 0.18 * white

    bg_rms = float(np.sqrt(np.mean(bg ** 2))) + 1e-12
    bg = bg / bg_rms * 0.08  # normalize background RMS to -22 dBFS
    bg_rms = float(np.sqrt(np.mean(bg ** 2)))

    target_hum_rms = bg_rms * (10.0 ** (snr_db / 20.0))
    mixed = bg + target_hum_rms * hum_unit
    peak = float(np.max(np.abs(mixed)))
    if peak > 0.98:
        mixed = mixed * (0.98 / peak)

    meta = {
        "synthetic_neso": True,
        "label": "[SYNTHETIC-NESO]",
        "start_idx_s": int(start_idx),
        "duration_s": float(duration_s),
        "fs_hz": float(fs),
        "wideband_hum_snr_db": float(snr_db),
        "harmonic_weights": harm_weights,
        "seed": int(seed + start_idx),
    }
    return mixed, meta


# =============================================================================
# Attack (a): ENF Removal via Narrowband Notch Filters at Harmonics
# =============================================================================
def attack_a_notch_removal(
    audio: np.ndarray,
    fs: float,
    harmonics_to_notch: Sequence[int] = (1, 2, 3, 4, 5, 6, 7),
    nominal_hz: float = 50.0,
    q_factor: float = 35.0,
    n_stages: int = 2,
) -> np.ndarray:
    """
    Attack (a): Remove ENF by applying a zero-phase cascade of narrowband IIR
    notch filters (`scipy.signal.iirnotch`) at specified harmonics of `nominal_hz`.
    """
    y = np.asarray(audio, dtype=np.float64).copy()
    for h in harmonics_to_notch:
        f0 = float(h) * nominal_hz
        if f0 >= 0.48 * fs:
            continue
        b, a = signal.iirnotch(w0=f0, Q=q_factor, fs=fs)
        sos = signal.tf2sos(b, a)
        for _ in range(max(1, n_stages)):
            y = signal.sosfiltfilt(sos, y)
    return y


# =============================================================================
# Attack (b): ENF Injection (Spoofing with a Wrong Date's Reference Trace)
# =============================================================================
def attack_b_enf_injection(
    audio: np.ndarray,
    fs: float,
    spoof_f_trace: np.ndarray,
    spoof_t_trace: Optional[np.ndarray] = None,
    mode: str = "single_100hz_clean",
    snr_db: float = 5.0,
    snr_reference: str = "native_hum",
    nominal_hz: float = 50.0,
    pre_notch_native: bool = False,
    seed: int = DEFAULT_SEED,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """
    Attack (b): Inject a synthetic ENF hum trace following a wrong date's grid
    reference (`spoof_f_trace`) into `audio` (which may be H0 without ENF or H1 with ENF).

    Modes:
      - "single_100hz_clean": Pure 100 Hz (h=2) constant-amplitude FM sinusoid.
      - "dual_50_100_clean": Constant-amplitude h=1,2 FM sinusoids.
      - "multi_h1_h4_clean": Constant-amplitude h=1..4 FM sinusoids (`{1:0.5, 2:1.0, 3:0.6, 4:0.4}`).
      - "whitebox_multi_rir": White-box physical-limit attack: h=1..6 with 1/h roll-off,
        independent slow room envelope modulation (CV=0.22), and phase micro-jitter.
    """
    x = np.asarray(audio, dtype=np.float64).copy()
    duration_s = float(len(x) / fs)

    if pre_notch_native:
        x = attack_a_notch_removal(x, fs, harmonics_to_notch=(1, 2, 3, 4, 5, 6, 7), nominal_hz=nominal_hz, q_factor=30.0)

    if mode == "single_100hz_clean":
        h_weights = {2: 1.0}
        cv = 0.0
        indep_fading = False
        p_jit = 0.0
    elif mode == "dual_50_100_clean":
        h_weights = {1: 0.45, 2: 1.0}
        cv = 0.0
        indep_fading = False
        p_jit = 0.0
    elif mode == "multi_h1_h4_clean":
        h_weights = {1: 0.45, 2: 1.0, 3: 0.65, 4: 0.40}
        cv = 0.0
        indep_fading = False
        p_jit = 0.0
    elif mode == "whitebox_multi_rir":
        h_weights = {1: 0.30, 2: 1.0, 3: 0.60, 4: 0.38, 5: 0.24, 6: 0.16}
        cv = 0.24
        indep_fading = True
        p_jit = 0.012
    else:
        raise ValueError(f"Unknown injection mode: {mode}")

    hum_unit = synthesize_enf_hum_waveform(
        f_trace=spoof_f_trace,
        t_trace=spoof_t_trace,
        fs=fs,
        duration_s=duration_s,
        harmonic_weights=h_weights,
        nominal_hz=nominal_hz,
        amp_mod_cv=cv,
        indep_harmonic_fading=indep_fading,
        phase_jitter_std_rad=p_jit,
        seed=seed,
    )

    band_info = measure_harmonic_band_powers(x, fs, nominal_hz=nominal_hz)
    if snr_reference == "native_hum":
        # Calibrate relative to the existing narrowband hum power across h=2..6
        sig_powers = [v["band_power"] for h, v in band_info.items() if h >= 2]
        ref_power = max(sum(sig_powers), 1e-12)
        ref_rms = math.sqrt(ref_power)
    elif snr_reference == "flanking_noise":
        # Calibrate relative to local flanking background noise in +/- 2.5 Hz around 100 Hz
        flank_bin = band_info.get(2, {}).get("flank_bin_power", 1e-10)
        ref_rms = math.sqrt(max(flank_bin * 10.0, 1e-12))
    else:
        # Wideband RMS
        ref_rms = float(np.sqrt(np.mean(x ** 2))) + 1e-12

    inject_rms = ref_rms * (10.0 ** (snr_db / 20.0))
    y = x + inject_rms * hum_unit
    peak = float(np.max(np.abs(y)))
    if peak > 0.99:
        y = y * (0.99 / peak)

    info = {
        "attack": "b_enf_injection",
        "mode": mode,
        "snr_db": float(snr_db),
        "snr_reference": snr_reference,
        "pre_notch_native": bool(pre_notch_native),
        "inject_rms": float(inject_rms),
        "ref_rms": float(ref_rms),
    }
    return y, info


# =============================================================================
# Attack (c): Double ENF (Two Concurrent Grid Traces)
# =============================================================================
def attack_c_double_enf(
    audio_h1: np.ndarray,
    fs: float,
    second_f_trace: np.ndarray,
    second_t_trace: Optional[np.ndarray] = None,
    mode: str = "all_harmonics_0db",
    rel_snr_db: float = 0.0,
    nominal_hz: float = 50.0,
    seed: int = DEFAULT_SEED,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """
    Attack (c): Create a recording containing two simultaneous real grid traces:
      - "all_harmonics": Second real trace injected across h=1..6 with realistic room
        envelope modulation at `rel_snr_db` (e.g. 0 dB or +3 dB) relative to native hum.
      - "harmonic_split_odd_even": Native ENF preserved on even harmonics (h=2,4,6;
        odd harmonics h=1,3,5 notched out), while the second grid trace is injected
        on odd harmonics (h=1,3,5) at `rel_snr_db`.
    """
    x = np.asarray(audio_h1, dtype=np.float64).copy()
    duration_s = float(len(x) / fs)
    band_info = measure_harmonic_band_powers(x, fs, nominal_hz=nominal_hz)
    native_power = sum(v["band_power"] for h, v in band_info.items() if h >= 2)
    native_rms = math.sqrt(max(native_power, 1e-12))

    if mode == "harmonic_split_odd_even":
        # Notch odd harmonics (1, 3, 5, 7) from the original recording so native trace lives on even h=2,4,6
        x = attack_a_notch_removal(x, fs, harmonics_to_notch=(1, 3, 5, 7), nominal_hz=nominal_hz, q_factor=30.0)
        h_weights = {1: 0.40, 3: 1.00, 5: 0.65, 7: 0.35}
    else:
        h_weights = {1: 0.25, 2: 1.00, 3: 0.60, 4: 0.40, 5: 0.25, 6: 0.15}

    hum2 = synthesize_enf_hum_waveform(
        f_trace=second_f_trace,
        t_trace=second_t_trace,
        fs=fs,
        duration_s=duration_s,
        harmonic_weights=h_weights,
        nominal_hz=nominal_hz,
        amp_mod_cv=0.18,
        indep_harmonic_fading=True,
        phase_jitter_std_rad=0.006,
        seed=seed,
    )
    inject_rms = native_rms * (10.0 ** (rel_snr_db / 20.0))
    y = x + inject_rms * hum2
    peak = float(np.max(np.abs(y)))
    if peak > 0.99:
        y = y * (0.99 / peak)

    return y, {
        "attack": "c_double_enf",
        "mode": mode,
        "rel_snr_db": float(rel_snr_db),
        "native_rms": float(native_rms),
        "inject_rms": float(inject_rms),
    }


# =============================================================================
# Attack (d): Re-encoding Chains, Spectral Gating, Resampling, Time-Stretch & Pitch Shift
# =============================================================================
def _ffmpeg_roundtrip(
    audio: np.ndarray,
    fs: float,
    encode_args: List[str],
    ext: str,
    decode_fs: Optional[float] = None,
) -> Tuple[np.ndarray, float]:
    """Write `audio` to temp WAV, encode via FFmpeg with `encode_args`, and decode back to float64."""
    target_fs = float(decode_fs if decode_fs is not None else fs)
    with tempfile.TemporaryDirectory(prefix="w14_ffmpeg_") as tmpdir:
        tmp_in = Path(tmpdir) / "in.wav"
        tmp_enc = Path(tmpdir) / f"encoded{ext}"
        tmp_out = Path(tmpdir) / "out.wav"
        sf.write(str(tmp_in), np.asarray(audio, dtype=np.float32), int(round(fs)), subtype="FLOAT")

        cmd_enc = ["ffmpeg", "-y", "-nostdin", "-v", "error", "-i", str(tmp_in)] + encode_args + [str(tmp_enc)]
        subprocess.run(cmd_enc, check=True, capture_output=True)

        cmd_dec = [
            "ffmpeg",
            "-y",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(tmp_enc),
            "-ac",
            "1",
            "-ar",
            str(int(round(target_fs))),
            "-c:a",
            "pcm_f32le",
            str(tmp_out),
        ]
        subprocess.run(cmd_dec, check=True, capture_output=True)
        y, fs_out = sf.read(str(tmp_out), dtype="float64")
        return y, float(fs_out)


def attack_d_spectral_gating_denoise(
    audio: np.ndarray,
    fs: float,
    gate_atten_db: float = 28.0,
    thresh_mult: float = 2.8,
) -> np.ndarray:
    """
    Attack (d4): Simulate heavy smartphone stationary noise suppression via STFT
    minimum-statistics / quantile stationary noise estimation and soft-knee spectral gating.
    Stationary narrowband hum tones (constant across time) are identified as part of
    the stationary noise profile and heavily gated between speech bursts.
    """
    x = np.asarray(audio, dtype=np.float64)
    nperseg = int(round(0.25 * fs))  # 250 ms window (4 Hz bin width, standard voice denoiser scale)
    noverlap = int(round(0.1875 * fs))
    freqs, t_frames, Zxx = signal.stft(x, fs=fs, window="hann", nperseg=nperseg, noverlap=noverlap)
    mag = np.abs(Zxx)

    # Stationary noise floor per frequency bin estimated from the 35th percentile across time
    # (captures continuous stationary hum + room hiss while ignoring transient speech bursts)
    noise_profile = np.percentile(mag, 35, axis=1, keepdims=True) + 1e-12
    snr_bin = mag / noise_profile

    # Heavy spectral gate: bins below thresh_mult * noise_profile are attenuated by gate_atten_db
    min_gain = 10.0 ** (-gate_atten_db / 20.0)
    gain = np.where(
        snr_bin < thresh_mult,
        min_gain + (1.0 - min_gain) * ((snr_bin / thresh_mult) ** 4),
        1.0,
    )
    # Extra stationary tone suppression in low frequencies (< 400 Hz) where voice fundamental is absent
    low_freq_mask = (freqs < 380.0)[:, None]
    stationary_ratio = np.median(mag, axis=1, keepdims=True) / ( np.percentile(mag, 90, axis=1, keepdims=True) + 1e-12 )
    is_stationary_tone = (stationary_ratio > 0.45) & low_freq_mask
    gain = np.where(is_stationary_tone & (snr_bin < thresh_mult * 1.8), min_gain * 0.25, gain)

    Z_gated = Zxx * gain
    _, y_rec = signal.istft(Z_gated, fs=fs, window="hann", nperseg=nperseg, noverlap=noverlap)
    if len(y_rec) >= len(x):
        return y_rec[: len(x)].astype(np.float64)
    return np.pad(y_rec, (0, len(x) - len(y_rec))).astype(np.float64)


def attack_d_transform(
    audio: np.ndarray,
    fs: float,
    variant: str,
) -> Tuple[np.ndarray, float, Dict[str, Any]]:
    """
    Execute a specific Attack (d) variant:
      - "d1_aac_32k": AAC 32 kbps re-encode
      - "d2_voip_codec_20k": VoIP codec 20 kbps (WhatsApp voice-note simulation)
      - "d3_mp3_64k": MP3 64 kbps re-encode
      - "d4_spectral_gating": Heavy stationary spectral gating noise suppression
      - "d5a_resample_8k_11k_8k": Asynchronous resampling chain 8000 -> 11025 -> 8000 Hz
      - "d5b_clock_drift_2000ppm": +0.2% (+2000 ppm) sample-clock speed drift
      - "d6a_timestretch_atempo_105": FFmpeg WSOLA time-stretch +5% (`atempo=1.05`) without pitch change
      - "d6b_timestretch_atempo_125": FFmpeg WSOLA time-stretch +25% (`atempo=1.25`) without pitch change
      - "d7a_pitch_shift_p05pct": Pitch shift +0.5% without duration change (50.0 -> 50.25 Hz)
      - "d7b_pitch_shift_p20pct": Pitch shift +2.0% without duration change (50.0 -> 51.00 Hz)
    """
    x = np.asarray(audio, dtype=np.float64)
    if variant == "d1_aac_32k":
        y, fs_out = _ffmpeg_roundtrip(x, fs, ["-c:a", "aac", "-b:a", "32k"], ".m4a")
    elif variant == "d2_voip_codec_20k":
        y, fs_out = _ffmpeg_roundtrip(
            x, fs, ["-c:a", "libopus", "-b:a", "20k", "-application", "voip", "-ar", "16000"], ".ogg", decode_fs=fs
        )
    elif variant == "d3_mp3_64k":
        y, fs_out = _ffmpeg_roundtrip(x, fs, ["-c:a", "libmp3lame", "-b:a", "64k"], ".mp3")
    elif variant == "d4_spectral_gating":
        y = attack_d_spectral_gating_denoise(x, fs, gate_atten_db=28.0, thresh_mult=2.8)
        fs_out = fs
    elif variant == "d5a_resample_8k_11k_8k":
        # 8000 -> 11025 -> 8000 Hz via polyphase FIR
        g1 = math.gcd(int(fs), 11025)
        y_mid = signal.resample_poly(x, 11025 // g1, int(fs) // g1)
        y = signal.resample_poly(y_mid, int(fs) // g1, 11025 // g1)
        y = y[: len(x)]
        fs_out = fs
    elif variant == "d5b_clock_drift_2000ppm":
        # +0.2% sample-clock drift (playback speed 1.002x: shifts both frequency by +0.2% -> +100 mHz at 50 Hz
        # and compresses timeline by 0.2% -> 1.2s lag drift over 600s)
        alpha = 1.002
        t_in = np.arange(len(x), dtype=np.float64)
        t_out = np.arange(0.0, len(x) - 1, alpha, dtype=np.float64)
        y = np.interp(t_out, t_in, x)
        fs_out = fs
    elif variant == "d6a_timestretch_atempo_105":
        y, fs_out = _ffmpeg_roundtrip(x, fs, ["-af", "atempo=1.05", "-c:a", "pcm_f32le"], ".wav")
    elif variant == "d6b_timestretch_atempo_125":
        y, fs_out = _ffmpeg_roundtrip(x, fs, ["-af", "atempo=1.25", "-c:a", "pcm_f32le"], ".wav")
    elif variant == "d7a_pitch_shift_p05pct":
        # Shift pitch by +0.5% (k=1.005) while compensating tempo by 1/1.005 so duration is unchanged
        k = 1.005
        af_str = f"asetrate={int(round(fs * k))},aresample={int(round(fs))},atempo={1.0/k:.6f}"
        y, fs_out = _ffmpeg_roundtrip(x, fs, ["-af", af_str, "-c:a", "pcm_f32le"], ".wav")
    elif variant == "d7b_pitch_shift_p20pct":
        k = 1.020
        af_str = f"asetrate={int(round(fs * k))},aresample={int(round(fs))},atempo={1.0/k:.6f}"
        y, fs_out = _ffmpeg_roundtrip(x, fs, ["-af", af_str, "-c:a", "pcm_f32le"], ".wav")
    else:
        raise ValueError(f"Unsupported Attack (d) variant: {variant}")

    return y, fs_out, {"attack": "d_transform", "variant": variant, "len_in": len(x), "len_out": len(y)}


# =============================================================================
# Attack (e): Cropping to Short Durations
# =============================================================================
def attack_e_crop_duration(
    audio: np.ndarray,
    fs: float,
    crop_duration_s: float,
    offset_s: float = 0.0,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Attack (e): Crop recording to `crop_duration_s` starting at `offset_s`."""
    start_idx = max(0, int(round(offset_s * fs)))
    n_crop = max(1, int(round(crop_duration_s * fs)))
    y = np.asarray(audio[start_idx : start_idx + n_crop], dtype=np.float64).copy()
    return y, {
        "attack": "e_crop_duration",
        "crop_duration_s": float(len(y) / fs),
        "offset_s": float(offset_s),
    }


# =============================================================================
# Attack (f): Concatenating Clips from Different Times (Splicing)
# =============================================================================
def attack_f_splice_concat(
    audio_a: np.ndarray,
    audio_b: np.ndarray,
    fs: float,
    mode: str = "f1_splice_50_50",
    crossfade_ms: float = 10.0,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """
    Attack (f): Concatenate or splice segments from two different recording times
    (`audio_a` at true timestamp t_A and `audio_b` at different timestamp t_B):
      - "f1_splice_50_50": 180s of A + 180s of B (total 360s)
      - "f2_splice_70_30": 210s of A + 90s of B (total 300s)
      - "f3a_insertion_overdub_120_60_120": 0..120s of A + 0..60s of B + 180..300s of A (total 300s;
        outer segments remain synchronous with t_A while middle 60s is replaced!)
      - "f3b_insertion_shift_120_60_120": 0..120s of A + 0..60s of B + 120..240s of A (total 300s;
        60s of B inserted at t=120s, shifting second part of A by +60s).
    """
    a = np.asarray(audio_a, dtype=np.float64)
    b = np.asarray(audio_b, dtype=np.float64)

    # Match wideband RMS of B to A to avoid trivial loudness jumps
    rms_a = float(np.sqrt(np.mean(a ** 2))) + 1e-12
    rms_b = float(np.sqrt(np.mean(b ** 2))) + 1e-12
    b = b * (rms_a / rms_b)

    def _join_with_xfade(seg1: np.ndarray, seg2: np.ndarray) -> np.ndarray:
        n_xf = int(round((crossfade_ms / 1000.0) * fs))
        if n_xf <= 1 or len(seg1) <= n_xf or len(seg2) <= n_xf:
            return np.concatenate([seg1, seg2])
        w_out = np.linspace(1.0, 0.0, n_xf)
        w_in = np.linspace(0.0, 1.0, n_xf)
        mid = seg1[-n_xf:] * w_out + seg2[:n_xf] * w_in
        return np.concatenate([seg1[:-n_xf], mid, seg2[n_xf:]])

    if mode == "f1_splice_50_50":
        n180 = min(len(a), len(b), int(round(180.0 * fs)))
        y = _join_with_xfade(a[:n180], b[:n180])
        boundaries_s = [float(n180 / fs)]
    elif mode == "f2_splice_70_30":
        n210 = min(len(a), int(round(210.0 * fs)))
        n90 = min(len(b), int(round(90.0 * fs)))
        y = _join_with_xfade(a[:n210], b[:n90])
        boundaries_s = [float(n210 / fs)]
    elif mode == "f3a_insertion_overdub_120_60_120":
        n120 = int(round(120.0 * fs))
        n60 = int(round(60.0 * fs))
        n180 = int(round(180.0 * fs))
        n300 = min(len(a), int(round(300.0 * fs)))
        seg_a1 = a[:n120]
        seg_b = b[:n60]
        seg_a2 = a[n180:n300]
        y = _join_with_xfade(_join_with_xfade(seg_a1, seg_b), seg_a2)
        boundaries_s = [120.0, 180.0]
    elif mode == "f3b_insertion_shift_120_60_120":
        n120 = int(round(120.0 * fs))
        n60 = int(round(60.0 * fs))
        n240 = min(len(a), int(round(240.0 * fs)))
        seg_a1 = a[:n120]
        seg_b = b[:n60]
        seg_a2 = a[n120:n240]
        y = _join_with_xfade(_join_with_xfade(seg_a1, seg_b), seg_a2)
        boundaries_s = [120.0, 180.0]
    else:
        raise ValueError(f"Unsupported splice mode: {mode}")

    return y, {
        "attack": "f_splice_concat",
        "mode": mode,
        "boundaries_s": boundaries_s,
        "duration_s": float(len(y) / fs),
    }


# =============================================================================
# Attack (g): Metadata, Filename & Container Timestamp Spoofing
# =============================================================================
def attack_g_metadata_spoof_file(
    src_wav_path: Union[str, Path],
    out_dir: Union[str, Path],
    spoof_date_iso: str = "2024-01-01T00:00:00Z",
    spoof_filename: str = "2024-01-01_000000_SPOOFED_CLAIM_EVIDENCE.wav",
) -> Tuple[Path, Dict[str, Any]]:
    """
    Attack (g): Copy the audio stream into a WAV file with forged RIFF INFO metadata
    tags (`creation_time`, `ICRD`, `date`, `title`, `comment`), a deceptive filename
    containing a fake timestamp, and a modified filesystem mtime (`2024-01-01`).
    """
    src_path = Path(src_wav_path)
    out_dir_p = Path(out_dir)
    out_dir_p.mkdir(parents=True, exist_ok=True)
    spoof_path = out_dir_p / spoof_filename

    cmd = [
        "ffmpeg",
        "-y",
        "-nostdin",
        "-v",
        "error",
        "-i",
        str(src_path),
        "-c:a",
        "copy",
        "-metadata",
        f"creation_time={spoof_date_iso}",
        "-metadata",
        f"date={spoof_date_iso[:10]}",
        "-metadata",
        "title=Verified_Claim_2024_01_01_00_00_00_UTC",
        "-metadata",
        "comment=EXIF_Time_2024-01-01T00:00:00Z",
        str(spoof_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)

    # Also spoof OS filesystem modification/access time to 2024-01-01 00:00:00 UTC (epoch 1704067200)
    fake_epoch = 1704067200.0
    os.utime(spoof_path, (fake_epoch, fake_epoch))

    return spoof_path, {
        "attack": "g_metadata_spoof",
        "orig_path": str(src_path),
        "spoof_path": str(spoof_path),
        "spoof_date_iso": spoof_date_iso,
        "spoof_mtime_epoch": int(fake_epoch),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="W14 Adversarial Attack Generator CLI")
    parser.add_argument("--demo-out", type=str, default=None, help="Directory to write demo attacked audio files")
    args = parser.parse_args()
    if args.demo_out:
        out_p = Path(args.demo_out)
        out_p.mkdir(parents=True, exist_ok=True)
        f_sim = 50.0 + 0.03 * np.sin(np.linspace(0, 8 * math.pi, 120))
        clip, meta = generate_synthetic_neso_clip(f_sim, start_idx=0, duration_s=60.0, fs=8000.0, snr_db=-10.0)
        wav_p = out_p / "demo_synthetic_neso.wav"
        sf.write(str(wav_p), clip, 8000)
        print(f"Wrote demo synthetic clip to {wav_p} ({meta})")


if __name__ == "__main__":
    main()
