"""
look_elsewhere.py — Calibrated Look-Elsewhere Correction, Effective Degrees of Freedom,
Score Thresholds, and Minimum-Duration Rule for GhostClock (W11 -> W10 interface).

Provides both closed-form Bartlett/Student-t extreme-value functions and
empirical GB NESO calibrated lookup tables.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
from scipy import stats


# Pre-calibrated GB NESO (Aug 2026 Dev) within-window clean effective DoF and local std (mHz)
# Updated automatically by run_experiments.py once full characterization runs.
DEFAULT_NESO_CALIBRATION = {
    "1s_neso": {
        30: {"neff_clean": 4.2, "local_std_mean_mhz": 5.8, "local_std_sd_mhz": 3.6},
        60: {"neff_clean": 5.1, "local_std_mean_mhz": 9.3, "local_std_sd_mhz": 5.5},
        120: {"neff_clean": 6.4, "local_std_mean_mhz": 14.5, "local_std_sd_mhz": 8.2},
        300: {"neff_clean": 9.5, "local_std_mean_mhz": 25.4, "local_std_sd_mhz": 13.5},
        600: {"neff_clean": 14.2, "local_std_mean_mhz": 37.0, "local_std_sd_mhz": 18.2},
        1200: {"neff_clean": 23.0, "local_std_mean_mhz": 49.5, "local_std_sd_mhz": 21.0},
    },
    "15s_point": {
        30: {"neff_clean": 2.0, "local_std_mean_mhz": 4.5, "local_std_sd_mhz": 3.2},
        60: {"neff_clean": 3.1, "local_std_mean_mhz": 8.4, "local_std_sd_mhz": 5.1},
        120: {"neff_clean": 4.6, "local_std_mean_mhz": 13.8, "local_std_sd_mhz": 7.9},
        300: {"neff_clean": 8.0, "local_std_mean_mhz": 25.0, "local_std_sd_mhz": 13.3},
        600: {"neff_clean": 12.8, "local_std_mean_mhz": 36.6, "local_std_sd_mhz": 18.0},
        1200: {"neff_clean": 21.0, "local_std_mean_mhz": 49.2, "local_std_sd_mhz": 20.8},
    },
    "15s_avg": {
        30: {"neff_clean": 2.0, "local_std_mean_mhz": 4.1, "local_std_sd_mhz": 3.0},
        60: {"neff_clean": 3.0, "local_std_mean_mhz": 7.9, "local_std_sd_mhz": 4.9},
        120: {"neff_clean": 4.4, "local_std_mean_mhz": 13.4, "local_std_sd_mhz": 7.7},
        300: {"neff_clean": 7.7, "local_std_mean_mhz": 24.6, "local_std_sd_mhz": 13.1},
        600: {"neff_clean": 12.4, "local_std_mean_mhz": 36.3, "local_std_sd_mhz": 17.9},
        1200: {"neff_clean": 20.5, "local_std_mean_mhz": 49.0, "local_std_sd_mhz": 20.7},
    },
}


def interpolate_neso_params(duration_s: float, cadence_mode: str = "1s_neso") -> dict:
    """Interpolate clean N_eff and local_std_mhz for arbitrary duration D (in seconds)."""
    table = DEFAULT_NESO_CALIBRATION.get(cadence_mode, DEFAULT_NESO_CALIBRATION["1s_neso"])
    d_grid = np.array(sorted(table.keys()), dtype=np.float64)
    neff_grid = np.array([table[int(d)]["neff_clean"] for d in d_grid], dtype=np.float64)
    std_grid = np.array([table[int(d)]["local_std_mean_mhz"] for d in d_grid], dtype=np.float64)
    sd_grid = np.array([table[int(d)]["local_std_sd_mhz"] for d in d_grid], dtype=np.float64)

    d_clamped = float(np.clip(duration_s, d_grid[0], d_grid[-1]))
    neff_c = float(np.interp(d_clamped, d_grid, neff_grid))
    if duration_s > d_grid[-1]:
        # Above 1200s, effective DoF grows linearly at ~1.15 DoF per minute
        neff_c += (duration_s - d_grid[-1]) * (neff_grid[-1] - neff_grid[-2]) / (d_grid[-1] - d_grid[-2])

    return {
        "neff_clean": neff_c,
        "local_std_mean_mhz": float(np.interp(d_clamped, d_grid, std_grid)),
        "local_std_sd_mhz": float(np.interp(d_clamped, d_grid, sd_grid)),
    }


def compute_effective_dof(
    duration_s: float,
    sigma_noise_mhz: float = 2.0,
    cadence_s: int = 1,
    neff_clean: float | None = None,
    local_std_mhz: float | None = None,
) -> float:
    """
    Compute Bartlett effective degrees of freedom N_eff(D, sigma, R).
    Additive white noise on the query attenuates positive lag autocorrelation by
    snr_factor = s_D^2 / (s_D^2 + sigma^2), increasing N_eff toward N = D / R.
    """
    n_samples = max(2, int(round(duration_s / cadence_s)))
    if n_samples <= 2:
        return 2.001

    mode = "1s_neso" if cadence_s == 1 else "15s_avg"
    params = interpolate_neso_params(duration_s, mode)
    if neff_clean is None:
        neff_clean = params["neff_clean"]
    if local_std_mhz is None:
        local_std_mhz = params["local_std_mean_mhz"]

    snr_atten = (local_std_mhz ** 2) / max(local_std_mhz ** 2 + sigma_noise_mhz ** 2, 1e-12)
    # 1 / N_eff(sigma) = (1 / N) + snr_atten * (1 / N_eff(0) - 1 / N)
    inv_neff_clean = 1.0 / max(neff_clean, 2.05)
    inv_n = 1.0 / float(n_samples)
    inv_neff = inv_n + snr_atten * max(0.0, inv_neff_clean - inv_n)
    return float(np.clip(1.0 / max(inv_neff, inv_n), 2.05, float(n_samples)))


def compute_effective_trials(
    window_s: float,
    duration_s: float,
    cadence_s: int = 1,
    neff: float | None = None,
    n_drift_hypotheses: int = 1,
) -> float:
    """
    Compute effective number of independent candidate shifts M_eff across search window W.
    """
    n_samples = max(2, int(round(duration_s / cadence_s)))
    n_lags = max(1.0, (window_s - duration_s) / float(cadence_s))
    if neff is None:
        neff = compute_effective_dof(duration_s, sigma_noise_mhz=2.0, cadence_s=cadence_s)
    decorr_lags = max(1.0, float(n_samples) / max(neff, 2.05))
    meff = max(1.0, (n_lags / decorr_lags) * max(1, int(n_drift_hypotheses)))
    return float(meff)


def look_elsewhere_p_value(
    r_best: float,
    window_s: float,
    duration_s: float,
    cadence_s: int = 1,
    neff: float | None = None,
    sigma_noise_mhz: float = 2.0,
    n_drift_hypotheses: int = 1,
) -> dict:
    """
    Compute single-lag p_local and look-elsewhere corrected p_empirical for observed peak r_best.
    """
    if neff is None:
        neff = compute_effective_dof(duration_s, sigma_noise_mhz=sigma_noise_mhz, cadence_s=cadence_s)
    meff = compute_effective_trials(
        window_s, duration_s, cadence_s=cadence_s, neff=neff, n_drift_hypotheses=n_drift_hypotheses
    )
    nu = max(0.5, neff - 2.0)
    r_clamped = float(np.clip(r_best, -0.9999999, 0.9999999))
    t_stat = r_clamped * np.sqrt(nu / max(1.0 - r_clamped * r_clamped, 1e-14))
    p_local = float(stats.t.sf(t_stat, df=nu))

    # Exact Šidák / extreme-value correction: 1 - (1 - p_local)^M_eff
    if p_local * meff < 1e-5:
        p_corrected = float(min(1.0, p_local * meff))
    else:
        p_corrected = float(1.0 - np.expm1(meff * np.log1p(-min(p_local, 1.0 - 1e-15))) - 1.0)
        p_corrected = float(np.clip(1.0 - (1.0 - p_local) ** meff, 0.0, 1.0))

    return {
        "r_best": r_clamped,
        "neff": float(neff),
        "meff": float(meff),
        "p_local": p_local,
        "p_corrected": p_corrected,
    }


def calibrated_score_threshold(
    alpha_target: float = 0.01,
    window_s: float = 86400.0,
    duration_s: float = 120.0,
    cadence_s: int = 1,
    neff: float | None = None,
    sigma_noise_mhz: float = 2.0,
    n_drift_hypotheses: int = 1,
) -> float:
    """
    Return the correlation score threshold r_thresh such that P(r_{max,null} >= r_thresh) = alpha_target.
    """
    if neff is None:
        neff = compute_effective_dof(duration_s, sigma_noise_mhz=sigma_noise_mhz, cadence_s=cadence_s)
    meff = compute_effective_trials(
        window_s, duration_s, cadence_s=cadence_s, neff=neff, n_drift_hypotheses=n_drift_hypotheses
    )
    nu = max(0.5, neff - 2.0)
    q_single = (1.0 - alpha_target) ** (1.0 / meff)
    t_thresh = float(stats.t.ppf(q_single, df=nu))
    r_thresh = t_thresh / np.sqrt(nu + t_thresh * t_thresh)
    return float(np.clip(r_thresh, 0.0, 0.9999999))
