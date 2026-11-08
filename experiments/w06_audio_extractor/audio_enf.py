#!/usr/bin/env python3
"""
GhostClock Worker W06: Audio ENF Extractor A (STFT Family)
==========================================================
Implements multi-harmonic Short-Time Fourier Transform (STFT) Electrical Network
Frequency (ENF) extraction and ENF-presence detection for audio/video recordings.

Pipeline steps (per integration/interfaces.md):
1. Decode any input media format via FFmpeg to mono float64 PCM without reading
   any wall-clock metadata, creation timestamps, or EXIF tags.
2. Proper anti-alias low-pass filtering (8th-order zero-phase Butterworth +
   polyphase FIR resampling) to downsample to `fs_proc` (default 1000 Hz).
3. Zero-phase narrowband band-pass filtering around each candidate harmonic
   h * f_nominal (h in {1, 2, 3, 4, 5, 6} -> 50, 100, 150, 200, 250, 300 Hz for
   50 Hz grids; 60, 120, 180, 240, 300, 360 Hz for 60 Hz grids).
4. Long-window STFT (default 16 s window, 1 s hop) with Hann/Gaussian tapering,
   high zero-padding (NFFT >= 65536), and sub-bin quadratic log-magnitude
   (Gaussian) / Jacobsen peak interpolation.
5. Per-harmonic, per-window narrowband SNR measurement relative to neighbouring
   flanking bins (measured on the wide-band pre-BPF spectrum to avoid filter-shape
   bias) plus inter-harmonic consensus & temporal smoothness weighting.
6. Weighted multi-harmonic combination (hybrid spectral + trace WMLE) to produce
   fundamental-equivalent f(t) (~50.0 Hz) and calibrated quality score q(t) in [0, 1].
7. Distinct ENF-presence detector combining narrowband harmonic SNR excess,
   temporal slow-variation stability (Hua et al., IEEE TIFS 2021), and
   inter-harmonic trajectory coherence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import soundfile as sf
from scipy import fft as sp_fft
from scipy import signal

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config_default.json"


def load_config(config: Optional[Union[Dict[str, Any], str, Path]] = None) -> Dict[str, Any]:
    """Load default config and merge any user overrides."""
    with open(DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    if config is None:
        return cfg
    if isinstance(config, (str, Path)):
        with open(Path(config), "r", encoding="utf-8") as f:
            user_cfg = json.load(f)
        cfg.update(user_cfg)
    elif isinstance(config, dict):
        cfg.update(config)
    else:
        raise TypeError(f"Unsupported config type: {type(config)}")
    return cfg


def compute_sha256(path: Path) -> str:
    """Compute SHA-256 hex digest of raw file bytes without inspecting metadata."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def probe_sample_rate(path: Path) -> float:
    """Probe sample rate of media file via soundfile or ffprobe (never reading timestamps)."""
    try:
        info = sf.info(str(path))
        if info.samplerate and info.samplerate > 0:
            return float(info.samplerate)
    except Exception:
        pass

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=sample_rate",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    val = res.stdout.strip().splitlines()[0].strip()
    return float(val)


