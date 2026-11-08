"""
Quick verification of loading pre-extracted ENF-WHU traces from work/C1/cache/w16/
with spike masking and upstream ENF presence score computation.
"""
from __future__ import annotations
import json
import math
import time
from pathlib import Path
import numpy as np
from scipy.ndimage import median_filter

REPO_ROOT = Path(__file__).resolve().parents[2]
C1_CACHE = REPO_ROOT / "work" / "C1" / "cache" / "w16"
C1_GT = json.loads((REPO_ROOT / "work" / "C1" / "gt_w16.json").read_text(encoding="utf-8"))
C1_SPLIT = json.loads((REPO_ROOT / "work" / "C1" / "split.json").read_text(encoding="utf-8"))


def process_cached_trace(npz_path: Path) -> dict:
    d = np.load(npz_path)
    t = d["t"].astype(np.float64)
    f_raw = d["f"].astype(np.float64)
    q_db = d["q"].astype(np.float64)
    snrk = d["snrk"].astype(np.float64)

    # 1. Detect and mask isolated frame spikes (> 25 mHz jump from 7-second running median)
    f_med = median_filter(f_raw, size=min(7, len(f_raw)))
    spike_mask = np.abs(f_raw - f_med) > 0.025
    f_clean = f_raw.copy()
    f_clean[spike_mask] = np.nan

    # Frame weights in [0.05, 1.0] from q_db, zeroed at spike frames
    q_norm = np.clip((q_db - 3.0) / 15.0, 0.05, 1.0)
    q_norm[spike_mask] = 0.0

    # 2. Compute upstream ENF presence score (blind to reference!)
    # Real ENF has:
    #   (a) High lag-1 & lag-2 temporal autocorrelation (rho1 > 0.80)
    #   (b) Small frame-to-frame step jitter (median |df| < 6 mHz)
    #   (c) Plausible grid standard deviation (std in [2.0, 60.0] mHz)
    #   (d) Multi-harmonic SNR support
    valid_f = f_raw[~spike_mask]
    if len(valid_f) >= 15:
        v_zm = valid_f - np.mean(valid_f)
        denom = float(np.sum(v_zm**2))
        rho1 = float(np.sum(v_zm[:-1] * v_zm[1:]) / denom) if denom > 1e-12 else 0.0
        rho2 = float(np.sum(v_zm[:-2] * v_zm[2:]) / denom) if denom > 1e-12 else 0.0
        rho_smooth = max(0.0, 0.6 * rho1 + 0.4 * rho2)
        med_step_mhz = float(np.median(np.abs(np.diff(valid_f)))) * 1000.0
        std_mhz = float(np.std(valid_f)) * 1000.0
    else:
        rho_smooth = 0.0
        med_step_mhz = 999.0
        std_mhz = 0.0

    step_score = math.exp(-max(0.0, med_step_mhz - 1.5) / 5.0)
    if 1.8 <= std_mhz <= 55.0:
        std_score = 1.0
    elif std_mhz < 1.8:
        std_score = max(0.0, std_mhz / 1.8)
    else:
        std_score = math.exp(-(std_mhz - 55.0) / 40.0)

    inlier_frac = float(1.0 - np.mean(spike_mask))
    # Count harmonics with median SNR >= 2.2
    med_snrk = np.median(snrk, axis=0)
    n_active_h = int(np.sum(med_snrk >= 2.2))
    harm_score = min(1.0, n_active_h / 3.0)

    presence_score = float(
        np.clip(
            (0.45 * (rho_smooth**2) + 0.30 * step_score + 0.15 * inlier_frac + 0.10 * harm_score)
            * std_score,
            0.0,
            1.0,
        )
    )

    return {
        "t": t,
        "f": f_clean,
        "f_raw": f_raw,
        "q": q_norm,
        "meta": {
            "duration_s": float(len(t)),
            "rho_smooth": round(rho_smooth, 4),
            "med_step_mhz": round(med_step_mhz, 3),
            "std_mhz": round(std_mhz, 3),
            "inlier_frac": round(inlier_frac, 4),
            "n_active_harmonics": n_active_h,
            "quality_summary": {
                "enf_presence_score": round(presence_score, 4),
                "mean_q": round(float(np.mean(q_norm)), 4),
            },
        },
    }


if __name__ == "__main__":
    t0 = time.perf_counter()
    h1_good_pres = []
    h1_bad_pres = []
    for cid, info in C1_GT.items():
        out = process_cached_trace(C1_CACHE / "H1" / f"{cid}.npz")
        p = out["meta"]["quality_summary"]["enf_presence_score"]
        if info["rec_ref_r_at_d"] >= 0.80:
            h1_good_pres.append(p)
        else:
            h1_bad_pres.append(p)
    h0_pres = []
    for p_npz in sorted((C1_CACHE / "H0").glob("*.npz")):
        out = process_cached_trace(p_npz)
        h0_pres.append(out["meta"]["quality_summary"]["enf_presence_score"])

    print(f"Loaded all 180 traces in {time.perf_counter()-t0:.3f}s")
    print(f"H1 clean (r>=0.80, n={len(h1_good_pres)}): median_pres={np.median(h1_good_pres):.3f}, p10={np.percentile(h1_good_pres, 10):.3f}")
    print(f"H1 corrupted (r<0.80, n={len(h1_bad_pres)}): median_pres={np.median(h1_bad_pres):.3f}, p90={np.percentile(h1_bad_pres, 90):.3f}")
    print(f"H0 no-ENF (n={len(h0_pres)}): median_pres={np.median(h0_pres):.3f}, p90={np.percentile(h0_pres, 90):.3f}, max={np.max(h0_pres):.3f}")
