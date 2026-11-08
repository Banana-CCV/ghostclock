#!/usr/bin/env python3
"""
Diagnose the lag between W06 extracted ENF trace and H1_ref reference trace:
1. Synthetic FM sinusoid test: verify whether W06's pipeline (ffmpeg decode,
   sosfiltfilt anti-alias, resample_poly, sosfiltfilt bandpass, STFT window centers)
   introduces any group delay or time shift on a known ground-truth FM signal.
2. Direct unfiltered `scipy.signal.stft` on raw 8000 Hz `H1/003.wav` (no downsampling,
   no bandpass filter, no W06 code) vs `H1_ref/003_ref.wav`: check whether the ~4 s
   lag on `003.wav` is intrinsic to the raw WAV pair in ENF-WHU or from DSP.
3. Measure the optimal cross-correlation lag across all Dev H1 recordings (`lag_s` in
   [-15, +15] s) and compare zero-lag vs lag-aligned r and RMSE.
"""

from __future__ import annotations

from pathlib import Path
import json
import numpy as np
import soundfile as sf
from scipy.signal import stft

from audio_enf import extract_audio_enf_detailed, extract_reference_enf, load_config
from evaluate_dev import load_or_build_dev_split

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = REPO_ROOT / "datasets" / "raw" / "enf-whu" / "repo" / "ENF-WHU-Dataset"
WORK_DIR = Path(__file__).resolve().parent


def test_synthetic_zero_delay() -> dict:
    """Synthesize a known FM signal at fs=8000 Hz and check W06's exact lag."""
    fs = 8000.0
    dur = 300.0
    n_samples = int(fs * dur)
    t_sample = np.arange(n_samples, dtype=np.float64) / fs

    # Known time-varying fundamental frequency f0(t) with non-periodic random walk / multi-sine
    f0_true = (
        50.0
        + 0.030 * np.sin(2.0 * np.pi * t_sample / 47.0)
        + 0.020 * np.cos(2.0 * np.pi * t_sample / 31.0)
        + 0.015 * np.sin(2.0 * np.pi * t_sample / 19.0)
    )
    phase = 2.0 * np.pi * np.cumsum(f0_true) / fs
    sig = 0.5 * np.sin(2.0 * phase) + 0.4 * np.sin(4.0 * phase) + 0.3 * np.sin(6.0 * phase)

    syn_path = WORK_DIR / "scratch_syn_fm.wav"
    sf.write(str(syn_path), sig.astype(np.float32), int(fs))

    cfg = load_config()
    res = extract_audio_enf_detailed(syn_path, cfg)
    tw = res["t"]
    fw = res["f_raw"]

    # Ground-truth window-center frequency
    f_true_centers = (
        50.0
        + 0.030 * np.sin(2.0 * np.pi * tw / 47.0)
        + 0.020 * np.cos(2.0 * np.pi * tw / 31.0)
        + 0.015 * np.sin(2.0 * np.pi * tw / 19.0)
    )

    x = fw - np.mean(fw)
    y = f_true_centers - np.mean(f_true_centers)
    lags = range(-6, 7)
    lag_corrs = {
        int(L): round(float(np.corrcoef(np.roll(x, L)[10:-10], y[10:-10])[0, 1]), 6)
        for L in lags
    }
    best_lag = max(lag_corrs, key=lambda k: lag_corrs[k])
    rmse_lag0 = float(np.sqrt(np.mean((fw - f_true_centers) ** 2)) * 1000.0)
    return {
        "best_lag_s": best_lag,
        "r_at_lag_0": lag_corrs[0],
        "rmse_at_lag_0_mhz": round(rmse_lag0, 4),
        "corr_by_lag_s": lag_corrs,
    }