def decode_audio_ffmpeg(
    path: Path,
    use_ffmpeg: bool = True,
    target_fs_ffmpeg: Optional[float] = None,
) -> Tuple[np.ndarray, float]:
    """
    Decode any audio/video container to mono float64 waveform via FFmpeg pipe.
    Never reads container timestamps, EXIF, or filename metadata.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Media file not found: {path}")

    fs_media = probe_sample_rate(path)

    if not use_ffmpeg and path.suffix.lower() in {".wav", ".flac", ".ogg"}:
        data, fs = sf.read(str(path), dtype="float64", always_2d=True)
        return np.mean(data, axis=1), float(fs)

    cmd = [
        "ffmpeg",
        "-nostdin",
        "-v",
        "error",
        "-i",
        str(path),
        "-vn",
        "-ac",
        "1",
    ]
    if target_fs_ffmpeg is not None:
        cmd.extend(["-ar", str(int(round(target_fs_ffmpeg)))])
        fs_out = float(int(round(target_fs_ffmpeg)))
    else:
        fs_out = fs_media

    cmd.extend(["-f", "f32le", "-acodec", "pcm_f32le", "pipe:1"])
    proc = subprocess.run(cmd, capture_output=True, check=True)
    audio_f32 = np.frombuffer(proc.stdout, dtype=np.float32)
    audio = audio_f32.astype(np.float64)
    return audio, fs_out


def downsample_antialias(
    audio: np.ndarray,
    fs_in: float,
    fs_target: float,
) -> Tuple[np.ndarray, float]:
    """
    Downsample audio to `fs_target` using polyphase FIR resampling with a
    Kaiser-windowed anti-aliasing filter (beta=8.0, >80 dB stopband attenuation).
    """
    if fs_in <= fs_target or abs(fs_in - fs_target) < 1e-6:
        return audio - np.mean(audio), fs_in

    x = audio - np.mean(audio)
    fs_in_i = int(round(fs_in))
    fs_out_i = int(round(fs_target))
    g = math.gcd(fs_in_i, fs_out_i)
    up = fs_out_i // g
    down = fs_in_i // g

    x_ds = signal.resample_poly(x, up, down, window=("kaiser", 8.0))
    return x_ds.astype(np.float64), float(fs_out_i)


def bandpass_harmonic(
    x: np.ndarray,
    fs: float,
    center_hz: float,
    half_bw_hz: float,
    order: int = 4,
) -> np.ndarray:
    """Zero-phase Butterworth narrowband band-pass filter around `center_hz`."""
    nyq = 0.5 * fs
    low = max(1.0, center_hz - half_bw_hz) / nyq
    high = min(nyq * 0.98, center_hz + half_bw_hz) / nyq
    if low >= high or high >= 1.0:
        return x.copy()
    sos = signal.butter(order, [low, high], btype="bandpass", output="sos")
    padlen = min(len(x) - 1, max(3 * order * 2, int(2.0 * fs)))
    return signal.sosfiltfilt(sos, x, padlen=padlen)


def build_window(win_len: int, window_type: str = "hann") -> np.ndarray:
    """Construct analysis window normalized to unit energy."""
    wtype = window_type.lower()
    if wtype == "hann":
        w = signal.windows.hann(win_len, sym=False)
    elif wtype == "gaussian":
        w = signal.windows.gaussian(win_len, std=0.18 * win_len, sym=False)
    elif wtype in {"rect", "rectangular", "boxcar"}:
        w = np.ones(win_len, dtype=np.float64)
    elif wtype == "hamming":
        w = signal.windows.hamming(win_len, sym=False)
    elif wtype == "blackmanharris":
        w = signal.windows.blackmanharris(win_len, sym=False)
    else:
        w = signal.windows.hann(win_len, sym=False)
    return w.astype(np.float64)


def frame_signal(
    x: np.ndarray,
    win_len: int,
    hop_len: int,
) -> np.ndarray:
    """Return zero-copy strided 2D view of frames (n_frames, win_len)."""
    if len(x) < win_len:
        pad_total = win_len - len(x)
        pad_l = pad_total // 2
        pad_r = pad_total - pad_l
        x = np.pad(x, (pad_l, pad_r), mode="reflect" if len(x) > 1 else "constant")
    n_frames = (len(x) - win_len) // hop_len + 1
    shape = (n_frames, win_len)
    strides = (x.strides[0] * hop_len, x.strides[0])
    return np.lib.stride_tricks.as_strided(x, shape=shape, strides=strides)


def subbin_interpolate(
    spec_complex: np.ndarray,
    spec_mag: np.ndarray,
    peak_idx: np.ndarray,
    mode: str = "gaussian_log",
) -> np.ndarray:
    """
    Vectorized sub-bin peak interpolation across M frames.
    `peak_idx` is 1D integer array of length M (within [1, n_bins - 2]).
    Returns fractional bin offset delta in [-0.5, +0.5].
    """
    m_Range = np.arange(len(peak_idx))
    k_l = np.maximum(0, peak_idx - 1)
    k_c = peak_idx
    k_r = np.minimum(spec_mag.shape[1] - 1, peak_idx + 1)

    if mode == "jacobsen":
        v_l = spec_complex[m_Range, k_l]
        v_c = spec_complex[m_Range, k_c]
        v_r = spec_complex[m_Range, k_r]
        denom = 2.0 * v_c - v_l - v_r
        delta = -np.real((v_r - v_l) / (denom + 1e-18))
    elif mode == "parabolic_mag":
        a = spec_mag[m_Range, k_l]
        b = spec_mag[m_Range, k_c]
        c = spec_mag[m_Range, k_r]
        denom = a - 2.0 * b + c
        delta = np.where(denom < -1e-18, 0.5 * (a - c) / (denom - 1e-18), 0.0)
    else:
        # Default: gaussian_log (quadratic interpolation on log-magnitude spectrum)
        a = np.log(spec_mag[m_Range, k_l] + 1e-18)
        b = np.log(spec_mag[m_Range, k_c] + 1e-18)
        c = np.log(spec_mag[m_Range, k_r] + 1e-18)
        denom = a - 2.0 * b + c
        delta = np.where(denom < -1e-18, 0.5 * (a - c) / (denom - 1e-18), 0.0)

    return np.clip(delta, -0.5, 0.5)


def extract_reference_enf(
    ref_path: Union[str, Path],
    window_s: float = 16.0,
    hop_s: float = 1.0,
    nominal_hz: float = 50.0,
    search_half_bw_hz: float = 0.15,
    window_type: str = "hann",
    nfft_min: int = 16384,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Extract clean fundamental-equivalent reference ENF trace from a power-mains
    reference recording (e.g., ENF-WHU H1_ref at 400 Hz around 50 Hz).
    Evaluated at the exact same window centers `t` as `analyse_audio`.
    """
    ref_sig, fs_ref = sf.read(str(ref_path), dtype="float64", always_2d=True)
    ref_sig = np.mean(ref_sig, axis=1)
    ref_sig = ref_sig - np.mean(ref_sig)

    # Bandpass around nominal fundamental (50 Hz)
    ref_bp = bandpass_harmonic(ref_sig, fs_ref, nominal_hz, half_bw_hz=0.5, order=4)

    win_len = max(16, int(round(window_s * fs_ref)))
    hop_len = max(1, int(round(hop_s * fs_ref)))
    nfft = max(nfft_min, int(2 ** math.ceil(math.log2(win_len * 4))))

    frames = frame_signal(ref_bp, win_len, hop_len)
    win = build_window(win_len, window_type)
    spec = sp_fft.rfft(frames * win[None, :], n=nfft, axis=1, workers=-1)
    freqs = np.fft.rfftfreq(nfft, d=1.0 / fs_ref)

    mask = (freqs >= nominal_hz - search_half_bw_hz) & (freqs <= nominal_hz + search_half_bw_hz)
    idx_band = np.where(mask)[0]
    mag = np.abs(spec)
    peak_local = np.argmax(mag[:, idx_band], axis=1)
    peak_bin = idx_band[0] + peak_local

    delta = subbin_interpolate(spec, mag, peak_bin, mode="gaussian_log")
    f_ref = (peak_bin + delta) * (fs_ref / nfft)
    f_ref = np.clip(f_ref, nominal_hz - search_half_bw_hz, nominal_hz + search_half_bw_hz)

    n_frames = len(f_ref)
    t_ref = np.arange(n_frames, dtype=np.float64) * hop_s + 0.5 * window_s
    return t_ref, f_ref


