"""
model_theory.py — Stochastic process modeling of GB grid frequency (NESO 1s),
Karhunen-Loeve / Bartlett effective degrees of freedom, Subspace Projection Theorem
for noisy ENF matching against clean references, and daily/hourly settlement structure.
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats


def compute_acf_fft(x: np.ndarray, max_lag: int = 3600) -> np.ndarray:
    """Compute normalized autocorrelation function up to max_lag using FFT."""
    x_zero = np.asarray(x, dtype=np.float64) - np.mean(x)
    n = len(x_zero)
    n_fft = 1 << (2 * n - 1).bit_length()
    f_x = np.fft.rfft(x_zero, n=n_fft)
    acov = np.fft.irfft(f_x * np.conjugate(f_x), n=n_fft)[: max_lag + 1]
    if acov[0] <= 0:
        return np.zeros(max_lag + 1, dtype=np.float64)
    return acov / acov[0]


def fit_ou_and_ar_models(f_hz: np.ndarray, dt: float = 1.0) -> dict:
    """
    Fit continuous-time Ornstein-Uhlenbeck (dx = -gamma * x dt + sigma_ou dW)
    and discrete AR(1), AR(2) models to GB grid frequency deviations.
    Also compute first-difference (innovation) process parameters and local
    within-window effective degrees of freedom per minute.
    """
    x = (np.asarray(f_hz, dtype=np.float64) - np.mean(f_hz)) * 1000.0  # in mHz
    sigma_x_mhz = float(np.std(x))
    acf = compute_acf_fft(x, max_lag=3600)

    # AR(1) / exact discrete OU fit at lag 1s and over 1..120s bulk exponential fit
    phi_1 = float(acf[1])
    gamma_1s = -np.log(max(phi_1, 1e-6)) / dt
    tau_1s = 1.0 / max(gamma_1s, 1e-9)

    lags = np.arange(1, 301, dtype=np.float64) * dt
    valid = acf[1:301] > 0.10
    if np.sum(valid) >= 5:
        slope, _, _, _, _ = stats.linregress(lags[valid], np.log(acf[1:301][valid]))
        gamma_bulk = float(-slope)
        tau_ou_bulk = float(1.0 / max(gamma_bulk, 1e-6))
    else:
        gamma_bulk = gamma_1s
        tau_ou_bulk = tau_1s

    # Diffusion coefficient sigma_ou from stationary variance: Var(x) = sigma_ou^2 / (2 * gamma)
    sigma_ou_bulk_mhz = float(sigma_x_mhz * np.sqrt(2.0 * gamma_bulk))

    # Increments analysis (confirming Schäfer et al. 2018 heavy-tail / non-Gaussian increments)
    dx_1s = np.diff(x)
    dx_15s = x[15:] - x[:-15]
    acf_dx1s = compute_acf_fft(dx_1s, max_lag=120)

    # Yule-Walker AR(2) coefficients
    r1, r2 = float(acf[1]), float(acf[2])
    denom = max(1.0 - r1 * r1, 1e-12)
    ar2_a1 = r1 * (1.0 - r2) / denom
    ar2_a2 = (r2 - r1 * r1) / denom
    ar2_resid_var = (1.0 - ar2_a1 * r1 - ar2_a2 * r2) * (sigma_x_mhz ** 2)

    # Bartlett integral correlation timescale of global series vs 1-minute detrended windows
    tau_int_global_s = float(dt * (1.0 + 2.0 * np.sum(acf[1:1800] ** 2)))
    tau_int_dx1s_s = float(dt * (1.0 + 2.0 * np.sum(acf_dx1s[1:60] ** 2)))
    dof_per_min_innovation = float(60.0 / tau_int_dx1s_s)

    # Within-window 60s Karhunen-Loeve effective DoF
    kl_60 = compute_kl_window_stats(x, 60, n_windows=400, seed=42)

    return {
        "mean_hz": float(np.mean(f_hz)),
        "std_mhz": sigma_x_mhz,
        "skewness": float(stats.skew(x)),
        "excess_kurtosis": float(stats.kurtosis(x, fisher=True)),
        "increment_1s_std_mhz": float(np.std(dx_1s)),
        "increment_1s_excess_kurtosis": float(stats.kurtosis(dx_1s, fisher=True)),
        "increment_15s_std_mhz": float(np.std(dx_15s)),
        "increment_15s_excess_kurtosis": float(stats.kurtosis(dx_15s, fisher=True)),
        "ar1_phi1": phi_1,
        "ou_gamma_1s_per_s": float(gamma_1s),
        "ou_tau_1s_s": float(tau_1s),
        "ou_gamma_bulk_per_s": gamma_bulk,
        "ou_tau_bulk_s": tau_ou_bulk,
        "ou_sigma_mhz_per_sqrt_s": sigma_ou_bulk_mhz,
        "ar2_phi1": float(ar2_a1),
        "ar2_phi2": float(ar2_a2),
        "ar2_innovation_std_mhz": float(np.sqrt(max(ar2_resid_var, 0.0))),
        "bartlett_global_timescale_s": tau_int_global_s,
        "within_60s_bulk_neff": kl_60["neff_bulk"],
        "within_60s_tail_neff": kl_60["neff_tail"],
        "innovation_integral_timescale_s": tau_int_dx1s_s,
        "effective_dof_per_minute_raw_window": kl_60["neff_bulk"],
        "effective_dof_per_minute_tail_modes": kl_60["neff_tail"],
        "effective_dof_per_minute_whitened_innovations": dof_per_min_innovation,
        "acf_selected_lags": {
            "1s": float(acf[1]),
            "5s": float(acf[5]),
            "10s": float(acf[10]),
            "15s": float(acf[15]),
            "30s": float(acf[30]),
            "60s": float(acf[60]),
            "120s": float(acf[120]),
            "300s": float(acf[300]),
            "600s": float(acf[600]),
            "1800s": float(acf[1800]),
            "3600s": float(acf[3600]),
        },
        "acf_array_600s": [float(v) for v in acf[:601]],
    }


def compute_kl_window_stats(
    y_mhz: np.ndarray,
    n_samples: int,
    n_windows: int = 400,
    seed: int = 42,
) -> dict:
    """
    Compute the empirical Karhunen-Loeve eigenvalue spectrum of zero-mean unit-norm
    windows of length n_samples, plus the distribution of local standard deviation s_D (mHz).
    """
    if n_samples <= 2:
        return {
            "n_samples": int(n_samples),
            "local_std_mean_mhz": 4.2,
            "local_std_sd_mhz": 3.0,
            "local_std_q10_mhz": 1.2,
            "local_std_q50_mhz": 3.5,
            "local_std_q90_mhz": 8.0,
            "neff_bulk": 2.0,
            "neff_tail": 2.0,
            "w_mode1": 1.0,
            "clean_null_q50": 1.0,
            "clean_null_q95": 1.0,
        }

    rng = np.random.default_rng(seed)
    starts = rng.integers(0, len(y_mhz) - n_samples, size=n_windows)
    segs = np.zeros((n_windows, n_samples), dtype=np.float64)
    stds = np.zeros(n_windows, dtype=np.float64)

    for i, s in enumerate(starts):
        seg = y_mhz[s : s + n_samples]
        seg_zm = seg - np.mean(seg)
        st = float(np.std(seg_zm))
        stds[i] = st
        norm = np.linalg.norm(seg_zm)
        if norm > 1e-9:
            segs[i] = seg_zm / norm

    _, s_vals, _ = np.linalg.svd(segs / np.sqrt(n_windows), full_matrices=False)
    eigs = (s_vals ** 2)
    eigs = eigs / max(float(np.sum(eigs)), 1e-12)

    # Satterthwaite bulk effective DoF: 1 / sum(eigs^2)
    neff_bulk = float(1.0 / max(float(np.sum(eigs ** 2)), 1e-12))
    # Higher-order residual effective DoF (excluding mode 1 linear trend):
    eigs_res = eigs[1:] / max(float(np.sum(eigs[1:])), 1e-12)
    neff_res = float(1.0 / max(float(np.sum(eigs_res ** 2)), 1e-12)) if len(eigs_res) > 0 else 2.0

    # Effective tail DoF governing extreme values r -> 1 across Karhunen-Loeve modes
    # Since the KL spectrum of an OU bridge is scale-invariant (lambda_k ~ 1/k^2),
    # the active clean subspace dimension is neff_bulk + neff_res (~ 10 - 12).
    neff_tail = float(min(n_samples, neff_bulk + 0.95 * neff_res))

    # Pairwise inner products among the 400 random clean windows (79,800 pairs)
    gram = segs @ segs.T
    off_diag = gram[np.triu_indices(n_windows, k=1)]

    return {
        "n_samples": int(n_samples),
        "local_std_mean_mhz": float(np.mean(stds)),
        "local_std_sd_mhz": float(np.std(stds)),
        "local_std_q10_mhz": float(np.percentile(stds, 10)),
        "local_std_q50_mhz": float(np.percentile(stds, 50)),
        "local_std_q90_mhz": float(np.percentile(stds, 90)),
        "local_stds_sample": stds,
        "neff_bulk": neff_bulk,
        "neff_res": neff_res,
        "neff_tail": neff_tail,
        "w_mode1": float(eigs[0]),
        "clean_pair_std": float(np.std(off_diag)),
        "clean_pair_p95": float(np.percentile(off_diag, 95)),
        "clean_pair_p99": float(np.percentile(off_diag, 99)),
        "clean_pair_p999": float(np.percentile(off_diag, 99.9)),
        "clean_pair_p9999": float(np.percentile(off_diag, 99.99)),
    }


def null_corr_ppf(q: float, neff: float) -> float:
    """Inverse CDF (quantile) of sample Pearson correlation under Student-t(neff - 2)."""
    nu = max(0.5, neff - 2.0)
    t_val = float(stats.t.ppf(np.clip(q, 1e-12, 1.0 - 1e-12), df=nu))
    r_val = t_val / np.sqrt(nu + t_val * t_val)
    return float(np.clip(r_val, -0.9999999, 0.9999999))


def analytic_uniqueness_prediction(
    duration_s: int,
    window_s: int,
    sigma_noise_mhz: float,
    cadence_s: int,
    kl_stats: dict,
    subgrid_jitter_mhz: float = 0.0,
) -> dict:
    """
    Closed-form analytic prediction using the Subspace Projection & Karhunen-Loeve
    Extreme-Value Theorem:
      1. Clean reference windows span an effective Karhunen-Loeve subspace S_OU of
         tail dimension d_OU = neff_tail.
      2. Across a search window of span W, adjacent lags decorrelate over a characteristic
         lag width tau_decorr = max(1, 0.18 * N_samples), yielding M_eff_clean = (W - D) / (R * tau_decorr)
         independent candidate peaks in S_OU.
      3. When query has local signal std s_D and effective noise std sigma_tot = sqrt(sigma^2 + sigma_jitter^2):
         - Signal attenuation factor kappa(s_D) = s_D / sqrt(s_D^2 + sigma_tot^2)
         - True correlation r_true(s_D) ~ kappa(s_D)
         - Best wrong-candidate score combines the projected clean extreme value and
           orthogonal white-noise extreme value:
             r_{max,null}(s_D) = sqrt(kappa^2 * r_{max,clean}^2 + (1 - kappa^2) * r_{max,white}^2)
         - Identification occurs when r_true > r_{max,null}, governed by the subspace
           identification SNR:
             SNR_id(s_D) = (sqrt(N) * s_D / sigma_tot) * sqrt((1 - r_{max,clean}) / 2)
    """
    n_samples = max(2, duration_s // cadence_s)
    sigma_tot = float(np.sqrt(sigma_noise_mhz ** 2 + subgrid_jitter_mhz ** 2))

    if n_samples <= 2:
        n_lags = max(1, (window_s - duration_s) // cadence_s)
        return {
            "n_samples": int(n_samples),
            "neff_bulk": 2.0,
            "neff_tail": 2.0,
            "meff": float(n_lags),
            "pred_wrong_mean": 0.995,
            "pred_wrong_p95": 1.000,
            "pred_wrong_p99": 1.000,
            "pred_true_mean": float(
                kl_stats["local_std_mean_mhz"]
                / np.sqrt(kl_stats["local_std_mean_mhz"] ** 2 + max(sigma_tot, 1e-6) ** 2)
            ),
            "pred_acc": float(min(1.0, 2.0 / max(n_lags, 2.0))),
        }

    neff_bulk = float(kl_stats["neff_bulk"])
    neff_tail = float(kl_stats["neff_tail"])
    s_samples = np.asarray(kl_stats.get("local_stds_sample", [kl_stats["local_std_mean_mhz"]]), dtype=np.float64)
    s_samples = np.maximum(s_samples, 0.5)

    # Effective number of independent peaks in the clean OU subspace
    n_lags_total = max(1.0, float(window_s - duration_s) / float(cadence_s))
    tau_decorr_samples = max(1.0, 0.22 * float(n_samples))
    meff_clean = max(1.0, n_lags_total / tau_decorr_samples)

    # Clean extreme-value distribution quantiles from Student-t(neff_tail - 2)
    q_mean = float(np.exp(-np.exp(-0.5772156649)) ** (1.0 / meff_clean))
    q_50 = float(0.50 ** (1.0 / meff_clean))
    q_95 = float(0.95 ** (1.0 / meff_clean))
    q_99 = float(0.99 ** (1.0 / meff_clean))

    r_clean_mean = null_corr_ppf(q_mean, neff_tail)
    r_clean_p50 = null_corr_ppf(q_50, neff_tail)
    r_clean_p95 = null_corr_ppf(q_95, neff_tail)
    r_clean_p99 = null_corr_ppf(q_99, neff_tail)

    # Pure white-noise correlation against smooth reference windows has full N degrees of freedom
    meff_white = max(1.0, n_lags_total / max(1.0, 0.20 * float(n_samples)))
    r_white_mean = null_corr_ppf(float(np.exp(-np.exp(-0.5772156649)) ** (1.0 / meff_white)), float(max(n_samples, 4)))
    r_white_p95 = null_corr_ppf(float(0.95 ** (1.0 / meff_white)), float(max(n_samples, 4)))
    r_white_p99 = null_corr_ppf(float(0.99 ** (1.0 / meff_white)), float(max(n_samples, 4)))

    # Integrate over empirical distribution of local signal standard deviation s_D
    kappa2 = (s_samples ** 2) / (s_samples ** 2 + sigma_tot ** 2)
    kappa = np.sqrt(kappa2)
    pred_true_mean = float(np.mean(kappa))

    # Expected wrong-candidate scores across trials
    w_mean_arr = np.sqrt(kappa2 * (r_clean_mean ** 2) + (1.0 - kappa2) * (r_white_mean ** 2))
    w_p95_arr = np.sqrt(kappa2 * (r_clean_p95 ** 2) + (1.0 - kappa2) * (r_white_p95 ** 2))
    w_p99_arr = np.sqrt(kappa2 * (r_clean_p99 ** 2) + (1.0 - kappa2) * (r_white_p99 ** 2))

    pred_wrong_mean = float(np.mean(w_mean_arr))
    pred_wrong_p50 = float(np.median(w_mean_arr))
    pred_wrong_p95 = float(np.percentile(w_p95_arr, 90))
    pred_wrong_p99 = float(np.percentile(w_p99_arr, 95))

    if sigma_tot <= 1e-9:
        pred_acc = 1.0
    else:
        # Subspace projection win probability:
        # Clean signal energy is N * s_D^2; white noise projected onto the smooth
        # d_KL-dimensional reference subspace has variance (d_KL / N) * sigma_tot^2.
        u_grid = np.linspace(0.05, 0.95, 19)
        q_clean_grid = u_grid ** (1.0 / meff_clean)
        r_clean_grid = np.array([null_corr_ppf(q, neff_tail) for q in q_clean_grid])

        acc_total = 0.0
        for r_c in r_clean_grid:
            # Clean correlation margin 1 - r_c vs projected noise maximum r_white_mean * (sigma_tot / s_D) * sqrt(2*(1 - r_c))
            sig_margin = kappa * (1.0 - r_c)
            noise_peak = np.sqrt(1.0 - kappa2) * r_white_mean * np.sqrt(max(0.5 * (1.0 - r_c), 0.01))
            noise_sd = np.maximum(
                np.sqrt(1.0 - kappa2) * np.sqrt(2.0 * max(1.0 - r_c, 0.005) / float(n_samples)),
                1e-5,
            )
            z_margin = (sig_margin - noise_peak) / noise_sd
            acc_total += float(np.mean(stats.norm.cdf(z_margin)))
        pred_acc = float(np.clip(acc_total / len(r_clean_grid), 0.0, 1.0))

    return {
        "n_samples": int(n_samples),
        "neff_bulk": neff_bulk,
        "neff_tail": neff_tail,
        "meff": float(meff_clean),
        "pred_wrong_mean": pred_wrong_mean,
        "pred_wrong_p50": pred_wrong_p50,
        "pred_wrong_p95": pred_wrong_p95,
        "pred_wrong_p99": pred_wrong_p99,
        "pred_true_mean": pred_true_mean,
        "pred_acc": pred_acc,
    }


def analyze_daily_and_hourly_structure(df: pd.DataFrame) -> dict:
    """
    Quantify daily (hour of day UTC) and hourly (minute of hour, settlement boundaries)
    structure of GB grid frequency fluctuations on 1-second NESO data.
    """
    ts = pd.to_datetime(df["ts_utc"], unit="s", utc=True)
    f = df["f_hz"].to_numpy(dtype=np.float64)
    df_diff = np.abs(np.diff(f, prepend=f[0])) * 1000.0  # mHz/s step speed

    n_mins = len(f) // 60
    f_blocks = f[: n_mins * 60].reshape(n_mins, 60)
    ts_mins = ts.iloc[: n_mins * 60 : 60]
    block_std_mhz = np.std(f_blocks, axis=1) * 1000.0
    block_range_mhz = (np.max(f_blocks, axis=1) - np.min(f_blocks, axis=1)) * 1000.0
    block_step_mhz = np.mean(df_diff[: n_mins * 60].reshape(n_mins, 60), axis=1)

    minute_of_hour = ts_mins.dt.minute.to_numpy()
    hour_of_day = ts_mins.dt.hour.to_numpy()

    min_profile = []
    for m in range(60):
        mask = minute_of_hour == m
        min_profile.append({
            "minute": int(m),
            "mean_local_std_mhz": float(np.mean(block_std_mhz[mask])),
            "median_local_std_mhz": float(np.median(block_std_mhz[mask])),
            "mean_range_mhz": float(np.mean(block_range_mhz[mask])),
            "mean_step_rate_mhz_per_s": float(np.mean(block_step_mhz[mask])),
        })

    hour_profile = []
    for h in range(24):
        mask = hour_of_day == h
        hour_profile.append({
            "hour_utc": int(h),
            "mean_local_std_mhz": float(np.mean(block_std_mhz[mask])),
            "mean_range_mhz": float(np.mean(block_range_mhz[mask])),
            "global_std_mhz": float(np.std(f_blocks[mask]) * 1000.0),
        })

    top_of_hour_mask = np.isin(minute_of_hour, [58, 59, 0, 1, 2])
    half_hour_mask = np.isin(minute_of_hour, [28, 29, 30, 31, 32])
    boundary_mask = top_of_hour_mask | half_hour_mask
    mid_period_mask = ~boundary_mask

    std_top = block_std_mhz[top_of_hour_mask]
    std_half = block_std_mhz[half_hour_mask]
    std_bound = block_std_mhz[boundary_mask]
    std_mid = block_std_mhz[mid_period_mask]

    t_stat, p_val_t = stats.ttest_ind(std_bound, std_mid, equal_var=False)
    u_stat, p_val_u = stats.mannwhitneyu(std_bound, std_mid, alternative="greater")

    return {
        "minute_of_hour_profile": min_profile,
        "hour_of_day_profile": hour_profile,
        "settlement_boundary_comparison": {
            "top_of_hour_minutes": [58, 59, 0, 1, 2],
            "half_hour_minutes": [28, 29, 30, 31, 32],
            "top_of_hour_mean_std_mhz": float(np.mean(std_top)),
            "half_hour_mean_std_mhz": float(np.mean(std_half)),
            "boundary_combined_mean_std_mhz": float(np.mean(std_bound)),
            "mid_period_mean_std_mhz": float(np.mean(std_mid)),
            "ratio_top_of_hour_vs_mid": float(np.mean(std_top) / max(np.mean(std_mid), 1e-9)),
            "ratio_boundary_vs_mid": float(np.mean(std_bound) / max(np.mean(std_mid), 1e-9)),
            "welch_t_stat": float(t_stat),
            "welch_p_value": float(p_val_t),
            "mannwhitney_u_p_value": float(p_val_u),
            "n_boundary_minutes": int(np.sum(boundary_mask)),
            "n_mid_minutes": int(np.sum(mid_period_mask)),
        },
    }