def test_raw_unfiltered_stft_on_003() -> dict:
    """Run scipy.signal.stft directly on raw 003.wav (200 Hz harmonic) vs 003_ref.wav (50 Hz)."""
    raw_h1, fs1 = sf.read(str(DATASET_DIR / "H1" / "003.wav"), dtype="float64")
    if raw_h1.ndim > 1:
        raw_h1 = raw_h1[:, 0]
    raw_ref, fs_ref = sf.read(str(DATASET_DIR / "H1_ref" / "003_ref.wav"), dtype="float64")
    if raw_ref.ndim > 1:
        raw_ref = raw_ref[:, 0]

    win_s, hop_s = 16.0, 1.0

    # Raw STFT on 003_ref.wav around 50 Hz
    nper_r, nhop_r = int(win_s * fs_ref), int(hop_s * fs_ref)
    fr, tr, Zr = stft(raw_ref, fs=fs_ref, window="hann", nperseg=nper_r, noverlap=nper_r - nhop_r, nfft=nper_r * 8, boundary=None, padded=False)
    Pr = np.abs(Zr) ** 2
    br = (fr > 49.8) & (fr < 50.2)
    f_ref_raw = fr[br][Pr[br].argmax(0)]

    # Raw STFT on 003.wav around 200 Hz (4th harmonic, no filter, no downsampling)
    nper_1, nhop_1 = int(win_s * fs1), int(hop_s * fs1)
    f1, t1, Z1 = stft(raw_h1, fs=fs1, window="hann", nperseg=nper_1, noverlap=nper_1 - nhop_1, nfft=nper_1 * 4, boundary=None, padded=False)
    P1 = np.abs(Z1) ** 2
    b1 = (f1 > 4 * 49.8) & (f1 < 4 * 50.2)
    f_h1_raw = f1[b1][P1[b1].argmax(0)] / 4.0

    n = min(len(f_ref_raw), len(f_h1_raw))
    x = f_h1_raw[:n] - np.mean(f_h1_raw[:n])
    y = f_ref_raw[:n] - np.mean(f_ref_raw[:n])
    lags = range(-8, 9)
    lag_corrs = {
        int(L): round(float(np.corrcoef(np.roll(x, L)[15:-15], y[15:-15])[0, 1]), 5)
        for L in lags
    }
    best_lag = max(lag_corrs, key=lambda k: lag_corrs[k])
    return {
        "best_lag_s": best_lag,
        "r_at_lag_0": lag_corrs[0],
        "r_at_best_lag": lag_corrs[best_lag],
        "corr_by_lag_s": lag_corrs,
        "duration_h1_s": round(len(raw_h1) / fs1, 4),
        "duration_ref_s": round(len(raw_ref) / fs_ref, 4),
    }