def extract_audio_enf_detailed(
    path: Union[str, Path],
    config: Optional[Union[Dict[str, Any], str, Path]] = None,
) -> Dict[str, Any]:
    """
    Run full multi-harmonic STFT extraction and ENF-presence detection, returning
    all intermediate arrays for diagnostics, ablation studies, and plotting.
    """
    cfg = load_config(config)
    path = Path(path)
    media_sha256 = compute_sha256(path)

    nominal_hz = float(cfg.get("nominal_hz", 50.0))
    fs_target = float(cfg.get("fs_proc", 1000.0))
    use_ffmpeg = bool(cfg.get("decode_via_ffmpeg", True))

    raw_audio, fs_media = decode_audio_ffmpeg(path, use_ffmpeg=use_ffmpeg)
    duration_s = float(len(raw_audio) / fs_media) if fs_media > 0 else 0.0

    # Downsample with proper anti-alias filter
    x_proc, fs_proc = downsample_antialias(raw_audio, fs_media, fs_target)

    # Candidate harmonics that fit comfortably below Nyquist
    cand_harmonics_cfg = [int(h) for h in cfg.get("harmonics", [1, 2, 3, 4, 5, 6])]
    flank_outer_base = float(cfg.get("flank_outer_hz", 2.50))
    harmonics = [
        h
        for h in cand_harmonics_cfg
        if (h * nominal_hz + max(flank_outer_base, h * 0.5)) < 0.47 * fs_proc
    ]
    if not harmonics:
        harmonics = [1]

    window_s = float(cfg.get("window_s", 16.0))
    hop_s = float(cfg.get("hop_s", 1.0))
    eff_window_s = min(window_s, max(2.0, duration_s))
    win_len = max(16, int(round(eff_window_s * fs_proc)))
    hop_len = max(1, int(round(hop_s * fs_proc)))

    zero_pad_factor = int(cfg.get("zero_pad_factor", 8))
    min_nfft = int(cfg.get("min_nfft", 65536))
    nfft = max(min_nfft, int(2 ** math.ceil(math.log2(win_len * zero_pad_factor))))

    window_type = str(cfg.get("window_type", "hann"))
    win = build_window(win_len, window_type)
    freqs = np.fft.rfftfreq(nfft, d=1.0 / fs_proc)
    df_bin = fs_proc / nfft

    # 1. Compute un-padded wide-band STFT for unbiased local flanking-bin noise estimation
    # (By Parseval/Rayleigh scaling with identical window `win`, per-bin noise power is
    # invariant to zero-padding, while un-padded rfft is ~15x faster).
    raw_frames = frame_signal(x_proc, win_len, hop_len)
    n_frames = raw_frames.shape[0]
    t_centers = np.arange(n_frames, dtype=np.float64) * hop_s + 0.5 * eff_window_s

    spec_raw_unpad = sp_fft.rfft((raw_frames * win[None, :]).astype(np.float32), n=win_len, axis=1, workers=-1)
    power_raw_unpad = np.abs(spec_raw_unpad).astype(np.float64) ** 2
    freqs_unpad = np.fft.rfftfreq(win_len, d=1.0 / fs_proc)

    # 2. Band-pass each candidate harmonic and extract per-harmonic STFT ridge & local SNR
    bp_order = int(cfg.get("bp_order", 4))
    bp_half_bw_hz = float(cfg.get("bp_half_bw_hz", 0.30))
    search_half_bw_hz = float(cfg.get("search_half_bw_hz", 0.12))
    flank_inner_hz = float(cfg.get("flank_inner_hz", 0.25))
    flank_outer_hz = float(cfg.get("flank_outer_hz", 2.50))
    peak_interp = str(cfg.get("peak_interp", "gaussian_log"))

    n_harm = len(harmonics)
    f_harm = np.zeros((n_harm, n_frames), dtype=np.float64)
    snr_db_harm = np.zeros((n_harm, n_frames), dtype=np.float64)
    snr_excess_harm = np.zeros((n_harm, n_frames), dtype=np.float64)
    edge_hit_harm = np.zeros((n_harm, n_frames), dtype=bool)

    # Common fundamental frequency search grid for spectral harmonic combining (WMLE)
    f0_grid = np.linspace(
        nominal_hz - search_half_bw_hz,
        nominal_hz + search_half_bw_hz,
        481,
        dtype=np.float64,
    )
    norm_profiles = np.zeros((n_harm, n_frames, len(f0_grid)), dtype=np.float64)

    # Band-pass each candidate harmonic in time domain; since passbands are disjoint
    # by >= 50 Hz (>150x filter bandwidth, >300 dB isolation), summing the band-passed
    # signals allows a single zero-padded STFT rfft across all harmonics.
    x_bp_sum = np.zeros_like(x_proc)
    for h in harmonics:
        fc = h * nominal_hz
        x_bp_sum += bandpass_harmonic(
            x_proc,
            fs_proc,
            center_hz=fc,
            half_bw_hz=h * bp_half_bw_hz,
            order=bp_order,
        )
    bp_frames = frame_signal(x_bp_sum, win_len, hop_len)
    spec_bp = sp_fft.rfft((bp_frames * win[None, :]).astype(np.float32), n=nfft, axis=1, workers=-1)
    mag_bp = np.abs(spec_bp).astype(np.float64)
    power_bp = mag_bp ** 2

    for idx_h, h in enumerate(harmonics):
        fc = h * nominal_hz
        # Search band indices at harmonic h
        f_low = h * (nominal_hz - search_half_bw_hz)
        f_high = h * (nominal_hz + search_half_bw_hz)
        sig_mask = (freqs >= f_low) & (freqs <= f_high)
        idx_sig = np.where(sig_mask)[0]
        if len(idx_sig) < 3:
            idx_center = int(round(fc / df_bin))
            idx_sig = np.arange(max(1, idx_center - 2), min(len(freqs) - 1, idx_center + 3))

        peak_local = np.argmax(mag_bp[:, idx_sig], axis=1)
        peak_bin = idx_sig[0] + peak_local
        delta = subbin_interpolate(spec_bp, mag_bp, peak_bin, mode=peak_interp)
        f_est_h = ((peak_bin + delta) * df_bin) / float(h)
        f_est_h = np.clip(f_est_h, nominal_hz - search_half_bw_hz, nominal_hz + search_half_bw_hz)
        f_harm[idx_h] = f_est_h

        # Detect if peak is stuck near search boundary
        edge_hit_harm[idx_h] = (
            np.abs(f_est_h - nominal_hz) >= 0.92 * search_half_bw_hz
        )

        # Measure true narrowband SNR relative to neighbouring flanking bins
        # Mainlobe integration radius in bins (~1.2 / eff_window_s Hz)
        lobe_bins = max(1, int(round((1.2 / eff_window_s) / df_bin)))
        # Flanking noise bins outside [fc - h*flank_inner, fc + h*flank_inner] on unpadded raw spectrum
        in_h = max(flank_inner_hz, h * 0.16)
        out_h = max(flank_outer_hz, h * 0.80)
        flank_mask = (
            ((freqs_unpad >= fc - out_h) & (freqs_unpad <= fc - in_h))
            | ((freqs_unpad >= fc + in_h) & (freqs_unpad <= fc + out_h))
        )
        idx_flank = np.where(flank_mask)[0]
        if len(idx_flank) < 5:
            idx_flank = np.where((freqs_unpad >= f_low) & (freqs_unpad <= f_high))[0]

        # Robust noise floor per bin: median / ln(2) to match exponential mean of Rayleigh^2 bins
        flank_power = power_raw_unpad[:, idx_flank]
        noise_floor_bin = (np.median(flank_power, axis=1) / math.log(2.0)) + 1e-20

        # Vectorized peak mainlobe mean power per bin around peak_bin in bandpassed spectrum
        # (Butterworth passband has unit gain |H(f)|^2 >= 0.995 across the narrow search band)
        offsets = np.arange(-lobe_bins, lobe_bins + 1)
        lobe_idx = np.clip(peak_bin[:, None] + offsets[None, :], 0, power_bp.shape[1] - 1)
        sig_power_bin = np.mean(power_bp[np.arange(n_frames)[:, None], lobe_idx], axis=1)

        ratio = sig_power_bin / noise_floor_bin
        snr_db = 10.0 * np.log10(np.maximum(ratio, 1e-6))
        snr_db_harm[idx_h] = snr_db

        # Expected random maximum ratio across independent search bins in the band
        n_indep_bins = max(2.0, (f_high - f_low) * eff_window_s)
        expected_null_ratio = math.log(n_indep_bins) + 0.5772156649
        snr_excess_harm[idx_h] = np.maximum(0.0, ratio - expected_null_ratio)

        # Vectorized normalized spectral profile on f0_grid for spectral combining (WMLE)
        freqs_sub = freqs[idx_sig] / float(h)
        p_sub = power_bp[:, idx_sig] / (noise_floor_bin[:, None] + 1e-20)
        p_sub_max = np.max(p_sub, axis=1, keepdims=True) + 1e-20
        p_sub_norm = p_sub / p_sub_max
        if len(freqs_sub) >= 2:
            pos = np.interp(f0_grid, freqs_sub, np.arange(len(freqs_sub), dtype=np.float64))
            i0 = np.clip(np.floor(pos).astype(int), 0, len(freqs_sub) - 2)
            frac = (pos - i0)[None, :]
            norm_profiles[idx_h] = (1.0 - frac) * p_sub_norm[:, i0] + frac * p_sub_norm[:, i0 + 1]
        else:
            norm_profiles[idx_h] = p_sub_norm[:, :1]

    # 3. Harmonic Weighting & Combination
    priors_cfg = cfg.get("harmonic_priors", {})
    prior_w = np.array(
        [float(priors_cfg.get(str(h), 1.0)) for h in harmonics],
        dtype=np.float64,
    )
    snr_floor_db = float(cfg.get("snr_floor_db", 3.5))
    snr_power_exp = float(cfg.get("snr_power_exp", 1.5))
    combination_mode = str(cfg.get("combination_mode", "snr_robust_hybrid"))

    # Per-frame SNR weight
    snr_above_floor = np.maximum(0.0, snr_db_harm - snr_floor_db)
    w_frame = (prior_w[:, None] * (snr_above_floor ** snr_power_exp)) + 1e-6
    # Penalize boundary hits
    w_frame = np.where(edge_hit_harm, w_frame * 0.08, w_frame)

    if combination_mode == "single_100hz" and 2 in harmonics:
        idx_2 = harmonics.index(2)
        w_total = np.zeros_like(w_frame)
        w_total[idx_2, :] = 1.0
        f_combined = f_harm[idx_2].copy()
        spec_combined = norm_profiles[idx_2].copy()
    elif combination_mode == "single_50hz" and 1 in harmonics:
        idx_1 = harmonics.index(1)
        w_total = np.zeros_like(w_frame)
        w_total[idx_1, :] = 1.0
        f_combined = f_harm[idx_1].copy()
        spec_combined = norm_profiles[idx_1].copy()
    elif combination_mode == "unweighted_mean":
        w_total = np.ones_like(w_frame) / float(n_harm)
        f_combined = np.mean(f_harm, axis=0)
        spec_combined = np.mean(norm_profiles, axis=0)
    elif combination_mode == "snr_weighted_trace":
        w_total = w_frame / (np.sum(w_frame, axis=0, keepdims=True) + 1e-12)
        f_combined = np.sum(w_total * f_harm, axis=0)
        spec_combined = np.sum(w_total[:, :, None] * norm_profiles, axis=0)
    elif combination_mode == "wmle_spectral":
        # Hajj-Ahmad et al. (2013) weighted spectral combination with quadratic interpolation
        w_total = w_frame / (np.sum(w_frame, axis=0, keepdims=True) + 1e-12)
        spec_combined = np.sum(w_total[:, :, None] * norm_profiles, axis=0)
        pk = np.argmax(spec_combined, axis=1)
        delta_s = subbin_interpolate(
            spec_combined.astype(np.complex128),
            np.sqrt(np.maximum(spec_combined, 0.0)),
            pk,
            mode="parabolic_mag",
        )
        df_grid = f0_grid[1] - f0_grid[0]
        f_combined = f0_grid[0] + (pk + delta_s) * df_grid
    else:
        # Default: "snr_robust_hybrid"
        # Combines local SNR weights, harmonic temporal smoothness, inter-harmonic
        # correlation/consensus (Hua et al. 2021), and joint spectral+trace refinement.
        if n_frames >= 4:
            df_dt = np.diff(f_harm, axis=1) / max(hop_s, 1e-6)
            mad_step = np.median(np.abs(df_dt), axis=1)
            # Expected physical ENF step is ~1-4 mHz/s; noisy bands jump by >15 mHz/s
            w_smooth = np.exp(-((mad_step / 0.012) ** 2))
            # Fraction of frames not stuck on search boundaries
            non_edge_frac = 1.0 - np.mean(edge_hit_harm.astype(np.float64), axis=1)
            w_harm_global = prior_w * w_smooth * (0.15 + 0.85 * non_edge_frac)
        else:
            w_harm_global = prior_w.copy()

        # Inter-harmonic pairwise agreement & consensus score (when >= 2 harmonics exist)
        if n_harm >= 2 and n_frames >= 6:
            med_snr_h = np.median(snr_db_harm, axis=1)
            snr_rank_w = np.maximum(0.05, med_snr_h - 2.0) * w_harm_global
            agree_scores = np.zeros(n_harm, dtype=np.float64)
            for i in range(n_harm):
                fi = f_harm[i]
                si = np.std(fi)
                for j in range(n_harm):
                    if i == j:
                        continue
                    fj = f_harm[j]
                    sj = np.std(fj)
                    if si > 1e-6 and sj > 1e-6:
                        r_ij = float(np.corrcoef(fi, fj)[0, 1])
                    else:
                        r_ij = 0.0
                    med_diff = float(np.median(np.abs(fi - fj)))
                    # Agreement requires both positive trajectory correlation and small frequency offset
                    prox_ij = math.exp(-((med_diff / 0.015) ** 2))
                    corr_pos = max(0.0, r_ij)
                    agree_scores[i] += snr_rank_w[j] * (0.35 * prox_ij + 0.65 * corr_pos * prox_ij)
            if np.max(agree_scores) > 1e-9:
                agree_scores = 0.15 + 0.85 * (agree_scores / np.max(agree_scores))
            else:
                agree_scores = np.ones(n_harm, dtype=np.float64)
        else:
            agree_scores = np.ones(n_harm, dtype=np.float64)

        w_init = w_frame * (w_harm_global * agree_scores)[:, None]
        w_init = w_init / (np.sum(w_init, axis=0, keepdims=True) + 1e-12)

        # Weighted spectral combination to anchor the multi-harmonic mode
        spec_combined = np.sum(w_init[:, :, None] * norm_profiles, axis=0)
        pk = np.argmax(spec_combined, axis=1)
        delta_s = subbin_interpolate(
            spec_combined.astype(np.complex128),
            np.sqrt(np.maximum(spec_combined, 0.0)),
            pk,
            mode="parabolic_mag",
        )
        df_grid = f0_grid[1] - f0_grid[0]
        f_spec_anchor = f0_grid[0] + (pk + delta_s) * df_grid

        # Huber / Tukey-like outlier suppression relative to spectral anchor
        resid = np.abs(f_harm - f_spec_anchor[None, :])
        sigma_r = 0.012  # 12 mHz scale in fundamental-equivalent units
        w_robust = w_init * np.exp(-((resid / sigma_r) ** 2))
        w_total = w_robust / (np.sum(w_robust, axis=0, keepdims=True) + 1e-12)

        # Second pass trace fusion + spectral anchor blend
        f_trace_weighted = np.sum(w_total * f_harm, axis=0)
        f_combined = 0.70 * f_trace_weighted + 0.30 * f_spec_anchor

        # Light temporal outlier glitch filter (suppresses 1-frame acoustic transients)
        med_k = int(cfg.get("temporal_median_kernel", 3))
        if med_k >= 3 and n_frames >= med_k:
            f_med = signal.medfilt(f_combined, kernel_size=med_k)
            max_step = float(cfg.get("max_step_hz_per_s", 0.025)) * hop_s
            glitch = np.abs(f_combined - f_med) > max_step
            f_combined = np.where(glitch, f_med, f_combined)

    # 4. Per-window quality score q(t) in [0, 1] and ENF-presence detection
    # Effective weighted SNR (dB) per frame
    eff_snr_db = np.sum(w_total * snr_db_harm, axis=0)
    # Top-2 harmonic SNR excess per frame
    if n_harm >= 2:
        sorted_snr = np.sort(snr_db_harm, axis=0)
        top2_snr_db = np.mean(sorted_snr[-2:, :], axis=0)
        # Weighted dispersion across harmonics (mHz)
        harm_disp_hz = np.sqrt(
            np.sum(w_total * ((f_harm - f_combined[None, :]) ** 2), axis=0)
        )
        coherence_frame = np.exp(-((harm_disp_hz / 0.018) ** 2))
    else:
        top2_snr_db = snr_db_harm[0]
        coherence_frame = np.ones(n_frames, dtype=np.float64)

    # Local temporal stability per frame
    if n_frames >= 3:
        local_step = np.zeros(n_frames, dtype=np.float64)
        local_step[1:-1] = 0.5 * (
            np.abs(f_combined[1:-1] - f_combined[:-2])
            + np.abs(f_combined[2:] - f_combined[1:-1])
        )
        local_step[0] = abs(f_combined[1] - f_combined[0])
        local_step[-1] = abs(f_combined[-1] - f_combined[-2])
        stability_frame = np.exp(-((local_step / (0.015 * hop_s)) ** 2))
    else:
        stability_frame = np.ones(n_frames, dtype=np.float64)

    # Sigmoid mapping of effective SNR above random-peak noise floor (~5.5 dB)
    snr_q = 1.0 / (1.0 + np.exp(-(eff_snr_db - 6.0) / 2.2))
    q_trace = np.clip(snr_q * (0.35 + 0.35 * stability_frame + 0.30 * coherence_frame), 0.0, 1.0)

    # 5. Distinct Clip-Level ENF-Presence Detector (H1 vs H0)
    presence_info = compute_enf_presence(
        f_combined=f_combined,
        f_harm=f_harm,
        snr_db_harm=snr_db_harm,
        edge_hit_harm=edge_hit_harm,
        harmonics=harmonics,
        hop_s=hop_s,
        presence_threshold=float(cfg.get("presence_threshold", 0.48)),
    )

    # Mark unusable frames as NaN if below min_frame_q
    min_frame_q = float(cfg.get("min_frame_q", 0.05))
    f_out = f_combined.copy()
    unusable = q_trace < min_frame_q
    f_out[unusable] = np.nan

    # Identify active harmonics whose average weight exceeds 0.10
    mean_w_h = np.mean(w_total, axis=1)
    harmonics_used = [int(h) for h, mw in zip(harmonics, mean_w_h) if mw >= 0.08]
    if not harmonics_used:
        harmonics_used = [int(harmonics[int(np.argmax(mean_w_h))])]

    valid_mask = ~np.isnan(f_out)
    frac_valid = float(np.mean(valid_mask)) if n_frames > 0 else 0.0
    median_q = float(np.median(q_trace)) if n_frames > 0 else 0.0
    overall_snr_db = float(np.median(eff_snr_db)) if n_frames > 0 else 0.0

    meta = {
        "source": "audio",
        "method": str(cfg.get("method", "w06_stft_multiharmonic_snr_weighted")),
        "nominal_hz": int(round(nominal_hz)),
        "harmonics_used": harmonics_used,
        "window_s": float(eff_window_s),
        "hop_s": float(hop_s),
        "fs_media": float(fs_media),
        "duration_s": float(duration_s),
        "media_sha256": media_sha256,
        "params": {
            "fs_proc": float(fs_proc),
            "candidate_harmonics": harmonics,
            "window_type": window_type,
            "zero_pad_factor": zero_pad_factor,
            "nfft": int(nfft),
            "bp_order": bp_order,
            "bp_half_bw_hz": bp_half_bw_hz,
            "search_half_bw_hz": search_half_bw_hz,
            "peak_interp": peak_interp,
            "combination_mode": combination_mode,
            "harmonic_mean_weights": {
                str(h): round(float(mw), 4) for h, mw in zip(harmonics, mean_w_h)
            },
        },
        "quality_summary": {
            "median_q": round(median_q, 4),
            "frac_valid": round(frac_valid, 4),
            "snr_db": round(overall_snr_db, 3),
            "enf_present": bool(presence_info["is_present"]),
            "enf_presence_score": round(float(presence_info["score"]), 4),
            "enf_presence_details": presence_info,
        },
        "provenance": {
            "code": "work/W06/audio_enf.py",
            "version": str(cfg.get("version", "1.0.0")),
        },
    }

    return {
        "t": t_centers,
        "f": f_out,
        "f_raw": f_combined,
        "q": q_trace,
        "harmonics": harmonics,
        "f_harm": f_harm,
        "snr_db_harm": snr_db_harm,
        "weights_harm": w_total,
        "f0_grid": f0_grid,
        "spec_combined": spec_combined,
        "norm_profiles": norm_profiles,
        "presence": presence_info,
        "meta": meta,
    }


