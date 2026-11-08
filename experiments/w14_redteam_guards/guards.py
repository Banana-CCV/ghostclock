#!/usr/bin/env python3
"""
GhostClock Worker W14: Deterministic Adversarial Guards (`work/W14/guards.py`)
==============================================================================
Implements the 6 code-enforced defensive guards designed to prevent GhostClock
from issuing a WRONG confident decision (`MATCH_SUPPORTED` at a wrong or forged
timestamp, or `MATCH_SUPPORTED` on a spliced/manipulated clip):

  - G1 (`spectral_notch_and_suppression_guard`):
      Detects narrowband IIR notch filters at nominal harmonics (Attack a) and
      stationary spectral gating / codec noise-floor mismatch (Attack d4).
  - G2 (`too_clean_injector_guard`):
      Detects synthetic FM sinusoid ENF injection (Attacks b1, b2, b3) via
      abnormally low narrowband envelope coefficient of variation (`CV_A`),
      single-harmonic isolation at high SNR, and unnatural inter-harmonic
      amplitude-ratio lock.
  - G3 (`harmonic_consistency_and_pitch_guard`):
      Detects inter-harmonic trajectory disagreement / per-harmonic reference lag
      conflicts (Attacks b3, c3), in-band dual-ridge double-ENF beating (Attacks
      c1, c2), and pitch shifting / sample-rate clock scaling (Attacks d7a, d7b).
  - G4 (`multi_segment_splice_and_drift_guard`):
      Detects 50/50 splices (f1), 70/30 asymmetric splices (f2), middle-insertion
      overdub/shift splices (f3a, f3b) that evade 2-half split checks, and
      resampling / WSOLA time-stretch lag drift (d5b, d6a, d6b).
  - G5 (`duration_and_uniqueness_guard`):
      Enforces strict minimum valid ENF duration (`>= 60 s` for 24-hour blind
      search) and peak uniqueness margin to block short-crop false matches (Attack e).
  - G6 (`audio_video_agreement_guard`):
      Enforces cross-modal agreement between audio ENF and rolling-shutter video
      ENF without ever multiplying their confidences (Scientific Ground Truth #3).

CLI usage from repo root:
    python work/W14/guards.py --in datasets/raw/enf-whu/repo/ENF-WHU-Dataset/H1/001.wav --out work/W14/demo_guard.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import soundfile as sf
from scipy import fft as sp_fft
from scipy import signal
from scipy.ndimage import median_filter

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _fast_sliding_ncc(query: np.ndarray, ref: np.ndarray) -> np.ndarray:
    """
    Fast O(R log R) sliding normalized cross-correlation of `query` against `ref`.
    Handles NaNs in `query` via zero-replacement after mean-centering valid points.
    """
    q = np.asarray(query, dtype=np.float64).ravel()
    r = np.asarray(ref, dtype=np.float64).ravel()
    L = len(q)
    R = len(r)
    if L < 4 or R < L:
        return np.zeros(max(1, R - L + 1), dtype=np.float64)

    valid_q = np.isfinite(q)
    if np.sum(valid_q) < 4:
        return np.zeros(R - L + 1, dtype=np.float64)

    q_mean = float(np.mean(q[valid_q]))
    q_zm = np.where(valid_q, q - q_mean, 0.0)
    w_q = valid_q.astype(np.float64)
    norm_q = float(np.sqrt(np.sum(q_zm ** 2)))
    if norm_q <= 1e-12:
        return np.zeros(R - L + 1, dtype=np.float64)

    valid_r = np.isfinite(r)
    r_clean = np.where(valid_r, r, float(np.nanmedian(r)) if np.any(valid_r) else 50.0)

    cross = signal.fftconvolve(r_clean, q_zm[::-1], mode="valid")
    sum_r = signal.fftconvolve(r_clean, w_q[::-1], mode="valid")
    sum_r2 = signal.fftconvolve(r_clean ** 2, w_q[::-1], mode="valid")
    n_eff = np.maximum(1.0, float(np.sum(w_q)))
    var_r = np.maximum(0.0, sum_r2 - (sum_r ** 2) / n_eff)
    denom = norm_q * np.sqrt(var_r)
    scores = np.where(denom > 1e-12, cross / denom, 0.0)
    return np.clip(scores, -1.0, 1.0)


def extract_harmonic_diagnostics(
    audio: np.ndarray,
    fs: float,
    nominal_hz: float = 50.0,
    harmonics: Sequence[int] = (1, 2, 3, 4, 5, 6, 7),
    window_s: float = 16.0,
    hop_s: float = 1.0,
    search_half_bw_hz: float = 0.12,
) -> Dict[str, Any]:
    """
    Extract multi-harmonic STFT ridges, narrowband amplitude envelopes A_h(t),
    flanking-bin SNRs, and secondary in-band peaks (after masking the primary ridge)
    for adversarial guard inspection.
    """
    x = np.asarray(audio, dtype=np.float64)
    if x.ndim > 1:
        x = np.mean(x, axis=1)
    x = x - np.mean(x)
    duration_s = float(len(x) / fs) if fs > 0 else 0.0

    # Downsample to 1000 Hz via Kaiser anti-aliasing polyphase filter
    fs_target = 1000.0
    if fs > fs_target + 1.0:
        g = math.gcd(int(round(fs)), int(round(fs_target)))
        up = int(round(fs_target)) // g
        down = int(round(fs)) // g
        x_proc = signal.resample_poly(x, up, down, window=("kaiser", 8.0))
        fs_proc = float(fs_target)
    else:
        x_proc = x
        fs_proc = float(fs)

    eff_win_s = min(window_s, max(2.0, duration_s * 0.8))
    win_len = max(16, int(round(eff_win_s * fs_proc)))
    hop_len = max(1, int(round(hop_s * fs_proc)))
    nfft = max(32768, int(2 ** math.ceil(math.log2(win_len * 4))))

    if len(x_proc) < win_len:
        x_proc = np.pad(x_proc, (0, win_len - len(x_proc)), mode="reflect" if len(x_proc) > 1 else "constant")

    n_frames = (len(x_proc) - win_len) // hop_len + 1
    strides = (x_proc.strides[0] * hop_len, x_proc.strides[0])
    frames = np.lib.stride_tricks.as_strided(x_proc, shape=(n_frames, win_len), strides=strides)
    win = signal.windows.hann(win_len, sym=False)
    t_centers = np.arange(n_frames, dtype=np.float64) * hop_s + 0.5 * eff_win_s

    # Unpadded STFT for flanking noise estimation
    spec_unpad = sp_fft.rfft((frames * win[None, :]).astype(np.float32), n=win_len, axis=1, workers=-1)
    power_unpad = np.abs(spec_unpad).astype(np.float64) ** 2
    freqs_unpad = np.fft.rfftfreq(win_len, d=1.0 / fs_proc)

    # Zero-padded STFT up to 400 Hz for fine ridge and secondary peak extraction
    valid_h = [int(h) for h in harmonics if (h * nominal_hz + 5.0) < 0.48 * fs_proc]
    max_freq_needed = max(valid_h) * (nominal_hz + 1.0)
    max_bin = min(nfft // 2, int(math.ceil(max_freq_needed * nfft / fs_proc)) + 8)
    spec_pad = sp_fft.rfft((frames * win[None, :]).astype(np.float32), n=nfft, axis=1, workers=-1)[:, :max_bin]
    mag_pad = np.abs(spec_pad).astype(np.float64)
    power_pad = mag_pad ** 2
    df_pad = fs_proc / float(nfft)
    freqs_pad = np.arange(max_bin, dtype=np.float64) * df_pad

    n_h = len(valid_h)
    f_harm = np.zeros((n_h, n_frames), dtype=np.float64)
    snr_db_harm = np.zeros((n_h, n_frames), dtype=np.float64)
    amp_harm = np.zeros((n_h, n_frames), dtype=np.float64)
    sec_f_harm = np.zeros((n_h, n_frames), dtype=np.float64)
    sec_snr_db_harm = np.zeros((n_h, n_frames), dtype=np.float64)
    edge_hit_harm = np.zeros((n_h, n_frames), dtype=bool)

    lobe_radius_bins = max(2, int(round((1.6 / eff_win_s) / df_pad)))
    rows = np.arange(n_frames)

    for ih, h in enumerate(valid_h):
        fc = h * nominal_hz
        f_lo = h * (nominal_hz - search_half_bw_hz)
        f_hi = h * (nominal_hz + search_half_bw_hz)
        idx_band = np.where((freqs_pad >= f_lo) & (freqs_pad <= f_hi))[0]
        if len(idx_band) < 3:
            c_bin = int(round(fc / df_pad))
            idx_band = np.arange(max(1, c_bin - 2), min(max_bin - 2, c_bin + 3))

        sub_mag = mag_pad[:, idx_band]
        pk_local = np.argmax(sub_mag, axis=1)
        pk_bin = idx_band[0] + pk_local
        pk_safe = np.clip(pk_bin, 1, max_bin - 2)

        # Log-parabolic sub-bin interpolation
        a_l = np.log(mag_pad[rows, pk_safe - 1] + 1e-18)
        b_c = np.log(mag_pad[rows, pk_safe] + 1e-18)
        c_r = np.log(mag_pad[rows, pk_safe + 1] + 1e-18)
        denom = a_l - 2.0 * b_c + c_r
        delta = np.where(denom < -1e-18, 0.5 * (a_l - c_r) / (denom - 1e-18), 0.0)
        delta = np.clip(delta, -0.5, 0.5)

        f_est = ((pk_bin + delta) * df_pad) / float(h)
        f_est = np.clip(f_est, nominal_hz - search_half_bw_hz, nominal_hz + search_half_bw_hz)
        f_harm[ih] = f_est
        amp_harm[ih] = mag_pad[rows, pk_bin]
        edge_hit_harm[ih] = np.abs(f_est - nominal_hz) >= 0.92 * search_half_bw_hz

        # Flanking noise floor on unpadded STFT
        in_h = max(0.28, h * 0.16)
        out_h = max(2.50, h * 0.80)
        flank_mask = (
            ((freqs_unpad >= fc - out_h) & (freqs_unpad <= fc - in_h))
            | ((freqs_unpad >= fc + in_h) & (freqs_unpad <= fc + out_h))
        )
        idx_flank = np.where(flank_mask)[0]
        if len(idx_flank) < 4:
            idx_flank = np.arange(max(1, int(fc - 2)), min(len(freqs_unpad) - 1, int(fc + 3)))
        noise_floor = (np.median(power_unpad[:, idx_flank], axis=1) / math.log(2.0)) + 1e-20

        # Primary mainlobe power
        lobe_bins = max(1, int(round((1.2 / eff_win_s) / df_pad)))
        offs = np.arange(-lobe_bins, lobe_bins + 1)
        lobe_idx = np.clip(pk_bin[:, None] + offs[None, :], 0, max_bin - 1)
        sig_p = np.mean(power_pad[rows[:, None], lobe_idx], axis=1)
        snr_db_harm[ih] = 10.0 * np.log10(np.maximum(sig_p / noise_floor, 1e-6))

        # Secondary in-band peak after masking +/- (h * lobe_radius_bins) around primary peak
        sub_power_masked = power_pad[:, idx_band].copy()
        mask_rad = max(lobe_radius_bins, int(round(h * 0.032 / df_pad)))
        band_pos = np.arange(len(idx_band))[None, :]
        near_primary = np.abs(band_pos - pk_local[:, None]) <= mask_rad
        sub_power_masked[near_primary] = 0.0

        sec_local = np.argmax(sub_power_masked, axis=1)
        sec_bin = idx_band[0] + sec_local
        sec_p = sub_power_masked[rows, sec_local]
        sec_snr_db_harm[ih] = 10.0 * np.log10(np.maximum(sec_p / noise_floor, 1e-6))
        sec_f_harm[ih] = (sec_bin * df_pad) / float(h)

    # Combine harmonics using W06 inter-harmonic consensus + smoothness weighting
    prior_w = np.array([0.35 if h == 1 else 1.0 for h in valid_h], dtype=np.float64)
    snr_above = np.maximum(0.0, snr_db_harm - 3.5)
    w_frame = (prior_w[:, None] * (snr_above ** 1.5)) + 1e-6
    w_frame = np.where(edge_hit_harm, w_frame * 0.08, w_frame)

    if n_frames >= 4:
        mad_step = np.median(np.abs(np.diff(f_harm, axis=1)) / max(hop_s, 1e-6), axis=1)
        w_smooth = np.exp(-((mad_step / 0.012) ** 2))
        non_edge = 1.0 - np.mean(edge_hit_harm.astype(np.float64), axis=1)
        w_harm_global = prior_w * w_smooth * (0.15 + 0.85 * non_edge)
    else:
        w_harm_global = prior_w.copy()

    if n_h >= 2 and n_frames >= 6:
        med_snr_h = np.median(snr_db_harm, axis=1)
        snr_rank_w = np.maximum(0.05, med_snr_h - 2.0) * w_harm_global
        agree_scores = np.zeros(n_h, dtype=np.float64)
        for i in range(n_h):
            fi = f_harm[i]
            si = np.std(fi)
            for j in range(n_h):
                if i == j:
                    continue
                fj = f_harm[j]
                sj = np.std(fj)
                r_ij = float(np.corrcoef(fi, fj)[0, 1]) if (si > 1e-6 and sj > 1e-6) else 0.0
                med_diff = float(np.median(np.abs(fi - fj)))
                prox_ij = math.exp(-((med_diff / 0.015) ** 2))
                agree_scores[i] += snr_rank_w[j] * (0.35 * prox_ij + 0.65 * max(0.0, r_ij) * prox_ij)
        if np.max(agree_scores) > 1e-9:
            agree_scores = 0.15 + 0.85 * (agree_scores / np.max(agree_scores))
        else:
            agree_scores = np.ones(n_h, dtype=np.float64)
    else:
        agree_scores = np.ones(n_h, dtype=np.float64)

    w_init = w_frame * (w_harm_global * agree_scores)[:, None]
    w_total = w_init / (np.sum(w_init, axis=0, keepdims=True) + 1e-12)
    f_combined = np.sum(w_total * f_harm, axis=0)

    if n_frames >= 3:
        f_med = signal.medfilt(f_combined, kernel_size=3)
        glitch = np.abs(f_combined - f_med) > 0.025 * hop_s
        f_combined = np.where(glitch, f_med, f_combined)

    eff_snr_db = np.sum(w_total * snr_db_harm, axis=0)
    snr_q = 1.0 / (1.0 + np.exp(-(eff_snr_db - 6.0) / 2.2))
    q_trace = np.clip(snr_q, 0.05, 1.0)

    try:
        from work.W06.audio_enf import compute_enf_presence
        presence_info = compute_enf_presence(
            f_combined=f_combined,
            f_harm=f_harm,
            snr_db_harm=snr_db_harm,
            edge_hit_harm=edge_hit_harm,
            harmonics=valid_h,
            hop_s=hop_s,
            presence_threshold=0.48,
        )
    except Exception:
        best_snr = float(np.max(np.median(snr_db_harm, axis=1)))
        pres_sc = float(1.0 / (1.0 + math.exp(-(best_snr - 6.8) / 1.8)))
        presence_info = {"score": round(pres_sc, 4), "is_present": pres_sc >= 0.48}

    meta = {
        "source": "audio",
        "method": "w06_w14_stft_multiharmonic",
        "nominal_hz": int(round(nominal_hz)),
        "duration_s": float(duration_s),
        "quality_summary": {
            "median_q": round(float(np.median(q_trace)), 4),
            "frac_valid": 1.0,
            "snr_db": round(float(np.median(eff_snr_db)), 3),
            "enf_present": bool(presence_info["is_present"]),
            "enf_presence_score": round(float(presence_info["score"]), 4),
        },
    }

    return {
        "t": t_centers,
        "f": f_combined,
        "q": q_trace,
        "presence": presence_info,
        "meta": meta,
        "harmonics": valid_h,
        "f_harm": f_harm,
        "snr_db_harm": snr_db_harm,
        "amp_harm": amp_harm,
        "sec_f_harm": sec_f_harm,
        "sec_snr_db_harm": sec_snr_db_harm,
        "edge_hit_harm": edge_hit_harm,
        "x_proc_1khz": x_proc,
        "fs_proc": fs_proc,
        "duration_s": duration_s,
    }


# =============================================================================
# Guard G1: Spectral Notch & Stationary Noise Suppression Detector
# =============================================================================
def guard_g1_notch_and_suppression(
    audio: np.ndarray,
    fs: float,
    nominal_hz: float = 50.0,
    harmonics: Sequence[int] = (1, 2, 3, 4, 5, 6, 7),
    mode: str = "v2_calibrated",
) -> Dict[str, Any]:
    """
    G1: Detect deliberate narrowband notch filtering at ENF harmonics (Attack a)
    and heavy stationary spectral gating / codec noise-floor mismatch (Attack d4).
    """
    x = np.asarray(audio, dtype=np.float64)
    if x.ndim > 1:
        x = np.mean(x, axis=1)
    x = x - np.mean(x)

    if fs > 1000.0:
        g = math.gcd(int(round(fs)), 1000)
        x_1k = signal.resample_poly(x, 1000 // g, int(round(fs)) // g, window=("kaiser", 8.0))
        fs_w = 1000.0
    else:
        x_1k = x
        fs_w = float(fs)

    nperseg = min(len(x_1k), int(round(8.0 * fs_w)))
    nfft = max(32768, int(2 ** math.ceil(math.log2(max(16, nperseg * 4)))))
    freqs, psd = signal.welch(
        x_1k, fs=fs_w, window="hann", nperseg=nperseg, noverlap=nperseg // 2, nfft=nfft
    )
    psd = psd + 1e-30

    dip_db_per_h: Dict[int, float] = {}
    shoulder_dip_per_h: Dict[int, float] = {}
    notched_harmonics: List[int] = []

    # Thresholds: v1_naive vs v2_calibrated
    dip_single_thresh = -5.5 if mode == "v1_naive" else -8.5
    dip_multi_thresh = -3.8 if mode == "v1_naive" else -5.8
    shoulder_thresh = -3.0 if mode == "v1_naive" else -4.8

    for h in harmonics:
        fc = h * nominal_hz
        if fc >= 0.47 * fs_w:
            continue
        core_mask = (freqs >= fc - 0.14) & (freqs <= fc + 0.14)
        mid_mask = (
            ((freqs >= fc - 0.55) & (freqs <= fc - 0.20))
            | ((freqs >= fc + 0.20) & (freqs <= fc + 0.55))
        )
        flank_mask = (
            ((freqs >= fc - 3.0) & (freqs <= fc - 0.70))
            | ((freqs >= fc + 0.70) & (freqs <= fc + 3.0))
        )
        p_core = float(np.mean(psd[core_mask]))
        p_mid = float(np.median(psd[mid_mask]))
        p_flank = float(np.median(psd[flank_mask]))

        dip_flank = 10.0 * math.log10(p_core / max(p_flank, 1e-30))
        dip_shoulder = 10.0 * math.log10(p_core / max(p_mid, 1e-30))
        dip_db_per_h[int(h)] = round(dip_flank, 2)
        shoulder_dip_per_h[int(h)] = round(dip_shoulder, 2)

        if dip_flank <= dip_multi_thresh and dip_shoulder <= shoulder_thresh:
            notched_harmonics.append(int(h))

    min_dip_db = min(dip_db_per_h.values()) if dip_db_per_h else 0.0
    min_shoulder_db = min(shoulder_dip_per_h.values()) if shoulder_dip_per_h else 0.0
    notch_detected = bool(
        len(notched_harmonics) >= 2
        or (len(notched_harmonics) >= 1 and min_dip_db <= dip_single_thresh and min_shoulder_db <= -6.0)
    )

    # Check for heavy stationary spectral gating (Attack d4)
    # In spectral gating, the low-frequency narrowband bins (< 380 Hz) exhibit abrupt bimodal
    # on/off gating across 0.25s frames where stationary intervals drop > 22 dB below median
    w_short = max(16, int(round(0.25 * fs_w)))
    _, _, Z_short = signal.stft(x_1k, fs=fs_w, window="hann", nperseg=w_short, noverlap=w_short // 2)
    f_short = np.fft.rfftfreq(w_short, d=1.0 / fs_w)
    low_band = (f_short >= 40.0) & (f_short <= 360.0)
    if np.any(low_band) and Z_short.shape[1] >= 12:
        mag_low = np.abs(Z_short[low_band, :]) + 1e-18
        # Per-bin ratio of p20 to p85 across time: spectral gating clamps stationary bins at p35 by >20 dB
        log_mag = 20.0 * np.log10(mag_low)
        p20 = np.percentile(log_mag, 20, axis=1)
        p50 = np.percentile(log_mag, 50, axis=1)
        p90 = np.percentile(log_mag, 90, axis=1)
        # In natural audio, p50 - p20 in 4 Hz bins is ~4-8 dB (Rayleigh distribution).
        # In heavy spectral gating, bins just below threshold are crushed by 20-35 dB!
        crush_db = float(np.percentile(p90 - p20, 75))
        bimodal_gap_db = float(np.percentile(p50 - p20, 80))
        gating_detected = bool(crush_db >= 31.0 and bimodal_gap_db >= 14.5)
    else:
        crush_db = 0.0
        bimodal_gap_db = 0.0
        gating_detected = False

    triggered = bool(notch_detected or gating_detected)
    reasons = []
    if notch_detected:
        reasons.append(
            f"G1_NOTCH_FILTER_DETECTED: Narrowband spectral notch detected at harmonics {notched_harmonics} "
            f"(min dip = {min_dip_db:.2f} dB, shoulder dip = {min_shoulder_db:.2f} dB)."
        )
    if gating_detected:
        reasons.append(
            f"G1_SPECTRAL_GATING_DETECTED: Heavy stationary spectral gating detected in <360 Hz band "
            f"(p90-p20 crush = {crush_db:.1f} dB, p50-p20 gap = {bimodal_gap_db:.1f} dB)."
        )

    return {
        "guard_id": "G1",
        "name": "spectral_notch_and_suppression_guard",
        "triggered": triggered,
        "notch_detected": notch_detected,
        "gating_detected": gating_detected,
        "notched_harmonics": notched_harmonics,
        "min_dip_db": round(min_dip_db, 2),
        "dip_db_per_harmonic": dip_db_per_h,
        "gating_crush_db": round(crush_db, 2),
        "gating_bimodal_gap_db": round(bimodal_gap_db, 2),
        "reasons": reasons,
    }


# =============================================================================
# Guard G2: "Too-Clean" Synthetic Hum Injector Detector
# =============================================================================
def guard_g2_too_clean_injector(
    harm_diag: Dict[str, Any],
    mode: str = "v2_calibrated",
) -> Dict[str, Any]:
    """
    G2: Detect synthetic FM sinusoid ENF injection (Attacks b1, b2, b3).
    Authentic acoustic/inductive mains hum exhibits natural room/coupling amplitude
    modulation (`cv_amp`), multi-harmonic excitation at high SNR, and independent
    inter-harmonic fading across room wavelengths.
    A constant-amplitude synthetic FM injection exhibits:
      1. Abnormally low amplitude CV (`cv_amp_best < thresh`) on the dominant harmonic, OR
      2. Extreme single-harmonic isolation (`dom_snr_db >= 11.5 dB` while all other
         harmonics have `snr < 3.5 dB`) coupled with steady envelope (`cv_amp_best < 0.14`), OR
      3. Multi-harmonic synthetic amplitude lock (two or more harmonics with `snr >= 9 dB`
         whose envelopes have `cv_amp < 0.085` and log-ratio std `< 0.075`).
    """
    snr_db_harm = harm_diag["snr_db_harm"]
    amp_harm = harm_diag["amp_harm"]
    harmonics = harm_diag["harmonics"]
    n_h, n_frames = snr_db_harm.shape

    if n_frames < 8 or n_h == 0:
        return {
            "guard_id": "G2",
            "name": "too_clean_injector_guard",
            "triggered": False,
            "reasons": [],
        }

    # Trim first and last frame to avoid window boundary taper effects
    sl = slice(1, max(2, n_frames - 1))
    med_snr_h = np.median(snr_db_harm[:, sl], axis=1)
    best_idx = int(np.argmax(med_snr_h))
    best_h = int(harmonics[best_idx])
    best_snr_db = float(med_snr_h[best_idx])

    # Compute robust and standard amplitude CV per harmonic
    cv_amp_h = np.zeros(n_h, dtype=np.float64)
    iqr_cv_h = np.zeros(n_h, dtype=np.float64)
    for ih in range(n_h):
        a = amp_harm[ih, sl]
        mu = float(np.mean(a)) + 1e-18
        med = float(np.median(a)) + 1e-18
        cv_amp_h[ih] = float(np.std(a) / mu)
        q75, q25 = np.percentile(a, [75, 25])
        iqr_cv_h[ih] = float((q75 - q25) / (1.349 * med))

    best_cv = float(min(cv_amp_h[best_idx], iqr_cv_h[best_idx]))

    # Secondary harmonic SNR (excluding best_idx)
    other_snrs = [float(med_snr_h[i]) for i in range(n_h) if i != best_idx]
    second_snr_db = max(other_snrs) if other_snrs else 0.0
    snr_dominance_db = best_snr_db - second_snr_db

    # Multi-harmonic log-amplitude ratio stability among harmonics with SNR >= 7.5 dB
    active_hi = [i for i in range(n_h) if med_snr_h[i] >= 7.5]
    min_log_ratio_std = 99.0
    if len(active_hi) >= 2:
        for idx_a in range(len(active_hi)):
            for idx_b in range(idx_a + 1, len(active_hi)):
                ia, ib = active_hi[idx_a], active_hi[idx_b]
                log_r = np.log((amp_harm[ia, sl] + 1e-18) / (amp_harm[ib, sl] + 1e-18))
                q75, q25 = np.percentile(log_r, [75, 25])
                r_std = float(min(np.std(log_r), (q75 - q25) / 1.349))
                if r_std < min_log_ratio_std:
                    min_log_ratio_std = r_std

    if mode == "v1_naive":
        # Overly aggressive v1 thresholds (flags some quiet room recordings)
        cv_floor = 0.16
        single_tone_cv_floor = 0.22
    else:
        # Calibrated v2 physical thresholds on dev split
        cv_floor = 0.068
        single_tone_cv_floor = 0.115

    # Signature 1: Ultra-flat constant-envelope harmonic at moderate-to-high SNR
    sig1_ultra_flat = bool(best_snr_db >= 7.5 and best_cv < cv_floor)

    # Signature 2: Single-tone isolated injection (e.g. pure 100 Hz injected with zero harmonic family)
    sig2_isolated_single = bool(
        best_snr_db >= 8.5
        and second_snr_db < 4.5
        and snr_dominance_db >= 5.5
        and best_cv < single_tone_cv_floor
    )

    # Signature 3: Constant-amplitude multi-harmonic synthesis (locked envelope ratios + low CV)
    sig3_multi_locked = bool(
        len(active_hi) >= 2
        and best_snr_db >= 8.5
        and best_cv < 0.095
        and min_log_ratio_std < 0.085
    )

    triggered = bool(sig1_ultra_flat or sig2_isolated_single or sig3_multi_locked)
    reasons = []
    if sig1_ultra_flat:
        reasons.append(
            f"G2_TOO_CLEAN_ENVELOPE: Dominant harmonic h={best_h} (SNR={best_snr_db:.1f} dB) has "
            f"unnaturally flat amplitude envelope CV={best_cv:.4f} (< {cv_floor:.3f}), consistent with "
            f"constant-amplitude synthetic FM injection."
        )
    if sig2_isolated_single:
        reasons.append(
            f"G2_SINGLE_HARMONIC_SYNTHETIC_ISOLATION: Harmonic h={best_h} has SNR={best_snr_db:.1f} dB "
            f"while all other harmonics are absent (max other SNR={second_snr_db:.1f} dB, dominance=+{snr_dominance_db:.1f} dB) "
            f"with low envelope variation CV={best_cv:.4f}."
        )
    if sig3_multi_locked:
        reasons.append(
            f"G2_MULTI_HARMONIC_AMPLITUDE_LOCK: Active harmonics {[harmonics[i] for i in active_hi]} exhibit "
            f"synthetically locked amplitude ratios (log-ratio std={min_log_ratio_std:.4f}) and low envelope CV={best_cv:.4f}."
        )

    return {
        "guard_id": "G2",
        "name": "too_clean_injector_guard",
        "triggered": triggered,
        "best_harmonic": best_h,
        "best_snr_db": round(best_snr_db, 2),
        "second_snr_db": round(second_snr_db, 2),
        "snr_dominance_db": round(snr_dominance_db, 2),
        "best_amp_cv": round(best_cv, 4),
        "min_interharmonic_log_ratio_std": round(min_log_ratio_std, 4) if min_log_ratio_std < 90.0 else None,
        "sig1_ultra_flat": sig1_ultra_flat,
        "sig2_isolated_single": sig2_isolated_single,
        "sig3_multi_locked": sig3_multi_locked,
        "reasons": reasons,
    }


# =============================================================================
# Guard G3: Inter-Harmonic Consistency, Double-ENF & Pitch-Shift Detector
# =============================================================================
def guard_g3_harmonic_consistency_and_pitch(
    harm_diag: Dict[str, Any],
    audio: np.ndarray,
    fs: float,
    ref_f: Optional[np.ndarray] = None,
    nominal_hz: float = 50.0,
    mode: str = "v2_calibrated",
) -> Dict[str, Any]:
    """
    G3: Detect:
      (1) Inter-harmonic trajectory conflict / harmonic-split double ENF (Attacks b3, c3)
          where two strong, smooth harmonics in the same clip follow uncorrelated
          ENF trajectories or match different reference lags.
      (2) Same-band double ENF (Attacks c1, c2, b3) where two concurrent grid traces
          create an in-band secondary narrowband ridge that matches a second reference
          timestamp or induces severe multi-tone beating.
      (3) Pitch shift / sample-clock scaling (Attacks d7a, d7b) where the harmonic
          comb is shifted away from nominal 50.0 Hz by >= 0.35% (>= 175 mHz).
    """
    f_harm = harm_diag["f_harm"]
    snr_db_harm = harm_diag["snr_db_harm"]
    sec_f_harm = harm_diag["sec_f_harm"]
    sec_snr_db_harm = harm_diag["sec_snr_db_harm"]
    edge_hit_harm = harm_diag["edge_hit_harm"]
    harmonics = harm_diag["harmonics"]
    n_h, n_frames = f_harm.shape

    reasons: List[str] = []
    if n_frames < 8:
        return {
            "guard_id": "G3",
            "name": "harmonic_consistency_and_pitch_guard",
            "triggered": False,
            "reasons": [],
        }

    med_snr_h = np.median(snr_db_harm, axis=1)
    step_mad_mhz = np.median(np.abs(np.diff(f_harm, axis=1)), axis=1) * 1000.0
    std_mhz = np.std(f_harm, axis=1) * 1000.0
    interior_frac = 1.0 - np.mean(edge_hit_harm.astype(np.float64), axis=1)

    # 1. Identify smooth, ENF-bearing harmonics
    # In v1_naive, including low-SNR h=1 (50 Hz) or rough speech-corrupted bands causes false alarms!
    # In v2_calibrated, a harmonic is considered a "coherent ENF carrier" only if it has high SNR,
    # smooth frame-to-frame steps, non-flat std, and stays inside the search band.
    snr_min_h = 5.2 if mode == "v1_naive" else 8.2
    step_max_mhz = 12.0 if mode == "v1_naive" else 5.8

    coherent_indices: List[int] = []
    for ih, h in enumerate(harmonics):
        req_snr = (snr_min_h + 2.0) if (h == 1 and mode == "v2_calibrated") else snr_min_h
        if (
            med_snr_h[ih] >= req_snr
            and step_mad_mhz[ih] <= step_max_mhz
            and 1.2 <= std_mhz[ih] <= 65.0
            and interior_frac[ih] >= 0.75
        ):
            coherent_indices.append(ih)

    # Check pairwise correlation and per-harmonic reference lag agreement among coherent harmonics
    min_pair_corr = 1.0
    conflicting_pair: Optional[Tuple[int, int, float]] = None
    lag_conflict_pair: Optional[Tuple[int, int, int, int, float, float]] = None

    # For reference matching, include any harmonic with moderate SNR >= 5.5 dB and step_mad <= 9.0 mHz
    ref_cand_indices = [
        ih
        for ih, h in enumerate(harmonics)
        if med_snr_h[ih] >= (7.5 if h == 1 else 5.5)
        and step_mad_mhz[ih] <= 9.0
        and std_mhz[ih] >= 1.1
    ]
    per_h_ref_matches: Dict[int, Dict[str, float]] = {}
    if ref_f is not None and len(ref_f) >= n_frames + 10:
        for ih in ref_cand_indices:
            scores_h = _fast_sliding_ncc(f_harm[ih], ref_f)
            best_lag_h = int(np.argmax(scores_h))
            best_r_h = float(scores_h[best_lag_h])
            per_h_ref_matches[int(harmonics[ih])] = {
                "lag_s": best_lag_h,
                "r": round(best_r_h, 4),
                "snr_db": round(float(med_snr_h[ih]), 2),
            }

    if len(coherent_indices) >= 2:
        for i_idx in range(len(coherent_indices)):
            for j_idx in range(i_idx + 1, len(coherent_indices)):
                ia, ib = coherent_indices[i_idx], coherent_indices[j_idx]
                ha, hb = int(harmonics[ia]), int(harmonics[ib])
                fa, fb = f_harm[ia], f_harm[ib]
                r_ab = float(np.corrcoef(fa, fb)[0, 1]) if (np.std(fa) > 1e-6 and np.std(fb) > 1e-6) else 0.0
                if r_ab < min_pair_corr:
                    min_pair_corr = r_ab
                    conflicting_pair = (ha, hb, r_ab)

    # Check per-harmonic reference lag conflict across all ref_cand_indices
    if len(per_h_ref_matches) >= 2:
        h_keys = sorted(per_h_ref_matches.keys())
        for i_k in range(len(h_keys)):
            for j_k in range(i_k + 1, len(h_keys)):
                ha, hb = h_keys[i_k], h_keys[j_k]
                ma, mb = per_h_ref_matches[ha], per_h_ref_matches[hb]
                # Require both harmonics to strongly match the 24h reference (r >= 0.58)
                # at timestamps separated by > 30s, AND low direct correlation between them
                ia, ib = harmonics.index(ha), harmonics.index(hb)
                r_ab = float(np.corrcoef(f_harm[ia], f_harm[ib])[0, 1])
                if ma["r"] >= 0.58 and mb["r"] >= 0.58 and abs(ma["lag_s"] - mb["lag_s"]) > 30 and r_ab < 0.35:
                    lag_conflict_pair = (ha, hb, int(ma["lag_s"]), int(mb["lag_s"]), ma["r"], mb["r"])

    corr_conflict_thresh = 0.35 if mode == "v1_naive" else 0.12
    inter_harmonic_conflict = bool(
        lag_conflict_pair is not None
        or (
            conflicting_pair is not None
            and min_pair_corr < corr_conflict_thresh
            and len(coherent_indices) >= 2
        )
    )

    # Also check if a single harmonic was spoofed over an H1 clip (Attack b3):
    # Even if non-spoofed harmonics have slightly higher step_mad due to speech, check if the
    # consensus of all remaining harmonics (h != best_h with med_snr >= 5.0 dB) matches a DIFFERENT
    # reference lag with r >= 0.52 than the dominant harmonic!
    best_ih = int(np.argmax(med_snr_h))
    best_h = int(harmonics[best_ih])
    other_active = [i for i in range(n_h) if i != best_ih and med_snr_h[i] >= 4.8]
    residual_harmonic_conflict = False
    residual_lag_info: Optional[Dict[str, Any]] = None
    if ref_f is not None and len(ref_f) >= n_frames + 10 and len(other_active) >= 2:
        w_other = np.maximum(0.1, med_snr_h[other_active] - 3.5)[:, None]
        f_other_mean = np.sum(w_other * f_harm[other_active], axis=0) / np.sum(w_other)
        sc_best = _fast_sliding_ncc(f_harm[best_ih], ref_f)
        sc_other = _fast_sliding_ncc(f_other_mean, ref_f)
        lag_b, r_b = int(np.argmax(sc_best)), float(np.max(sc_best))
        lag_o, r_o = int(np.argmax(sc_other)), float(np.max(sc_other))
        r_direct = float(np.corrcoef(f_harm[best_ih], f_other_mean)[0, 1])
        if r_b >= 0.58 and r_o >= 0.54 and abs(lag_b - lag_o) > 30 and r_direct < 0.35:
            residual_harmonic_conflict = True
            residual_lag_info = {
                "dominant_h": best_h,
                "dominant_lag_s": lag_b,
                "dominant_r": round(r_b, 4),
                "other_harmonics": [int(harmonics[i]) for i in other_active],
                "other_lag_s": lag_o,
                "other_r": round(r_o, 4),
                "direct_corr": round(r_direct, 4),
            }

    # 2. Same-Band Dual-Ridge / Beating Detector (Attacks c1, c2, b3 when all harmonics are mixed)
    # In a clean recording, after masking the primary ENF ridge, the secondary peak inside
    # [50h - 0.12, 50h + 0.12] Hz is just background noise and does NOT correlate with a
    # second reference timestamp nor sustain high in-band SNR across multiple harmonics.
    med_sec_snr_h = np.median(sec_snr_db_harm, axis=1)
    best_sec_snr_db = float(med_sec_snr_h[best_ih])
    # Weighted secondary trace across top harmonics
    top_h_idx = np.argsort(med_snr_h)[::-1][: min(3, n_h)]
    w_sec = np.maximum(0.1, med_sec_snr_h[top_h_idx])[:, None]
    f_sec_combined = np.sum(w_sec * sec_f_harm[top_h_idx], axis=0) / np.sum(w_sec)

    inband_double_enf = False
    sec_ref_r = 0.0
    sec_ref_lag = -1
    if ref_f is not None and len(ref_f) >= n_frames + 10:
        sc_prim = _fast_sliding_ncc(f_harm[best_ih], ref_f)
        prim_lag = int(np.argmax(sc_prim))
        prim_r = float(sc_prim[prim_lag])

        sc_sec = _fast_sliding_ncc(f_sec_combined, ref_f)
        # Mask +/- 60s around primary lag
        lo_m = max(0, prim_lag - 60)
        hi_m = min(len(sc_sec), prim_lag + 61)
        sc_sec_masked = sc_sec.copy()
        sc_sec_masked[lo_m:hi_m] = -1.0
        sec_ref_lag = int(np.argmax(sc_sec_masked))
        sec_ref_r = float(sc_sec_masked[sec_ref_lag])

        # Also check if primary correlation spectrum itself has TWO strong distinct peaks
        # (because a 0 dB or +3 dB mixture of two traces correlates with BOTH true and spoof lags!)
        sc_prim_masked = sc_prim.copy()
        sc_prim_masked[lo_m:hi_m] = -1.0
        prim_second_lag = int(np.argmax(sc_prim_masked))
        prim_second_r = float(sc_prim_masked[prim_second_lag])

        # When two traces are mixed (c1, c2, b3), either:
        # (a) The secondary in-band ridge has elevated SNR (>= 6.2 dB) and correlates with the
        #     second trace (sec_ref_r >= 0.44), OR
        # (b) Both primary and secondary peaks in sc_prim are strong (prim_r >= 0.52 and prim_second_r >= 0.48)
        #     while best_sec_snr_db >= 5.8 dB!
        if (best_sec_snr_db >= 6.0 and sec_ref_r >= 0.44) or (
            best_sec_snr_db >= 5.5 and prim_r >= 0.50 and prim_second_r >= 0.47
        ):
            inband_double_enf = True

    # 3. Wideband Pitch-Shift / Sample-Rate Scaling Detector (Attacks d7a, d7b)
    x_1k = harm_diag["x_proc_1khz"]
    fs_1k = harm_diag["fs_proc"]
    nperseg = min(len(x_1k), int(round(10.0 * fs_1k)))
    nfft_p = max(65536, int(2 ** math.ceil(math.log2(max(16, nperseg * 4)))))
    freqs_p, psd_p = signal.welch(x_1k, fs=fs_1k, window="hann", nperseg=nperseg, noverlap=nperseg // 2, nfft=nfft_p)
    df_p = float(freqs_p[1] - freqs_p[0])
    bg_p = median_filter(psd_p, size=int(round(4.0 / df_p)) | 1, mode="nearest") / math.log(2.0) + 1e-30
    snr_spec = 10.0 * np.log10((psd_p + 1e-30) / bg_p)

    # Scan candidate fundamental f0 in [48.50, 51.50] Hz in 0.005 Hz steps across h=2,3,4,5,6
    f0_scan = np.arange(48.50, 51.505, 0.005)
    comb_scores = np.zeros_like(f0_scan)
    scan_h = [h for h in (2, 3, 4, 5, 6) if h * 52.0 < 0.48 * fs_1k]
    for h in scan_h:
        idx_scan = np.clip(np.round((h * f0_scan) / df_p).astype(int), 0, len(snr_spec) - 1)
        comb_scores += np.maximum(0.0, snr_spec[idx_scan] - 3.5)
    comb_scores /= max(1, len(scan_h))

    best_f0_idx = int(np.argmax(comb_scores))
    best_f0_hz = float(f0_scan[best_f0_idx])
    best_comb_snr = float(comb_scores[best_f0_idx])
    nom_idx = int(np.argmin(np.abs(f0_scan - nominal_hz)))
    nom_comb_snr = float(comb_scores[nom_idx])

    pitch_offset_hz = best_f0_hz - nominal_hz
    pitch_shift_pct = 100.0 * (pitch_offset_hz / nominal_hz)
    # Trigger if a shifted harmonic comb (|offset| >= 0.18 Hz, i.e. >= 0.36%) is strong and clearly beats 50.0 Hz
    pitch_shift_detected = bool(
        abs(pitch_offset_hz) >= 0.18
        and best_comb_snr >= 5.5
        and (best_comb_snr - nom_comb_snr) >= 3.0
    )

    triggered = bool(
        inter_harmonic_conflict
        or residual_harmonic_conflict
        or inband_double_enf
        or pitch_shift_detected
    )

    if lag_conflict_pair is not None:
        ha, hb, la, lb, ra, rb = lag_conflict_pair
        reasons.append(
            f"G3_HARMONIC_LAG_CONFLICT: Coherent harmonics h={ha} and h={hb} match different reference "
            f"timestamps (lag_{ha}={la}s [r={ra:.3f}] vs lag_{hb}={lb}s [r={rb:.3f}]), proving multi-trace tampering."
        )
    elif inter_harmonic_conflict and conflicting_pair is not None:
        ha, hb, rab = conflicting_pair
        reasons.append(
            f"G3_INTER_HARMONIC_INCONSISTENCY: Coherent harmonics h={ha} and h={hb} have incompatible "
            f"trajectories (r={rab:.3f} < {corr_conflict_thresh:.2f})."
        )
    if residual_harmonic_conflict and residual_lag_info is not None:
        reasons.append(
            f"G3_RESIDUAL_HARMONIC_SPOOF_CONFLICT: Dominant harmonic h={residual_lag_info['dominant_h']} "
            f"matches lag={residual_lag_info['dominant_lag_s']}s (r={residual_lag_info['dominant_r']:.3f}), "
            f"contradicting background harmonics {residual_lag_info['other_harmonics']} which match "
            f"lag={residual_lag_info['other_lag_s']}s (r={residual_lag_info['other_r']:.3f})."
        )
    if inband_double_enf:
        reasons.append(
            f"G3_INBAND_DOUBLE_ENF_DETECTED: Secondary narrowband ENF ridge detected inside harmonic "
            f"passband (sec_snr={best_sec_snr_db:.1f} dB, secondary lag={sec_ref_lag}s with r={sec_ref_r:.3f})."
        )
    if pitch_shift_detected:
        reasons.append(
            f"G3_PITCH_SHIFT_DETECTED: Harmonic comb shifted to f0={best_f0_hz:.3f} Hz "
            f"({pitch_shift_pct:+.2f}%, comb excess SNR={best_comb_snr:.1f} dB vs {nom_comb_snr:.1f} dB at 50 Hz)."
        )

    return {
        "guard_id": "G3",
        "name": "harmonic_consistency_and_pitch_guard",
        "triggered": triggered,
        "inter_harmonic_conflict": inter_harmonic_conflict,
        "residual_harmonic_conflict": residual_harmonic_conflict,
        "inband_double_enf": inband_double_enf,
        "pitch_shift_detected": pitch_shift_detected,
        "coherent_harmonics": [int(harmonics[i]) for i in coherent_indices],
        "min_pair_corr": round(min_pair_corr, 4) if len(coherent_indices) >= 2 else None,
        "per_harmonic_ref_matches": per_h_ref_matches,
        "residual_lag_info": residual_lag_info,
        "best_sec_snr_db": round(best_sec_snr_db, 2),
        "sec_ref_r": round(sec_ref_r, 4),
        "estimated_f0_hz": round(best_f0_hz, 4),
        "pitch_shift_pct": round(pitch_shift_pct, 3),
        "reasons": reasons,
    }


# =============================================================================
# Guard G4: Multi-Segment Splice, Concatenation & Drift Detector
# =============================================================================
def guard_g4_multifragment_splice_and_drift(
    f_trace: np.ndarray,
    t_trace: np.ndarray,
    ref_f: np.ndarray,
    best_global_lag_s: int,
    best_global_r: float,
    audio: Optional[np.ndarray] = None,
    fs: float = 8000.0,
    seg_len_s: int = 60,
    seg_stride_s: int = 30,
    mode: str = "v2_calibrated",
) -> Dict[str, Any]:
    """
    G4: Detect spliced concatenations (50/50 f1, 70/30 f2, and 120s-60s-120s middle
    insertions f3a/f3b that defeat 2-piece split-half gates) as well as resampling
    or WSOLA time-stretch drift (d5b, d6a, d6b).
    """
    f_q = np.asarray(f_trace, dtype=np.float64).ravel()
    L = len(f_q)
    reasons: List[str] = []

    if L < 90 or len(ref_f) < L + 10:
        return {
            "guard_id": "G4",
            "name": "multi_segment_splice_and_drift_guard",
            "triggered": False,
            "reasons": [],
        }

    # Build sliding sub-segments of length `seg_len_s` (60s) with stride `seg_stride_s` (30s)
    starts = list(range(0, L - seg_len_s + 1, seg_stride_s))
    if starts[-1] != L - seg_len_s and (L - seg_len_s - starts[-1]) >= 15:
        starts.append(L - seg_len_s)

    segments_info: List[Dict[str, Any]] = []
    for s_idx in starts:
        sub_q = f_q[s_idx : s_idx + seg_len_s]
        exp_lag = best_global_lag_s + s_idx

        # Local correlation at expected lag (allowing +/- 2s jitter)
        best_loc_r = -1.0
        for d in range(-2, 3):
            cand_l = exp_lag + d
            if 0 <= cand_l and cand_l + seg_len_s <= len(ref_f):
                sub_r = ref_f[cand_l : cand_l + seg_len_s]
                valid = np.isfinite(sub_q) & np.isfinite(sub_r)
                if np.sum(valid) >= 20 and np.std(sub_q[valid]) > 1e-6 and np.std(sub_r[valid]) > 1e-6:
                    rc = float(np.corrcoef(sub_q[valid], sub_r[valid])[0, 1])
                    if rc > best_loc_r:
                        best_loc_r = rc

        # Independent 24-hour search for this 60s sub-segment
        scores_sub = _fast_sliding_ncc(sub_q, ref_f)
        indep_lag = int(np.argmax(scores_sub))
        indep_r = float(scores_sub[indep_lag])
        lag_dev_s = indep_lag - exp_lag

        segments_info.append(
            {
                "start_s": int(s_idx),
                "end_s": int(s_idx + seg_len_s),
                "expected_lag_s": int(exp_lag),
                "local_r": round(best_loc_r, 4),
                "indep_best_lag_s": int(indep_lag),
                "indep_best_r": round(indep_r, 4),
                "lag_deviation_s": int(lag_dev_s),
            }
        )

    local_rs = np.array([seg["local_r"] for seg in segments_info], dtype=np.float64)
    indep_rs = np.array([seg["indep_best_r"] for seg in segments_info], dtype=np.float64)
    lag_devs = np.array([seg["lag_deviation_s"] for seg in segments_info], dtype=np.float64)

    max_local_r = float(np.max(local_rs))
    min_local_r = float(np.min(local_rs))

    # 1. Splice Detection:
    # A clip is spliced if at least one sub-segment strongly supports the primary alignment
    # (max_local_r >= 0.60), while another sub-segment:
    #   (a) Fails local correlation at the primary alignment (local_r < 0.18) AND independently
    #       matches a different timestamp (|lag_dev| > 25s) with high correlation (indep_r >= 0.62)
    #       and large correlation gain (indep_r - local_r >= 0.45), OR
    #   (b) Two non-overlapping sub-segments both have very strong independent matches
    #       (indep_r >= 0.68) at incompatible timeline offsets (|lag_dev_i - lag_dev_j| >= 25s)
    #       while at least one has local_r < 0.25.
    alt_match_thresh = 0.56 if mode == "v1_naive" else 0.63
    local_drop_thresh = 0.28 if mode == "v1_naive" else 0.18

    spliced_segments = [
        seg
        for seg in segments_info
        if (
            max_local_r >= 0.58
            and seg["local_r"] < local_drop_thresh
            and abs(seg["lag_deviation_s"]) > 25
            and seg["indep_best_r"] >= alt_match_thresh
            and (seg["indep_best_r"] - seg["local_r"]) >= 0.42
        )
    ]

    # Also check shift-splice (e.g. f3b where first segment has lag_dev ~ 0 and last segment has lag_dev ~ -60s)
    strong_segs = [seg for seg in segments_info if seg["indep_best_r"] >= 0.65]
    shift_splice = False
    if len(strong_segs) >= 2:
        devs = [seg["lag_deviation_s"] for seg in strong_segs]
        if (max(devs) - min(devs)) >= 30 and min_local_r < 0.22:
            shift_splice = True

    splice_detected = bool(len(spliced_segments) > 0 or shift_splice)

    # 2. Time-Stretch & Clock-Drift Detection (d5b, d6a, d6b)
    # Check WSOLA time-stretch artifacts on audio if available
    wsola_detected = False
    wsola_info: Dict[str, Any] = {}
    if audio is not None and len(audio) >= int(10 * fs):
        try:
            from work.W13.speed_check import _compute_wsola_diagnostics
            x_1k = signal.resample_poly(audio - np.mean(audio), 1, max(1, int(round(fs / 1000.0)))) if fs > 1200 else (audio - np.mean(audio))
            fs_1k = float(fs) / max(1, int(round(fs / 1000.0))) if fs > 1200 else float(fs)
            nfft_w = 65536
            freqs_w, psd_w = signal.welch(x_1k, fs=fs_1k, nperseg=min(len(x_1k), int(10 * fs_1k)), nfft=nfft_w)
            wsola_info = _compute_wsola_diagnostics(x_1k, fs_1k, 50.0, [2, 3, 4, 5, 6], psd_w, freqs_w)
            wsola_detected = bool(wsola_info.get("suspected_time_stretch", False))
        except Exception:
            wsola_detected = False

    # Check linear lag drift across sub-segments (when segments match progressively shifting lags)
    drift_detected = False
    drift_slope_ppm = 0.0
    valid_drift_segs = [seg for seg in segments_info if seg["indep_best_r"] >= 0.55 and abs(seg["lag_deviation_s"]) <= 90]
    if len(valid_drift_segs) >= 4:
        t_s = np.array([seg["start_s"] for seg in valid_drift_segs], dtype=np.float64)
        d_s = np.array([seg["lag_deviation_s"] for seg in valid_drift_segs], dtype=np.float64)
        if np.ptp(t_s) >= 120.0:
            slope, _ = np.polyfit(t_s, d_s, 1)
            drift_slope_ppm = float(slope * 1e6)
            total_drift_s = abs(slope * float(L))
            # If total drift across the clip exceeds 6s and r2 of linear drift is high
            corr_lin = abs(float(np.corrcoef(t_s, d_s)[0, 1])) if np.std(d_s) > 1e-3 else 0.0
            if total_drift_s >= 6.0 and corr_lin >= 0.80 and not splice_detected:
                drift_detected = True

    triggered = bool(splice_detected or wsola_detected or drift_detected)
    if splice_detected:
        reasons.append(
            f"G4_SPLICE_CONCATENATION_DETECTED: Sub-segment correlation drops to min_local_r={min_local_r:.3f} "
            f"(while clean segments reach {max_local_r:.3f}), and anomalous sub-segment(s) independently match "
            f"different timeline offset(s) {[s['indep_best_lag_s'] for s in spliced_segments]}."
        )
    if wsola_detected:
        reasons.append(
            f"G4_WSOLA_TIMESTRETCH_DETECTED: Pitch-preserving time-stretch artifacts detected around ENF harmonics "
            f"(sideband ratio={wsola_info.get('sideband_to_carrier_ratio', 0.0):.4f}, "
            f"phase instability={wsola_info.get('phase_instability_hz', 0.0):.4f} Hz)."
        )
    if drift_detected:
        reasons.append(
            f"G4_TIMELINE_DRIFT_DETECTED: Progressive lag drift of {drift_slope_ppm:+.0f} ppm across sub-segments."
        )

    return {
        "guard_id": "G4",
        "name": "multi_segment_splice_and_drift_guard",
        "triggered": triggered,
        "splice_detected": splice_detected,
        "wsola_timestretch_detected": wsola_detected,
        "drift_detected": drift_detected,
        "max_local_r": round(max_local_r, 4),
        "min_local_r": round(min_local_r, 4),
        "n_spliced_segments": len(spliced_segments),
        "segments": segments_info,
        "wsola_diagnostics": wsola_info,
        "reasons": reasons,
    }


# =============================================================================
# Guard G5: Minimum Duration & Look-Elsewhere Uniqueness Guard
# =============================================================================
def guard_g5_duration_and_uniqueness(
    f_trace: np.ndarray,
    match_result: Dict[str, Any],
    min_duration_s: float = 60.0,
    min_margin: float = 0.055,
    max_p_emp: float = 0.015,
) -> Dict[str, Any]:
    """
    G5: Block short-duration clips (Attack e: 10s, 20s, 30s) and ambiguous peaks
    from issuing `MATCH_SUPPORTED` over a 24-hour search window.
    """
    diag = match_result.get("diagnostics", {})
    uniq = match_result.get("uniqueness", {})
    null_info = match_result.get("null", {})

    valid_dur_s = float(diag.get("valid_duration_s", np.sum(np.isfinite(f_trace))))
    margin = float(uniq.get("margin_vs_second", 0.0))
    p_emp = float(null_info.get("p_empirical", 1.0))

    short_clip = bool(valid_dur_s < min_duration_s)
    low_margin = bool(margin < min_margin or p_emp > max_p_emp)
    triggered = bool(short_clip or low_margin)

    reasons = []
    if short_clip:
        reasons.append(
            f"G5_SHORT_DURATION_BLOCKED: Valid trace duration {valid_dur_s:.1f}s is below the "
            f"{min_duration_s:.0f}s minimum required to prevent 24-hour look-elsewhere false matches."
        )
    if low_margin and not short_clip:
        reasons.append(
            f"G5_UNIQUENESS_OR_NULL_BLOCKED: Peak uniqueness margin ({margin:.4f} vs {min_margin:.3f}) "
            f"or empirical p-value ({p_emp:.4g} vs {max_p_emp:.3g}) is insufficient for unique dating."
        )

    return {
        "guard_id": "G5",
        "name": "duration_and_uniqueness_guard",
        "triggered": triggered,
        "short_clip_blocked": short_clip,
        "low_margin_blocked": low_margin,
        "valid_duration_s": round(valid_dur_s, 2),
        "margin_vs_second": round(margin, 4),
        "p_empirical": round(p_emp, 6),
        "reasons": reasons,
    }


# =============================================================================
# Guard G6: Cross-Modal Audio-vs-Video ENF Agreement Guard
# =============================================================================
def guard_g6_audio_video_agreement(
    audio_trace: np.ndarray,
    video_trace: Optional[np.ndarray],
    audio_lag_s: int,
    video_lag_s: Optional[int],
    audio_r: float,
    video_r: Optional[float],
    max_lag_diff_s: int = 5,
    min_cross_corr: float = 0.35,
) -> Dict[str, Any]:
    """
    G6: When both audio ENF and rolling-shutter video ENF traces are available
    for a clip, verify that they sense the same electrical environment:
      1. Never multiply confidences (Scientific Ground Truth #3).
      2. Require matched reference timestamps to agree within `max_lag_diff_s` (5s)
         and direct zero-lag trace correlation `r(f_A, f_V) >= min_cross_corr` (0.35).
    """
    if video_trace is None or video_lag_s is None or video_r is None:
        return {
            "guard_id": "G6",
            "name": "audio_video_agreement_guard",
            "triggered": False,
            "applicable": False,
            "reasons": [],
        }

    fa = np.asarray(audio_trace, dtype=np.float64).ravel()
    fv = np.asarray(video_trace, dtype=np.float64).ravel()
    n = min(len(fa), len(fv))
    if n >= 10:
        valid = np.isfinite(fa[:n]) & np.isfinite(fv[:n])
        if np.sum(valid) >= 10 and np.std(fa[:n][valid]) > 1e-6 and np.std(fv[:n][valid]) > 1e-6:
            r_av = float(np.corrcoef(fa[:n][valid], fv[:n][valid])[0, 1])
            rmse_av_mhz = float(np.sqrt(np.mean((fa[:n][valid] - fv[:n][valid]) ** 2)) * 1000.0)
        else:
            r_av = 0.0
            rmse_av_mhz = 999.0
    else:
        r_av = 0.0
        rmse_av_mhz = 999.0

    lag_diff_s = abs(int(audio_lag_s) - int(video_lag_s))
    disagreement = bool(lag_diff_s > max_lag_diff_s or r_av < min_cross_corr)

    reasons = []
    if disagreement:
        reasons.append(
            f"G6_AUDIO_VIDEO_DISAGREEMENT: Audio ENF matches lag={audio_lag_s}s (r={audio_r:.3f}) "
            f"while Video rolling-shutter ENF matches lag={video_lag_s}s (r={video_r:.3f}), "
            f"discrepancy={lag_diff_s}s, direct trace correlation r(A,V)={r_av:.3f} (< {min_cross_corr:.2f}). "
            f"Indicates cross-modal audio replacement or spoofing."
        )

    return {
        "guard_id": "G6",
        "name": "audio_video_agreement_guard",
        "triggered": disagreement,
        "applicable": True,
        "audio_lag_s": int(audio_lag_s),
        "video_lag_s": int(video_lag_s),
        "lag_diff_s": int(lag_diff_s),
        "cross_modal_r": round(r_av, 4),
        "cross_modal_rmse_mhz": round(rmse_av_mhz, 2),
        "reasons": reasons,
    }


def evaluate_all_guards(
    audio: np.ndarray,
    fs: float,
    f_trace: np.ndarray,
    t_trace: np.ndarray,
    match_result: Dict[str, Any],
    ref_f: Optional[np.ndarray] = None,
    harm_diag: Optional[Dict[str, Any]] = None,
    video_trace: Optional[np.ndarray] = None,
    video_lag_s: Optional[int] = None,
    video_r: Optional[float] = None,
    nominal_hz: float = 50.0,
    mode: str = "v2_calibrated",
) -> Dict[str, Any]:
    """
    Run all 6 deterministic guards (`G1`-`G6`) and compute the guarded GhostClock
    decision status (`MATCH_SUPPORTED`, `INCONCLUSIVE`, or `MATERIAL_DISCREPANCY_REVIEW`).
    """
    if harm_diag is None:
        harm_diag = extract_harmonic_diagnostics(audio, fs, nominal_hz=nominal_hz)

    best_lag_s = int(match_result.get("best", {}).get("start_utc", 0))
    best_r = float(match_result.get("best", {}).get("score", 0.0))
    base_status = str(match_result.get("status", "INCONCLUSIVE"))

    g1 = guard_g1_notch_and_suppression(audio, fs, nominal_hz=nominal_hz, mode=mode)
    g2 = guard_g2_too_clean_injector(harm_diag, mode=mode)
    g3 = guard_g3_harmonic_consistency_and_pitch(harm_diag, audio, fs, ref_f=ref_f, nominal_hz=nominal_hz, mode=mode)
    g4 = (
        guard_g4_multifragment_splice_and_drift(
            f_trace, t_trace, ref_f, best_lag_s, best_r, audio=audio, fs=fs, mode=mode
        )
        if ref_f is not None
        else {"guard_id": "G4", "triggered": False, "reasons": []}
    )
    g5 = guard_g5_duration_and_uniqueness(f_trace, match_result)
    g6 = guard_g6_audio_video_agreement(f_trace, video_trace, best_lag_s, video_lag_s, best_r, video_r)

    guards_dict = {"G1": g1, "G2": g2, "G3": g3, "G4": g4, "G5": g5, "G6": g6}
    triggered_ids = [gid for gid, g in guards_dict.items() if g.get("triggered", False)]
    all_reasons: List[str] = []
    for gid in triggered_ids:
        all_reasons.extend(guards_dict[gid].get("reasons", []))

    # Decision policy enforcement with guards:
    # - If base_status was already MATERIAL_DISCREPANCY_REVIEW (e.g. claimed_start_utc mismatch),
    #   keep MATERIAL_DISCREPANCY_REVIEW unless G5 says signal is too short/weak to support any claim.
    # - If G2 (synthetic injection), G3 (harmonic conflict / double ENF / pitch shift),
    #   G4 (splice / time-stretch), or G6 (audio-video disagreement) triggers, escalate to
    #   MATERIAL_DISCREPANCY_REVIEW (human forensic review required) or block MATCH_SUPPORTED!
    # - If G1 (notch / heavy suppression) or G5 (short duration / low uniqueness) triggers,
    #   override MATCH_SUPPORTED -> INCONCLUSIVE (or MATERIAL_DISCREPANCY_REVIEW if notch filter detected).
    guarded_status = base_status
    if "G5" in triggered_ids:
        guarded_status = "INCONCLUSIVE"
    elif any(gid in triggered_ids for gid in ("G2", "G3", "G4", "G6")):
        guarded_status = "MATERIAL_DISCREPANCY_REVIEW"
    elif "G1" in triggered_ids:
        if g1.get("notch_detected", False):
            guarded_status = "MATERIAL_DISCREPANCY_REVIEW"
        else:
            guarded_status = "INCONCLUSIVE"

    return {
        "base_status": base_status,
        "guarded_status": guarded_status,
        "any_guard_triggered": len(triggered_ids) > 0,
        "any_anomaly_guard_triggered": any(gid in triggered_ids for gid in ("G1", "G2", "G3", "G4", "G6")),
        "triggered_guards": triggered_ids,
        "guard_reasons": all_reasons,
        "guards": guards_dict,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run W14 Deterministic Adversarial Guards on an audio file")
    parser.add_argument("--in", dest="in_path", required=True, help="Input audio path")
    parser.add_argument("--out", dest="out_path", required=True, help="Output JSON path")
    parser.add_argument("--nominal", type=float, default=50.0, help="Nominal grid frequency (Hz)")
    args = parser.parse_args()

    audio, fs = sf.read(args.in_path, dtype="float64")
    if audio.ndim > 1:
        audio = np.mean(audio, axis=1)
    harm_diag = extract_harmonic_diagnostics(audio, float(fs), nominal_hz=args.nominal)
    f_trace = harm_diag["f_harm"][1] if len(harm_diag["harmonics"]) >= 2 else harm_diag["f_harm"][0]
    dummy_match = {
        "best": {"start_utc": 0, "score": 0.9},
        "diagnostics": {"valid_duration_s": float(len(f_trace))},
        "uniqueness": {"margin_vs_second": 0.2},
        "null": {"p_empirical": 0.001},
        "status": "MATCH_SUPPORTED",
    }
    res = evaluate_all_guards(
        audio=audio,
        fs=float(fs),
        f_trace=f_trace,
        t_trace=harm_diag["t"],
        match_result=dummy_match,
        harm_diag=harm_diag,
        nominal_hz=args.nominal,
    )
    out_p = Path(args.out_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(f"[W14 Guards] triggered={res['triggered_guards']} | guarded_status={res['guarded_status']}")


if __name__ == "__main__":
    main()