def analyze_dev_lag_distribution() -> dict:
    """Measure the lag distribution across all Dev H1 files."""
    split_info = load_or_build_dev_split()
    h1_dev_ids = split_info["h1_dev"]
    cfg = load_config()
    cfg["decode_via_ffmpeg"] = False

    per_file_lags = []
    for cid in h1_dev_ids:
        wav_path = DATASET_DIR / "H1" / f"{cid}.wav"
        ref_path = DATASET_DIR / "H1_ref" / f"{cid}_ref.wav"
        res = extract_audio_enf_detailed(wav_path, cfg)
        _, f_ref = extract_reference_enf(ref_path, window_s=cfg["window_s"], hop_s=cfg["hop_s"])

        fw = res["f_raw"]
        n = min(len(fw), len(f_ref))
        fw = fw[:n]
        fr = f_ref[:n]
        x = fw - np.mean(fw)
        y = fr - np.mean(fr)

        lags = range(-15, 16)
        best_l = 0
        best_r = -2.0
        r_0 = float(np.corrcoef(x, y)[0, 1])
        rmse_0 = float(np.sqrt(np.mean((fw - fr) ** 2)) * 1000.0)

        for L in lags:
            if L < 0:
                xs, ys = x[-L:], y[: n + L]
                fws, frs = fw[-L:], fr[: n + L]
            elif L > 0:
                xs, ys = x[: n - L], y[L:]
                fws, frs = fw[: n - L], fr[L:]
            else:
                xs, ys = x, y
                fws, frs = fw, fr
            if len(xs) < 20:
                continue
            r_l = float(np.corrcoef(xs, ys)[0, 1])
            if r_l > best_r:
                best_r = r_l
                best_l = int(L)
                best_rmse = float(np.sqrt(np.mean((fws - frs) ** 2)) * 1000.0)

        per_file_lags.append({
            "id": cid,
            "best_lag_s": best_l,
            "r_lag0": round(r_0, 4),
            "r_best_lag": round(best_r, 4),
            "rmse_lag0_mhz": round(rmse_0, 3),
            "rmse_best_lag_mhz": round(best_rmse, 3),
        })

    # Filter to high-confidence recordings (r_best_lag >= 0.70) where lag is meaningful
    valid_lags = [p["best_lag_s"] for p in per_file_lags if p["r_best_lag"] >= 0.70]
    abs_lags = np.abs(valid_lags)
    r0_all = [p["r_lag0"] for p in per_file_lags]
    rb_all = [p["r_best_lag"] for p in per_file_lags]
    rmse0_all = [p["rmse_lag0_mhz"] for p in per_file_lags]
    rmseb_all = [p["rmse_best_lag_mhz"] for p in per_file_lags]

    from collections import Counter
    hist_counts = dict(sorted(Counter(valid_lags).items()))

    return {
        "n_dev_h1": len(h1_dev_ids),
        "n_meaningful_lag_r_ge_0_70": len(valid_lags),
        "lag_s_histogram_on_r_ge_0_70": {str(k): int(v) for k, v in hist_counts.items()},
        "median_lag_s": float(np.median(valid_lags)) if valid_lags else 0.0,
        "mean_lag_s": round(float(np.mean(valid_lags)), 3) if valid_lags else 0.0,
        "std_lag_s": round(float(np.std(valid_lags)), 3) if valid_lags else 0.0,
        "median_abs_lag_s": float(np.median(abs_lags)) if len(abs_lags) else 0.0,
        "p90_abs_lag_s": float(np.percentile(abs_lags, 90)) if len(abs_lags) else 0.0,
        "frac_within_1s": round(float(np.mean(abs_lags <= 1)), 4) if len(abs_lags) else 0.0,
        "frac_within_2s": round(float(np.mean(abs_lags <= 2)), 4) if len(abs_lags) else 0.0,
        "frac_within_5s": round(float(np.mean(abs_lags <= 5)), 4) if len(abs_lags) else 0.0,
        "zero_lag_median_r": round(float(np.median(r0_all)), 4),
        "best_lag_median_r": round(float(np.median(rb_all)), 4),
        "zero_lag_median_rmse_mhz": round(float(np.median(rmse0_all)), 3),
        "best_lag_median_rmse_mhz": round(float(np.median(rmseb_all)), 3),
        "per_file_lags": per_file_lags,
    }


def main() -> None:
    print("1. Testing synthetic FM signal for pipeline group delay / window-center alignment...")
    syn_res = test_synthetic_zero_delay()
    print("   Synthetic FM result:", json.dumps(syn_res, indent=2))

    print("2. Testing raw unfiltered scipy.signal.stft on H1/003.wav vs H1_ref/003_ref.wav...")
    raw_003_res = test_raw_unfiltered_stft_on_003()
    print("   Raw 003.wav STFT result:", json.dumps(raw_003_res, indent=2))

    print("3. Analyzing per-file lag distribution across all Dev H1 recordings...")
    dev_lag_res = analyze_dev_lag_distribution()
    summary_print = {k: v for k, v in dev_lag_res.items() if k != "per_file_lags"}
    print("   Dev H1 lag summary:", json.dumps(summary_print, indent=2))

    out = {
        "synthetic_fm_zero_delay_verification": syn_res,
        "raw_unfiltered_stft_003_verification": raw_003_res,
        "dev_h1_lag_distribution": dev_lag_res,
    }
    out_path = WORK_DIR / "lag_diagnosis.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"Saved lag diagnosis to {out_path}")


if __name__ == "__main__":
    main()