def compute_enf_presence(
    f_combined: np.ndarray,
    f_harm: np.ndarray,
    snr_db_harm: np.ndarray,
    edge_hit_harm: np.ndarray,
    harmonics: List[int],
    hop_s: float = 1.0,
    presence_threshold: float = 0.48,
) -> Dict[str, Any]:
    """
    Distinct ENF-presence detector (H1: mains hum present vs H0: no mains hum).
    Combines four physical signatures of real grid hum:
      1. Narrowband SNR excess at strong harmonics (especially even/higher harmonics
         h >= 2 that bypass microphone high-pass filters) relative to flanking bins.
      2. Temporal slow-variation stability (Hua et al., IEEE TIFS 2021 TF detector):
         real ENF has small frame-to-frame step variance and low total variance
         compared to random noise peaks jumping across the search band.
      3. Non-boundary interior occupancy: true ENF stays near nominal frequency rather
         than clinging to search boundaries.
      4. Inter-harmonic trajectory coherence: multiple harmonics exhibit correlated
         frequency variations and consistent fundamental-equivalent frequency.
    """
    n_harm, n_frames = f_harm.shape
    if n_frames == 0:
        return {
            "score": 0.0,
            "is_present": False,
            "snr_score": 0.0,
            "stability_score": 0.0,
            "coherence_score": 0.0,
            "best_harmonic": 2,
            "best_harmonic_snr_db": 0.0,
            "tf_variance_hz2": 1.0,
        }

    # Per-harmonic summary stats
    med_snr_h = np.median(snr_db_harm, axis=1)
    p75_snr_h = np.percentile(snr_db_harm, 75, axis=1)
    interior_frac_h = 1.0 - np.mean(edge_hit_harm.astype(np.float64), axis=1)

    if n_frames >= 3:
        var_h = np.var(f_harm, axis=1)
        diff_std_h = np.std(np.diff(f_harm, axis=1) / max(hop_s, 1e-6), axis=1)
        diff_mad_h = np.median(np.abs(np.diff(f_harm, axis=1) / max(hop_s, 1e-6)), axis=1)
    else:
        var_h = np.zeros(n_harm, dtype=np.float64) + 1e-4
        diff_std_h = np.zeros(n_harm, dtype=np.float64) + 0.01
        diff_mad_h = np.zeros(n_harm, dtype=np.float64) + 0.005

    # Prefer h >= 2 on microphone recordings (since h=1 at 50 Hz is often low-freq rumble)
    prior_h = np.array([0.45 if h == 1 else 1.0 for h in harmonics], dtype=np.float64)

    # 1. Harmonic narrowband SNR score (calibrated against finite-bin extreme value ~5.2 dB)
    effective_h_snr = prior_h * (0.6 * med_snr_h + 0.4 * p75_snr_h) * (0.3 + 0.7 * interior_frac_h)
    best_idx = int(np.argmax(effective_h_snr))
    best_h = int(harmonics[best_idx])
    best_snr_db = float(med_snr_h[best_idx])

    # Sort harmonic SNRs (for h >= 2 if available)
    h_ge2_mask = np.array([h >= 2 for h in harmonics], dtype=bool)
    if np.any(h_ge2_mask):
        snr_ge2 = np.sort(med_snr_h[h_ge2_mask])[::-1]
        top1_snr = float(snr_ge2[0])
        top2_snr = float(np.mean(snr_ge2[: min(2, len(snr_ge2))]))
    else:
        top1_snr = best_snr_db
        top2_snr = best_snr_db

    # Sigmoid on top harmonic SNR above the ~6.2 dB random-peak baseline
    snr_score = float(1.0 / (1.0 + math.exp(-(0.65 * top1_snr + 0.35 * top2_snr - 6.8) / 1.5)))

    # 2. Temporal stability score (Hua et al. 2021 TF variance + first-difference smoothness)
    tf_var_combined = float(np.var(f_combined)) if n_frames >= 2 else 1e-3
    tf_var_best = float(var_h[best_idx])
    min_tf_var = min(tf_var_combined, tf_var_best)
    best_diff_mad = min(
        float(np.median(np.abs(np.diff(f_combined) / max(hop_s, 1e-6)))) if n_frames >= 2 else 0.01,
        float(diff_mad_h[best_idx]),
    )
    best_interior = max(
        float(1.0 - np.mean(np.abs(f_combined - np.round(np.median(f_combined))) >= 0.11)),
        float(interior_frac_h[best_idx]),
    )

    # Under H0 (uniform random peak in [-0.12, +0.12] Hz), variance is (0.24)^2 / 12 = 0.0048 Hz^2
    # and step MAD is ~0.060 Hz/s. Under H1, variance is typically < 0.0008 Hz^2 and step MAD < 0.008 Hz/s.
    var_score = math.exp(-min_tf_var / 0.0014)
    step_score = math.exp(-((best_diff_mad / 0.014) ** 2))
    stability_score = float(0.45 * var_score + 0.40 * step_score + 0.15 * best_interior)

    # 3. Inter-harmonic coherence score (pairwise correlation and frequency proximity among top harmonics)
    if n_harm >= 2 and n_frames >= 5:
        pair_corrs = []
        pair_prox = []
        # Check pairs among top-3 harmonics by SNR
        top_indices = np.argsort(effective_h_snr)[::-1][: min(4, n_harm)]
        for idx_a in range(len(top_indices)):
            for idx_b in range(idx_a + 1, len(top_indices)):
                ia, ib = int(top_indices[idx_a]), int(top_indices[idx_b])
                fa, fb = f_harm[ia], f_harm[ib]
                if np.std(fa) > 1e-6 and np.std(fb) > 1e-6:
                    r_ab = float(np.corrcoef(fa, fb)[0, 1])
                else:
                    r_ab = 0.0
                pair_corrs.append(max(0.0, r_ab))
                med_diff = float(np.median(np.abs(fa - fb)))
                pair_prox.append(math.exp(-((med_diff / 0.020) ** 2)))
        max_corr = float(np.max(pair_corrs)) if pair_corrs else 0.0
        mean_prox = float(np.mean(pair_prox)) if pair_prox else 0.0
        coherence_score = float(0.55 * max_corr + 0.45 * mean_prox)
    else:
        coherence_score = float(stability_score)

    # Composite ENF-presence score in [0, 1]
    composite_score = float(
        np.clip(
            0.48 * snr_score + 0.34 * stability_score + 0.18 * coherence_score,
            0.0,
            1.0,
        )
    )

    return {
        "score": round(composite_score, 4),
        "is_present": bool(composite_score >= presence_threshold),
        "threshold": float(presence_threshold),
        "snr_score": round(snr_score, 4),
        "stability_score": round(stability_score, 4),
        "coherence_score": round(coherence_score, 4),
        "best_harmonic": best_h,
        "best_harmonic_snr_db": round(best_snr_db, 3),
        "top2_harmonic_snr_db": round(top2_snr, 3),
        "tf_variance_hz2": round(min_tf_var, 6),
        "step_mad_hz_per_s": round(best_diff_mad, 5),
        "harmonic_median_snrs_db": {
            str(h): round(float(s), 2) for h, s in zip(harmonics, med_snr_h)
        },
    }


def analyse_audio(
    path: Union[str, Path],
    config: Optional[Union[Dict[str, Any], str, Path]] = None,
) -> Tuple[Path, Path]:
    """
    Frozen Extractor API per integration/interfaces.md §1 & §4:
      analyse_audio(path, config) -> (trace_npz_path, trace_json_path)

    Writes `<name>.trace.npz` (with float64 arrays `t`, `f`, `q`) and
    `<name>.trace.json` (metadata and quality summary without any wall-clock timestamps).
    """
    cfg = load_config(config)
    media_path = Path(path)
    out_dir = Path(cfg.get("out_dir", Path(__file__).resolve().parent / "traces"))
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = str(cfg.get("output_stem", media_path.stem))
    npz_path = out_dir / f"{stem}.trace.npz"
    json_path = out_dir / f"{stem}.trace.json"

    res = extract_audio_enf_detailed(media_path, cfg)

    np.savez(
        npz_path,
        t=np.asarray(res["t"], dtype=np.float64),
        f=np.asarray(res["f"], dtype=np.float64),
        q=np.asarray(res["q"], dtype=np.float64),
    )
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(res["meta"], f, indent=2)

    return npz_path, json_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="W06 Audio ENF Extractor A (STFT Multi-Harmonic Family)"
    )
    parser.add_argument("--in", dest="in_path", required=True, help="Input audio/video media path")
    parser.add_argument("--out", dest="out_dir", required=True, help="Output directory for trace files")
    parser.add_argument("--nominal", dest="nominal_hz", type=int, default=None, help="Nominal grid frequency (50 or 60)")
    parser.add_argument("--config", dest="config_path", type=str, default=None, help="Optional JSON config path")
    parser.add_argument("--window-s", dest="window_s", type=float, default=None, help="Override STFT window length (s)")
    parser.add_argument("--hop-s", dest="hop_s", type=float, default=None, help="Override STFT hop length (s)")
    parser.add_argument("--mode", dest="combination_mode", type=str, default=None, help="Override harmonic combination mode")
    args = parser.parse_args()

    cfg = load_config(args.config_path)
    cfg["out_dir"] = str(Path(args.out_dir))
    if args.nominal_hz is not None:
        cfg["nominal_hz"] = int(args.nominal_hz)
    if args.window_s is not None:
        cfg["window_s"] = float(args.window_s)
    if args.hop_s is not None:
        cfg["hop_s"] = float(args.hop_s)
    if args.combination_mode is not None:
        cfg["combination_mode"] = str(args.combination_mode)

    npz_path, json_path = analyse_audio(args.in_path, cfg)
    print(f"Wrote ENF trace NPZ : {npz_path}")
    print(f"Wrote ENF trace JSON: {json_path}")


if __name__ == "__main__":
    main()
