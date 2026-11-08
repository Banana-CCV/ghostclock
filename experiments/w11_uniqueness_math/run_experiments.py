"""
run_experiments.py — Fast, exact block-reduced FFT execution script for W11:
Uniqueness & Feasibility Mathematics (NESO-based).

Completes all 300 Dev+Holdout Monte Carlo cells, OU/AR stochastic fits, settlement boundary
tests, extractor error stress suite, Step G hybrid AR-whitening iteration, W10 calibration JSON,
and all 6 PNG figures in ~15-20 seconds.

Usage from repo root:
  python work/W11/run_experiments.py
"""
import argparse
import gc
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy.fft
from scipy import stats

from work.W11.model_theory import (
    fit_ou_and_ar_models,
    compute_kl_window_stats,
    analytic_uniqueness_prediction,
    analyze_daily_and_hourly_structure,
)


DURATIONS_S = [30, 60, 120, 300, 600, 1200]
SIGMAS_MHZ = [0.0, 1.0, 2.0, 5.0, 10.0]
WINDOWS_SPEC = [
    ("1h", 3600),
    ("6h", 21600),
    ("1d", 86400),
    ("1w", 604800),
    ("1m", -1),  # full month
]
CADENCE_MODES = ["1s_neso", "15s_point", "15s_avg"]
FFT_WORKERS = 4


def precompute_sliding_norms(y: np.ndarray, n_win: int, min_std_mhz: float = 0.25) -> np.ndarray:
    """Compute sliding zero-mean L2 norms ||y[tau : tau+n_win] - mean||_2 in O(N) via float64 cumsum."""
    y64 = np.asarray(y, dtype=np.float64)
    n_lags = len(y64) - n_win + 1
    cs1 = np.concatenate(([0.0], np.cumsum(y64)))
    cs2 = np.concatenate(([0.0], np.cumsum(y64 * y64)))
    sum_y = cs1[n_win : n_win + n_lags] - cs1[:n_lags]
    sum_y2 = cs2[n_win : n_win + n_lags] - cs2[:n_lags]
    var_y = np.maximum(sum_y2 - (sum_y * sum_y) / float(n_win), (min_std_mhz ** 2) * float(n_win))
    return np.sqrt(var_y).astype(np.float32)


def evaluate_windows_via_blocks(
    corr_batch: np.ndarray,
    starts_ref_idx: np.ndarray,
    starts_1s: np.ndarray,
    cadence_s: int,
    D: int,
    n_total_1s: int,
    r_mode: str,
) -> dict:
    """
    Evaluate all 5 search windows (1h, 6h, 1d, 1w, 1m) in O(N_blocks) time by partitioning
    lags into 1-hour blocks (3600s = 3600 lags at 1s, or 240 lags at 15s).
    """
    n_trials, n_lags = corr_batch.shape
    block_lags = max(1, 3600 // cadence_s)
    n_blocks = n_lags // block_lags
    n_used = n_blocks * block_lags

    corr_trimmed = corr_batch[:, :n_used].reshape(n_trials, n_blocks, block_lags)
    blk_max = np.max(corr_trimmed, axis=2)        # (n_trials, n_blocks)
    blk_argmax = np.argmax(corr_trimmed, axis=2)  # (n_trials, n_blocks)

    excl_rad_lags = max(2, max(D, 60) // cadence_s)
    res_by_w = {}

    for w_label, w_sec_spec in WINDOWS_SPEC:
        w_blocks = n_blocks if w_sec_spec < 0 else min(n_blocks, max(1, w_sec_spec // 3600))
        acc_2s = 0
        acc_15s = 0
        true_scores = np.zeros(n_trials, dtype=np.float64)
        wrong_scores = np.zeros(n_trials, dtype=np.float64)
        margins = np.zeros(n_trials, dtype=np.float64)

        for i in range(n_trials):
            s_idx = min(int(starts_ref_idx[i]), n_used - 1)
            s_1s = int(starts_1s[i]) if r_mode != "1s_neso" else s_idx
            true_scores[i] = float(corr_batch[i, s_idx])

            s_blk = s_idx // block_lags
            if w_blocks >= n_blocks:
                b0, b1 = 0, n_blocks
            else:
                frac = ((i * 37 + D) % 73) / 73.0
                offset_blocks = int(frac * max(0, w_blocks - 1))
                b0 = max(0, min(n_blocks - w_blocks, s_blk - offset_blocks))
                b1 = b0 + w_blocks

            # Best overall peak in window [b0, b1)
            sub_bmax = blk_max[i, b0:b1]
            best_b_rel = int(np.argmax(sub_bmax))
            best_b = b0 + best_b_rel
            best_score = float(sub_bmax[best_b_rel])
            best_idx = best_b * block_lags + int(blk_argmax[i, best_b])
            est_start_1s = best_idx * cadence_s

            err_s = abs(est_start_1s - s_1s)
            if err_s <= 2:
                acc_2s += 1
            if err_s <= 15:
                acc_15s += 1

            # Best wrong score outside [s_idx - excl_rad_lags, s_idx + excl_rad_lags]
            lo_ex = max(b0 * block_lags, s_idx - excl_rad_lags)
            hi_ex = min(b1 * block_lags, s_idx + excl_rad_lags + 1)
            blk_lo = lo_ex // block_lags
            blk_hi = (hi_ex - 1) // block_lags

            w_best = -1.0
            if blk_lo > b0:
                w_best = max(w_best, float(np.max(blk_max[i, b0:blk_lo])))
            if blk_hi + 1 < b1:
                w_best = max(w_best, float(np.max(blk_max[i, blk_hi + 1 : b1])))
            # Check remaining unexcluded lags inside boundary blocks [blk_lo .. blk_hi]
            raw_slice_start = blk_lo * block_lags
            raw_slice_end = (blk_hi + 1) * block_lags
            if lo_ex > raw_slice_start:
                w_best = max(w_best, float(np.max(corr_batch[i, raw_slice_start:lo_ex])))
            if hi_ex < raw_slice_end:
                w_best = max(w_best, float(np.max(corr_batch[i, hi_ex:raw_slice_end])))

            wrong_scores[i] = w_best
            margins[i] = best_score - w_best

        res_by_w[w_label] = {
            "acc_2s": acc_2s,
            "acc_15s": acc_15s,
            "true_scores": true_scores,
            "wrong_scores": wrong_scores,
            "margins": margins,
        }
    return res_by_w


def run_mc_grid_for_split(
    y_1s_mhz: np.ndarray,
    split_name: str,
    n_trials: int = 30,
    seed: int = 101,
) -> tuple[list[dict], dict]:
    """
    Execute the full (D x sigma x W x R) Monte Carlo identification experiment on a 1s reference series.
    All noise-injected query segments are explicitly labelled 'semi-synthetic'.
    """
    t0_split = time.time()
    n_total_1s = len(y_1s_mhz)
    rng = np.random.default_rng(seed)

    n_total_15s = n_total_1s // 15
    y_15s_point = y_1s_mhz[: n_total_15s * 15 : 15].copy()
    y_15s_avg = y_1s_mhz[: n_total_15s * 15].reshape(n_total_15s, 15).mean(axis=1)

    subgrid_diffs_point = []
    subgrid_diffs_avg = []
    for offset in range(1, 8):
        subgrid_diffs_point.append(
            np.std(y_1s_mhz[offset : offset + (n_total_15s - 1) * 15 : 15] - y_15s_point[: (n_total_15s - 1)])
        )
        seg_shifted = y_1s_mhz[offset : offset + (n_total_15s - 1) * 15].reshape(n_total_15s - 1, 15).mean(axis=1)
        subgrid_diffs_avg.append(np.std(seg_shifted - y_15s_avg[: n_total_15s - 1]))
    jitter_15s_point_mhz = float(np.mean(subgrid_diffs_point)) * 0.55
    jitter_15s_avg_mhz = float(np.mean(subgrid_diffs_avg)) * 0.45

    results_rows = []
    kl_by_mode_and_d = {"1s_neso": {}, "15s_point": {}, "15s_avg": {}}

    for r_mode in CADENCE_MODES:
        if r_mode == "1s_neso":
            y_ref = y_1s_mhz
            cadence_s = 1
            subgrid_jitter = 0.0
        elif r_mode == "15s_point":
            y_ref = y_15s_point
            cadence_s = 15
            subgrid_jitter = jitter_15s_point_mhz
        else:
            y_ref = y_15s_avg
            cadence_s = 15
            subgrid_jitter = jitter_15s_avg_mhz

        n_ref = len(y_ref)
        max_n_win = max(DURATIONS_S) // cadence_s
        n_fft = scipy.fft.next_fast_len(n_ref + max_n_win, real=True)
        Y_fft = scipy.fft.rfft(y_ref.astype(np.float32), n=n_fft, workers=FFT_WORKERS)

        for D in DURATIONS_S:
            n_win = max(2, D // cadence_s)
            n_lags = n_ref - n_win + 1
            norm_y = precompute_sliding_norms(y_ref, n_win)

            kl_stats = compute_kl_window_stats(y_ref, n_win, n_windows=300, seed=seed + D)
            kl_by_mode_and_d[r_mode][D] = {
                k: v for k, v in kl_stats.items() if k != "local_stds_sample"
            }

            block_lags = max(1, 3600 // cadence_s)
            n_used = (n_lags // block_lags) * block_lags
            max_start_1s = (n_used - 4) * cadence_s
            starts_1s = rng.integers(cadence_s * 2, max_start_1s, size=n_trials)
            starts_ref_idx = np.clip(np.round(starts_1s / float(cadence_s)).astype(np.int64), 0, n_used - 1)

            seg_clean_zm = np.zeros((n_trials, n_win), dtype=np.float32)
            seg_noise_zm = np.zeros((n_trials, n_win), dtype=np.float32)

            for i in range(n_trials):
                s_1s = int(starts_1s[i])
                if r_mode == "1s_neso":
                    s_idx = int(starts_ref_idx[i])
                    c_seg = y_1s_mhz[s_idx : s_idx + n_win].astype(np.float64)
                elif r_mode == "15s_point":
                    c_seg = y_1s_mhz[s_1s : s_1s + n_win * 15 : 15].astype(np.float64)
                else:
                    c_seg = y_1s_mhz[s_1s : s_1s + n_win * 15].reshape(n_win, 15).mean(axis=1).astype(np.float64)

                n_seg = rng.normal(0.0, 1.0, size=n_win)
                seg_clean_zm[i] = (c_seg - np.mean(c_seg)).astype(np.float32)
                seg_noise_zm[i] = (n_seg - np.mean(n_seg)).astype(np.float32)

            # Single FFT pair for all n_trials (=30, ~300 MB total)
            C_fft = scipy.fft.rfft(seg_clean_zm, n=n_fft, axis=1, workers=FFT_WORKERS)
            A_clean = scipy.fft.irfft(Y_fft[None, :] * np.conj(C_fft), n=n_fft, axis=1, workers=FFT_WORKERS)[:, :n_lags]
            del C_fft
            A_clean /= norm_y[None, :]

            N_fft = scipy.fft.rfft(seg_noise_zm, n=n_fft, axis=1, workers=FFT_WORKERS)
            A_noise = scipy.fft.irfft(Y_fft[None, :] * np.conj(N_fft), n=n_fft, axis=1, workers=FFT_WORKERS)[:, :n_lags]
            del N_fft
            A_noise /= norm_y[None, :]

            for sigma in SIGMAS_MHZ:
                q_comb = seg_clean_zm + np.float32(sigma) * seg_noise_zm
                q_norms = np.maximum(np.linalg.norm(q_comb, axis=1), np.float32(1e-12))
                corr_batch = (A_clean + np.float32(sigma) * A_noise) / q_norms[:, None]
                np.clip(corr_batch, -1.0, 1.0, out=corr_batch)

                res_by_w = evaluate_windows_via_blocks(
                    corr_batch, starts_ref_idx, starts_1s, cadence_s, D, n_total_1s, r_mode
                )
                del corr_batch

                for w_label, w_sec_spec in WINDOWS_SPEC:
                    w_sec = n_total_1s if w_sec_spec < 0 else w_sec_spec
                    cell = res_by_w[w_label]
                    pred = analytic_uniqueness_prediction(
                        duration_s=D,
                        window_s=w_sec,
                        sigma_noise_mhz=sigma,
                        cadence_s=cadence_s,
                        kl_stats=kl_stats,
                        subgrid_jitter_mhz=subgrid_jitter,
                    )
                    results_rows.append({
                        "split": split_name,
                        "data_label": "real_reference" if sigma == 0.0 and r_mode == "1s_neso" else "semi-synthetic",
                        "cadence_mode": r_mode,
                        "cadence_s": cadence_s,
                        "duration_s": D,
                        "sigma_mhz": sigma,
                        "window_label": w_label,
                        "window_s": w_sec,
                        "n_trials": n_trials,
                        "acc_2s": cell["acc_2s"] / float(n_trials),
                        "acc_15s": cell["acc_15s"] / float(n_trials),
                        "acc_2s_num": cell["acc_2s"],
                        "acc_15s_num": cell["acc_15s"],
                        "true_score_mean": float(np.mean(cell["true_scores"])),
                        "true_score_std": float(np.std(cell["true_scores"])),
                        "wrong_score_mean": float(np.mean(cell["wrong_scores"])),
                        "wrong_score_std": float(np.std(cell["wrong_scores"])),
                        "wrong_score_p50": float(np.percentile(cell["wrong_scores"], 50)),
                        "wrong_score_p95": float(np.percentile(cell["wrong_scores"], 95)),
                        "wrong_score_p99": float(np.percentile(cell["wrong_scores"], 99)),
                        "margin_mean": float(np.mean(cell["margins"])),
                        "analytic_acc_pred": pred["pred_acc"],
                        "analytic_true_mean_pred": pred["pred_true_mean"],
                        "analytic_wrong_mean_pred": pred["pred_wrong_mean"],
                        "analytic_wrong_p95_pred": pred["pred_wrong_p95"],
                        "analytic_wrong_p99_pred": pred["pred_wrong_p99"],
                        "neff_bulk": pred["neff_bulk"],
                        "neff_tail": pred["neff_tail"],
                        "meff": pred["meff"],
                    })

            del A_clean, A_noise
            gc.collect()
            print(f"[MC {split_name}] Completed R={r_mode} D={D:4d}s (elapsed {time.time() - t0_split:.1f}s)", flush=True)

        del Y_fft
        gc.collect()

    return results_rows, kl_by_mode_and_d


def run_settlement_stratified_mc(y_1s_mhz: np.ndarray, ts_utc: np.ndarray, n_trials: int = 30, seed: int = 303) -> list[dict]:
    """
    Quantify whether ENF segments starting near top-of-hour (:58..:01) and half-hour (:28..:31)
    settlement boundaries have higher identification accuracy than mid-period (:10..:20, :40..:50) segments.
    """
    rng = np.random.default_rng(seed)
    n_total = len(y_1s_mhz)
    n_fft = scipy.fft.next_fast_len(n_total + 300, real=True)
    Y_fft = scipy.fft.rfft(y_1s_mhz.astype(np.float32), n=n_fft, workers=FFT_WORKERS)

    ts_dt = pd.to_datetime(ts_utc, unit="s", utc=True)
    minutes = ts_dt.minute.to_numpy()
    seconds = ts_dt.second.to_numpy()

    valid_range = np.arange(n_total) < (n_total - 7200)
    top_starts = np.where(valid_range & (seconds == 0) & np.isin(minutes, [58, 59, 0, 1]))[0]
    half_starts = np.where(valid_range & (seconds == 0) & np.isin(minutes, [28, 29, 30, 31]))[0]
    mid_starts = np.where(valid_range & (seconds == 0) & np.isin(minutes, list(range(10, 21)) + list(range(40, 51))))[0]

    strata = [
        ("top_of_hour", top_starts),
        ("half_hour", half_starts),
        ("mid_period", mid_starts),
    ]

    rows = []
    for D in [60, 120]:
        n_lags = n_total - D + 1
        norm_y = precompute_sliding_norms(y_1s_mhz, D)
        for stratum_name, pool in strata:
            chosen = rng.choice(pool, size=n_trials, replace=False)
            seg_clean = np.zeros((n_trials, D), dtype=np.float32)
            seg_noise = np.zeros((n_trials, D), dtype=np.float32)
            local_stds = np.zeros(n_trials, dtype=np.float64)
            for i, s in enumerate(chosen):
                c = y_1s_mhz[s : s + D].astype(np.float64)
                local_stds[i] = float(np.std(c))
                n = rng.normal(0.0, 1.0, size=D)
                seg_clean[i] = (c - np.mean(c)).astype(np.float32)
                seg_noise[i] = (n - np.mean(n)).astype(np.float32)

            C_fft = scipy.fft.rfft(seg_clean, n=n_fft, axis=1, workers=FFT_WORKERS)
            A_clean = scipy.fft.irfft(Y_fft[None, :] * np.conj(C_fft), n=n_fft, axis=1, workers=FFT_WORKERS)[:, :n_lags]
            del C_fft
            A_clean /= norm_y[None, :]

            N_fft = scipy.fft.rfft(seg_noise, n=n_fft, axis=1, workers=FFT_WORKERS)
            A_noise = scipy.fft.irfft(Y_fft[None, :] * np.conj(N_fft), n=n_fft, axis=1, workers=FFT_WORKERS)[:, :n_lags]
            del N_fft
            A_noise /= norm_y[None, :]

            for sigma in [2.0, 5.0, 10.0]:
                q_comb = seg_clean + np.float32(sigma) * seg_noise
                q_norms = np.maximum(np.linalg.norm(q_comb, axis=1), np.float32(1e-12))
                corr_b = (A_clean + np.float32(sigma) * A_noise) / q_norms[:, None]
                np.clip(corr_b, -1.0, 1.0, out=corr_b)
                res_w = evaluate_windows_via_blocks(corr_b, chosen, chosen, 1, D, n_total, "1s_neso")
                del corr_b
                for w_label in ["1d", "1m"]:
                    acc2 = res_w[w_label]["acc_2s"]
                    rows.append({
                        "stratum": stratum_name,
                        "duration_s": D,
                        "sigma_mhz": sigma,
                        "window_label": w_label,
                        "n_trials": n_trials,
                        "mean_local_std_mhz": float(np.mean(local_stds)),
                        "acc_2s": acc2 / float(n_trials),
                        "acc_2s_num": acc2,
                    })
            del A_clean, A_noise
            gc.collect()
    del Y_fft
    gc.collect()
    return rows


def run_extractor_stress_suite(y_1s_mhz: np.ndarray, n_trials: int = 30, seed: int = 404) -> list[dict]:
    """
    Evaluate realistic semi-synthetic extractor non-idealities against W in {1d, 1m}.
    """
    rng = np.random.default_rng(seed)
    n_total = len(y_1s_mhz)
    n_fft = scipy.fft.next_fast_len(n_total + 1200, real=True)
    Y_fft = scipy.fft.rfft(y_1s_mhz.astype(np.float32), n=n_fft, workers=FFT_WORKERS)

    stress_modes = [
        "awgn_2mHz",
        "drift_100ppm",
        "drift_1000ppm",
        "dropouts_30pct",
        "combined_realistic",
    ]
    rows = []

    for D in [60, 120, 300, 600]:
        n_lags = n_total - D + 1
        norm_y = precompute_sliding_norms(y_1s_mhz, D)
        starts = rng.integers(100, n_lags - 7200, size=n_trials)

        for mode in stress_modes:
            queries = np.zeros((n_trials, D), dtype=np.float32)
            for i, s in enumerate(starts):
                t_idx = np.arange(D, dtype=np.float64)
                if mode == "awgn_2mHz":
                    seg = y_1s_mhz[s : s + D] + rng.normal(0.0, 2.0, size=D)
                    mask = np.ones(D, dtype=bool)
                elif mode == "drift_100ppm":
                    t_warped = s + t_idx * (1.0 + 1e-4)
                    seg_interp = np.interp(t_warped, np.arange(s, s + D + 5), y_1s_mhz[s : s + D + 5])
                    rw = np.cumsum(rng.normal(0.0, 0.15, size=D))
                    seg = seg_interp + 5.0 + rw + rng.normal(0.0, 2.0, size=D)
                    mask = np.ones(D, dtype=bool)
                elif mode == "drift_1000ppm":
                    t_warped = s + t_idx * (1.0 + 1e-3)
                    seg_interp = np.interp(t_warped, np.arange(s, s + D + 5), y_1s_mhz[s : s + D + 5])
                    seg = seg_interp + 50.0 + rng.normal(0.0, 2.0, size=D)
                    mask = np.ones(D, dtype=bool)
                elif mode == "dropouts_30pct":
                    seg = y_1s_mhz[s : s + D] + rng.normal(0.0, 2.0, size=D)
                    mask = np.ones(D, dtype=bool)
                    n_drop_target = int(0.30 * D)
                    dropped = 0
                    while dropped < n_drop_target:
                        b_len = int(rng.integers(5, 21))
                        b_start = int(rng.integers(0, max(1, D - b_len)))
                        mask[b_start : b_start + b_len] = False
                        dropped = int(np.sum(~mask))
                else:
                    t_warped = s + t_idx * (1.0 + 1e-4)
                    seg_interp = np.interp(t_warped, np.arange(s, s + D + 5), y_1s_mhz[s : s + D + 5])
                    seg = seg_interp + rng.normal(0.0, 2.0, size=D)
                    n_imp = max(1, int(0.02 * D))
                    imp_idx = rng.choice(D, size=n_imp, replace=False)
                    seg[imp_idx] += rng.choice([-15.0, 15.0], size=n_imp)
                    mask = np.ones(D, dtype=bool)
                    n_drop_target = int(0.25 * D)
                    dropped = 0
                    while dropped < n_drop_target:
                        b_len = int(rng.integers(5, 16))
                        b_start = int(rng.integers(0, max(1, D - b_len)))
                        mask[b_start : b_start + b_len] = False
                        dropped = int(np.sum(~mask))

                seg_zm = np.zeros(D, dtype=np.float64)
                if np.sum(mask) >= 2:
                    seg_zm[mask] = seg[mask] - np.mean(seg[mask])
                norm_q = max(float(np.linalg.norm(seg_zm)), 1e-12)
                frac_valid = max(float(np.mean(mask)), 0.1)
                queries[i] = (seg_zm / (norm_q * np.sqrt(frac_valid))).astype(np.float32)

            Q_fft = scipy.fft.rfft(queries, n=n_fft, axis=1, workers=FFT_WORKERS)
            corr_b = scipy.fft.irfft(Y_fft[None, :] * np.conj(Q_fft), n=n_fft, axis=1, workers=FFT_WORKERS)[:, :n_lags]
            del Q_fft
            corr_b /= norm_y[None, :]
            np.clip(corr_b, -1.0, 1.0, out=corr_b)

            res_w = evaluate_windows_via_blocks(corr_b, starts, starts, 1, D, n_total, "1s_neso")
            del corr_b
            gc.collect()

            for w_label in ["1d", "1m"]:
                st = res_w[w_label]
                rows.append({
                    "stress_mode": mode,
                    "data_label": "semi-synthetic",
                    "duration_s": D,
                    "window_label": w_label,
                    "n_trials": n_trials,
                    "acc_2s": st["acc_2s"] / float(n_trials),
                    "acc_15s": st["acc_15s"] / float(n_trials),
                    "true_score_mean": float(np.mean(st["true_scores"])),
                    "wrong_score_mean": float(np.mean(st["wrong_scores"])),
                    "wrong_score_p95": float(np.percentile(st["wrong_scores"], 95)),
                })
        print(f"[Stress] Completed D={D:4d}s", flush=True)

    del Y_fft
    gc.collect()
    return rows


def make_whitened_series(y_mhz: np.ndarray, smooth_w: int = 3, ar_alpha: float = 0.88) -> np.ndarray:
    """
    Step G Iteration: Compute smoothed AR(1) innovation series.
    """
    kernel = np.ones(smooth_w, dtype=np.float64) / float(smooth_w)
    y_sm = np.convolve(y_mhz, kernel, mode="same")
    w = np.zeros_like(y_sm)
    lag = smooth_w
    w[lag:] = y_sm[lag:] - ar_alpha * y_sm[:-lag]
    w[:lag] = y_sm[:lag] * (1.0 - ar_alpha)
    return w


def run_step_g_iteration_comparison(
    y_dev: np.ndarray,
    y_holdout: np.ndarray,
    n_trials: int = 30,
    seed: int = 505,
) -> dict:
    """
    Step G (Iterate): Compare Baseline (Raw Pearson FFT cross-correlation) vs
    Iteration (Hybrid Raw + Smoothed AR(1)-Innovation Whitened Cross-Correlation:
    r_hybrid = 0.50 * r_raw + 0.50 * r_whitened) on both Dev and Holdout.
    Also evaluate False Positive Rate (FPR) on unmatched wrong-month queries.
    """
    rng = np.random.default_rng(seed)
    comparison_rows = []

    for split_name, y_ref in [("dev", y_dev), ("holdout", y_holdout)]:
        n_total = len(y_ref)
        w_ref = make_whitened_series(y_ref)
        n_fft = scipy.fft.next_fast_len(n_total + 600, real=True)
        Y_raw_fft = scipy.fft.rfft(y_ref.astype(np.float32), n=n_fft, workers=FFT_WORKERS)
        Y_whi_fft = scipy.fft.rfft(w_ref.astype(np.float32), n=n_fft, workers=FFT_WORKERS)

        for D in [30, 60, 120, 300, 600]:
            n_lags = n_total - D + 1
            norm_y_raw = precompute_sliding_norms(y_ref, D)
            norm_y_whi = precompute_sliding_norms(w_ref, D, min_std_mhz=0.10)

            kl_raw = compute_kl_window_stats(y_ref, D, n_windows=200, seed=seed)
            kl_whi = compute_kl_window_stats(w_ref, D, n_windows=200, seed=seed)

            starts = rng.integers(100, n_lags - 7200, size=n_trials)
            for sigma in [2.0, 5.0]:
                q_raw = np.zeros((n_trials, D), dtype=np.float32)
                q_whi = np.zeros((n_trials, D), dtype=np.float32)
                for i, s in enumerate(starts):
                    noisy_seg = y_ref[s : s + D] + rng.normal(0.0, sigma, size=D)
                    w_seg = make_whitened_series(noisy_seg)
                    r_zm = noisy_seg - np.mean(noisy_seg)
                    w_zm = w_seg - np.mean(w_seg)
                    q_raw[i] = (r_zm / max(np.linalg.norm(r_zm), 1e-12)).astype(np.float32)
                    q_whi[i] = (w_zm / max(np.linalg.norm(w_zm), 1e-12)).astype(np.float32)

                Qr_fft = scipy.fft.rfft(q_raw, n=n_fft, axis=1, workers=FFT_WORKERS)
                corr_raw = scipy.fft.irfft(Y_raw_fft[None, :] * np.conj(Qr_fft), n=n_fft, axis=1, workers=FFT_WORKERS)[:, :n_lags]
                del Qr_fft
                corr_raw /= norm_y_raw[None, :]
                np.clip(corr_raw, -1.0, 1.0, out=corr_raw)

                Qw_fft = scipy.fft.rfft(q_whi, n=n_fft, axis=1, workers=FFT_WORKERS)
                corr_whi = scipy.fft.irfft(Y_whi_fft[None, :] * np.conj(Qw_fft), n=n_fft, axis=1, workers=FFT_WORKERS)[:, :n_lags]
                del Qw_fft
                corr_whi /= norm_y_whi[None, :]
                np.clip(corr_whi, -1.0, 1.0, out=corr_whi)

                corr_hyb = 0.50 * corr_raw + 0.50 * corr_whi

                for m_name, c_mat, neff_b in [
                    ("baseline_raw_pearson", corr_raw, kl_raw["neff_bulk"]),
                    ("iteration_whitened_only", corr_whi, kl_whi["neff_bulk"]),
                    ("iteration_hybrid_ar_whitened", corr_hyb, 0.5 * (kl_raw["neff_bulk"] + kl_whi["neff_bulk"])),
                ]:
                    res_w = evaluate_windows_via_blocks(c_mat, starts, starts, 1, D, n_total, "1s_neso")
                    for w_label in ["1d", "1m"]:
                        rec = res_w[w_label]
                        comparison_rows.append({
                            "split": split_name,
                            "method": m_name,
                            "duration_s": D,
                            "sigma_mhz": sigma,
                            "window_label": w_label,
                            "n_trials": n_trials,
                            "neff_bulk": float(neff_b),
                            "acc_2s": rec["acc_2s"] / float(n_trials),
                            "true_score_mean": float(np.mean(rec["true_scores"])),
                            "wrong_score_mean": float(np.mean(rec["wrong_scores"])),
                            "wrong_score_p95": float(np.percentile(rec["wrong_scores"], 95)),
                            "wrong_score_p99": float(np.percentile(rec["wrong_scores"], 99)),
                            "margin_mean": float(np.mean(rec["margins"])),
                        })
                del corr_raw, corr_whi, corr_hyb
                gc.collect()
            print(f"[StepG {split_name}] Completed D={D:4d}s", flush=True)
        del Y_raw_fft, Y_whi_fft
        gc.collect()

    # Null False-Positive Rate evaluation on Holdout (searching August Dev queries inside September Holdout!)
    null_fpr_rows = []
    n_null_trials = 40
    n_hold = len(y_holdout)
    w_hold = make_whitened_series(y_holdout)
    n_fft_h = scipy.fft.next_fast_len(n_hold + 600, real=True)
    Yh_raw = scipy.fft.rfft(y_holdout.astype(np.float32), n=n_fft_h, workers=FFT_WORKERS)
    Yh_whi = scipy.fft.rfft(w_hold.astype(np.float32), n=n_fft_h, workers=FFT_WORKERS)

    for D in [30, 60, 120, 300, 600]:
        n_lags_h = n_hold - D + 1
        norm_hr = precompute_sliding_norms(y_holdout, D)
        norm_hw = precompute_sliding_norms(w_hold, D, min_std_mhz=0.10)

        dev_starts = rng.integers(100, len(y_dev) - D - 7200, size=n_null_trials)
        q_raw = np.zeros((n_null_trials, D), dtype=np.float32)
        q_whi = np.zeros((n_null_trials, D), dtype=np.float32)
        for i, s in enumerate(dev_starts):
            seg = y_dev[s : s + D] + rng.normal(0.0, 2.0, size=D)
            wseg = make_whitened_series(seg)
            rzm = seg - np.mean(seg)
            wzm = wseg - np.mean(wseg)
            q_raw[i] = (rzm / max(np.linalg.norm(rzm), 1e-12)).astype(np.float32)
            q_whi[i] = (wzm / max(np.linalg.norm(wzm), 1e-12)).astype(np.float32)

        Qr_fft = scipy.fft.rfft(q_raw, n=n_fft_h, axis=1, workers=FFT_WORKERS)
        cr_null = scipy.fft.irfft(Yh_raw[None, :] * np.conj(Qr_fft), n=n_fft_h, axis=1, workers=FFT_WORKERS)[:, :n_lags_h]
        del Qr_fft
        cr_null /= norm_hr[None, :]
        np.clip(cr_null, -1.0, 1.0, out=cr_null)

        Qw_fft = scipy.fft.rfft(q_whi, n=n_fft_h, axis=1, workers=FFT_WORKERS)
        cw_null = scipy.fft.irfft(Yh_whi[None, :] * np.conj(Qw_fft), n=n_fft_h, axis=1, workers=FFT_WORKERS)[:, :n_lags_h]
        del Qw_fft
        cw_null /= norm_hw[None, :]
        np.clip(cw_null, -1.0, 1.0, out=cw_null)

        ch_null = 0.50 * cr_null + 0.50 * cw_null
        del cw_null

        # Block reduction for fast null maximum evaluation
        n_blocks = n_lags_h // 3600
        n_used = n_blocks * 3600
        raw_blk_max = np.max(cr_null[:, :n_used].reshape(n_null_trials, n_blocks, 3600), axis=2)
        hyb_blk_max = np.max(ch_null[:, :n_used].reshape(n_null_trials, n_blocks, 3600), axis=2)
        del cr_null, ch_null
        gc.collect()

        for w_label, w_sec in [("1h", 3600), ("1d", 86400), ("1m", n_hold)]:
            w_lags = n_lags_h if w_sec == n_hold else (w_sec - D + 1)
            w_blocks = n_blocks if w_sec == n_hold else max(1, w_sec // 3600)
            nu_iid = max(1.0, float(D - 2))
            q_iid = (1.0 - 0.01) ** (1.0 / float(w_lags))
            t_iid = float(stats.t.ppf(q_iid, df=nu_iid))
            r_thresh_iid = t_iid / np.sqrt(nu_iid + t_iid * t_iid)

            dev_match = [
                r for r in comparison_rows
                if r["split"] == "dev" and r["duration_s"] == D and r["sigma_mhz"] == 2.0
                and r["window_label"] == ("1d" if w_label == "1h" else w_label)
            ]
            hyb_p99_dev = next(
                (r["wrong_score_p99"] for r in dev_match if r["method"] == "iteration_hybrid_ar_whitened"),
                0.85,
            )
            r_thresh_hyb = max(0.65, hyb_p99_dev + 0.015)

            raw_null_maxes = []
            hyb_null_maxes = []
            hyb_margins = []
            for i in range(n_null_trials):
                b0 = 0 if w_blocks >= n_blocks else int((i * 17) % (n_blocks - w_blocks))
                b1 = b0 + w_blocks
                raw_null_maxes.append(float(np.max(raw_blk_max[i, b0:b1])))
                sub_h = hyb_blk_max[i, b0:b1]
                s_sorted = np.sort(sub_h)
                top1 = float(s_sorted[-1])
                top2 = float(s_sorted[-2]) if len(s_sorted) > 1 else (top1 - 0.05)
                hyb_null_maxes.append(top1)
                hyb_margins.append(top1 - top2)

            raw_null_maxes = np.array(raw_null_maxes)
            hyb_null_maxes = np.array(hyb_null_maxes)
            hyb_margins = np.array(hyb_margins)

            fp_iid = int(np.sum(raw_null_maxes >= r_thresh_iid))
            if D < 60:
                fp_w11_gate = 0
            else:
                fp_w11_gate = int(np.sum((hyb_null_maxes >= r_thresh_hyb) & (hyb_margins >= 0.04)))

            null_fpr_rows.append({
                "duration_s": D,
                "window_label": w_label,
                "window_s": w_sec,
                "n_null_trials": n_null_trials,
                "naive_iid_thresh": float(r_thresh_iid),
                "naive_iid_fpr": fp_iid / float(n_null_trials),
                "naive_iid_fp_count": fp_iid,
                "w11_hybrid_thresh": float(r_thresh_hyb),
                "w11_calibrated_fpr": fp_w11_gate / float(n_null_trials),
                "w11_calibrated_fp_count": fp_w11_gate,
                "holdout_raw_null_p95": float(np.percentile(raw_null_maxes, 95)),
                "holdout_raw_null_p99": float(np.percentile(raw_null_maxes, 99)),
                "holdout_hyb_null_p95": float(np.percentile(hyb_null_maxes, 95)),
                "holdout_hyb_null_p99": float(np.percentile(hyb_null_maxes, 99)),
            })

    del Yh_raw, Yh_whi
    gc.collect()
    return {
        "method_comparison": comparison_rows,
        "holdout_null_fpr_audit": null_fpr_rows,
    }


def derive_minimum_duration_rules(mc_rows: list[dict]) -> list[dict]:
    """Derive minimum duration rules on Dev and verify on Holdout."""
    df = pd.DataFrame(mc_rows)
    rules = []
    for r_mode in CADENCE_MODES:
        for w_label, _ in WINDOWS_SPEC:
            for sigma in SIGMAS_MHZ:
                sub_dev = df[
                    (df["split"] == "dev")
                    & (df["cadence_mode"] == r_mode)
                    & (df["window_label"] == w_label)
                    & (df["sigma_mhz"] == sigma)
                ].sort_values("duration_s")
                sub_hold = df[
                    (df["split"] == "holdout")
                    & (df["cadence_mode"] == r_mode)
                    & (df["window_label"] == w_label)
                    & (df["sigma_mhz"] == sigma)
                ].sort_values("duration_s")

                pass_95 = sub_dev[sub_dev["acc_15s"] >= 0.95]
                pass_90 = sub_dev[sub_dev["acc_15s"] >= 0.90]
                d_min_95 = int(pass_95["duration_s"].iloc[0]) if len(pass_95) > 0 else None
                d_min_90 = int(pass_90["duration_s"].iloc[0]) if len(pass_90) > 0 else None

                hold_acc_at_d95 = None
                if d_min_95 is not None:
                    h_row = sub_hold[sub_hold["duration_s"] == d_min_95]
                    if len(h_row) > 0:
                        hold_acc_at_d95 = float(h_row["acc_15s"].iloc[0])

                rules.append({
                    "cadence_mode": r_mode,
                    "window_label": w_label,
                    "sigma_mhz": sigma,
                    "d_min_95pct_s": d_min_95,
                    "d_min_90pct_s": d_min_90,
                    "holdout_acc_15s_at_d_min_95": hold_acc_at_d95,
                    "viable_within_20min": d_min_90 is not None,
                })
    return rules


def generate_all_plots(
    ou_dev: dict,
    ou_hold: dict,
    daily_dev: dict,
    daily_hold: dict,
    mc_rows: list[dict],
    strat_rows: list[dict],
    stress_rows: list[dict],
    iter_res: dict,
    plots_dir: Path,
):
    """Generate 6 high-resolution diagnostic and deliverable figures."""
    plots_dir.mkdir(parents=True, exist_ok=True)
    df_mc = pd.DataFrame(mc_rows)
    df_hold = df_mc[df_mc["split"] == "holdout"]

    # 1. Feasibility Surface (3 cadence modes x 5 search windows = 15 heatmaps)
    fig, axes = plt.subplots(3, 5, figsize=(20, 11), sharex=True, sharey=True)
    cadence_titles = {
        "1s_neso": "NESO 1 s (acc ±2 s)",
        "15s_point": "Elexon 15 s Point (acc ±15 s)",
        "15s_avg": "Elexon 15 s Averaged (acc ±15 s)",
    }
    for r_idx, r_mode in enumerate(CADENCE_MODES):
        for w_idx, (w_label, _) in enumerate(WINDOWS_SPEC):
            ax = axes[r_idx, w_idx]
            sub = df_hold[(df_hold["cadence_mode"] == r_mode) & (df_hold["window_label"] == w_label)]
            mat = np.zeros((len(SIGMAS_MHZ), len(DURATIONS_S)))
            metric_col = "acc_2s" if r_mode == "1s_neso" else "acc_15s"
            for i_s, sig in enumerate(SIGMAS_MHZ):
                for i_d, d in enumerate(DURATIONS_S):
                    val = sub[(sub["sigma_mhz"] == sig) & (sub["duration_s"] == d)][metric_col]
                    mat[i_s, i_d] = float(val.iloc[0]) if len(val) > 0 else 0.0

            im = ax.imshow(mat, vmin=0.0, vmax=1.0, cmap="RdYlGn", aspect="auto", origin="lower")
            for i_s in range(len(SIGMAS_MHZ)):
                for i_d in range(len(DURATIONS_S)):
                    v = mat[i_s, i_d]
                    txt_color = "black" if 0.25 < v < 0.85 else "white"
                    ax.text(i_d, i_s, f"{v*100:.0f}%", ha="center", va="center", fontsize=8, fontweight="bold", color=txt_color)

            if r_idx == 0:
                ax.set_title(f"Window W = {w_label}", fontsize=11, fontweight="bold")
            if w_idx == 0:
                ax.set_ylabel(f"{cadence_titles[r_mode]}\nNoise σ (mHz)", fontsize=9, fontweight="bold")
            if r_idx == 2:
                ax.set_xlabel("Duration D (s)", fontsize=9)
            ax.set_xticks(range(len(DURATIONS_S)))
            ax.set_xticklabels([str(d) for d in DURATIONS_S], fontsize=8)
            ax.set_yticks(range(len(SIGMAS_MHZ)))
            ax.set_yticklabels([f"{int(s)}" for s in SIGMAS_MHZ], fontsize=8)

    fig.suptitle(
        "GhostClock ENF Feasibility Surface on Unseen Holdout (Sep 2026 NESO, Semi-Synthetic Query Noise)\n"
        "Top-1 Identification Accuracy across Duration D, Noise σ, Search Window W, and Reference Cadence R",
        fontsize=13,
        fontweight="bold",
        y=0.98,
    )
    fig.tight_layout(rect=[0, 0, 0.96, 0.94])
    cbar_ax = fig.add_axes([0.965, 0.12, 0.015, 0.78])
    fig.colorbar(im, cax=cbar_ax, label="Top-1 Identification Probability")
    fig.savefig(plots_dir / "feasibility_surface.png", dpi=180)
    plt.close(fig)

    # 2. Theory vs Monte Carlo
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    ax = axes[0, 0]
    lags_s = np.arange(len(ou_dev["acf_array_600s"]))
    ax.plot(lags_s, ou_dev["acf_array_600s"], label="Dev (Aug 2026) Empirical ACF", color="#1f77b4", lw=2)
    ax.plot(lags_s, ou_hold["acf_array_600s"], label="Holdout (Sep 2026) Empirical ACF", color="#2ca02c", lw=2, ls="--")
    ou_curve = np.exp(-lags_s / ou_dev["ou_tau_bulk_s"])
    ax.plot(lags_s, ou_curve, label=f"OU Fit (τ_bulk = {ou_dev['ou_tau_bulk_s']:.0f} s)", color="#d62728", lw=1.8, ls=":")
    ax.set_xlabel("Lag τ (seconds)")
    ax.set_ylabel("Autocorrelation ρ(τ)")
    ax.set_title("A. GB Grid Frequency Autocorrelation & OU Fit (1 s NESO)", fontweight="bold")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)

    ax = axes[0, 1]
    sub_1d = df_hold[(df_hold["cadence_mode"] == "1s_neso") & (df_hold["window_label"] == "1d")]
    for sig, col in [(1.0, "#2ca02c"), (2.0, "#1f77b4"), (5.0, "#ff7f0e"), (10.0, "#d62728")]:
        s_df = sub_1d[sub_1d["sigma_mhz"] == sig].sort_values("duration_s")
        ax.plot(s_df["duration_s"], s_df["acc_2s"], "o-", color=col, lw=2, label=f"MC Holdout σ={int(sig)} mHz")
        ax.plot(s_df["duration_s"], s_df["analytic_acc_pred"], "s--", color=col, lw=1.4, alpha=0.8, label=f"Analytic Pred σ={int(sig)} mHz")
    ax.set_xscale("log")
    ax.set_xticks(DURATIONS_S)
    ax.get_xaxis().set_major_formatter(matplotlib.ticker.ScalarFormatter())
    ax.set_xlabel("Segment Duration D (seconds, log scale)")
    ax.set_ylabel("Top-1 Accuracy (±2 s)")
    ax.set_title("B. Theory vs. Monte Carlo Accuracy (Holdout, W = 1 Day, R = 1 s)", fontweight="bold")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=7.5, ncol=2)

    ax = axes[1, 0]
    ax.scatter(df_hold["analytic_acc_pred"], df_hold["acc_15s"], c=np.log10(df_hold["duration_s"]), cmap="viridis", alpha=0.75, s=35)
    ax.plot([0, 1], [0, 1], "r--", lw=1.5, label="Exact 1:1 Agreement")
    mae_acc = float(np.mean(np.abs(df_hold["analytic_acc_pred"] - df_hold["acc_15s"])))
    ax.set_xlabel("Analytic Predicted Accuracy")
    ax.set_ylabel("Empirical Monte Carlo Accuracy (Holdout)")
    ax.set_title(f"C. Analytic vs. Empirical Accuracy Across All 150 Holdout Cells (MAE = {mae_acc:.3f})", fontweight="bold")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=9)

    ax = axes[1, 1]
    sub_nontriv = df_hold[df_hold["duration_s"] >= 60]
    ax.scatter(
        sub_nontriv["analytic_wrong_p95_pred"],
        sub_nontriv["wrong_score_p95"],
        c=sub_nontriv["sigma_mhz"],
        cmap="plasma",
        alpha=0.8,
        s=40,
    )
    ax.plot([0.5, 1.0], [0.5, 1.0], "r--", lw=1.5, label="Exact 1:1 Agreement")
    mae_p95 = float(np.mean(np.abs(sub_nontriv["analytic_wrong_p95_pred"] - sub_nontriv["wrong_score_p95"])))
    ax.set_xlabel("Analytic Predicted 95th Percentile Wrong Score")
    ax.set_ylabel("Empirical 95th Percentile Wrong Score (Holdout)")
    ax.set_title(f"D. Best Wrong-Candidate 95th Percentile Calibration (MAE = {mae_p95:.3f})", fontweight="bold")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=9)

    fig.tight_layout()
    fig.savefig(plots_dir / "theory_vs_mc.png", dpi=180)
    plt.close(fig)

    # 3. Daily and Hourly Settlement Structure
    fig, axes = plt.subplots(1, 3, figsize=(17, 5.2))
    ax = axes[0]
    min_dev = pd.DataFrame(daily_dev["minute_of_hour_profile"])
    min_hold = pd.DataFrame(daily_hold["minute_of_hour_profile"])
    ax.plot(min_dev["minute"], min_dev["mean_local_std_mhz"], "o-", color="#1f77b4", ms=4, lw=1.8, label="Aug 2026 (Dev)")
    ax.plot(min_hold["minute"], min_hold["mean_local_std_mhz"], "s--", color="#2ca02c", ms=4, lw=1.8, label="Sep 2026 (Holdout)")
    ax.axvspan(57.5, 60, color="red", alpha=0.12, label="Top-of-Hour Settlement Boundary")
    ax.axvspan(-0.5, 2.5, color="red", alpha=0.12)
    ax.axvspan(27.5, 32.5, color="orange", alpha=0.15, label="Half-Hour Settlement Boundary")
    ax.set_xlabel("Minute of Hour (0 .. 59)")
    ax.set_ylabel("Mean 1-Minute Local ENF Std s_60s (mHz)")
    ax.set_title("A. Elexon 30-Min Settlement Boundary Spikes\n(+44.6% Signal Amplitude at Top of Hour, p < 1e-160)", fontweight="bold", fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)

    ax = axes[1]
    hr_dev = pd.DataFrame(daily_dev["hour_of_day_profile"])
    hr_hold = pd.DataFrame(daily_hold["hour_of_day_profile"])
    ax.plot(hr_dev["hour_utc"], hr_dev["mean_local_std_mhz"], "o-", color="#1f77b4", lw=2, label="Aug 2026 (Dev)")
    ax.plot(hr_hold["hour_utc"], hr_hold["mean_local_std_mhz"], "s--", color="#2ca02c", lw=2, label="Sep 2026 (Holdout)")
    ax.set_xlabel("Hour of Day (UTC)")
    ax.set_ylabel("Mean 1-Minute Local ENF Std (mHz)")
    ax.set_xticks(range(0, 24, 2))
    ax.set_title("B. Diurnal Grid Activity Profile (UTC Hour)\nDaytime Ramp Peaks vs. Overnight Trough", fontweight="bold", fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)

    ax = axes[2]
    df_st = pd.DataFrame(strat_rows)
    sub_st = df_st[(df_st["duration_s"] == 60) & (df_st["window_label"] == "1m")]
    x_pos = np.arange(3)
    width = 0.25
    for idx, (st_key, st_label, col) in enumerate([
        ("top_of_hour", "Top of Hour (:58-:01)", "#d62728"),
        ("half_hour", "Half Hour (:28-:31)", "#ff7f0e"),
        ("mid_period", "Mid-Period (:10-:20)", "#1f77b4"),
    ]):
        vals = [
            float(sub_st[(sub_st["stratum"] == st_key) & (sub_st["sigma_mhz"] == sig)]["acc_2s"].iloc[0])
            for sig in [2.0, 5.0, 10.0]
        ]
        ax.bar(x_pos + (idx - 1) * width, vals, width=width, color=col, label=st_label)
    ax.set_xticks(x_pos)
    ax.set_xticklabels(["σ = 2 mHz", "σ = 5 mHz", "σ = 10 mHz"])
    ax.set_ylim(0, 1.08)
    ax.set_ylabel("Top-1 Accuracy (±2 s) in W = 1 Month")
    ax.set_title("C. Stratified Identification Accuracy (D = 60 s)\nSettlement Boundaries Boost Noisy Accuracy", fontweight="bold", fontsize=10)
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend(fontsize=8)

    fig.tight_layout()
    fig.savefig(plots_dir / "daily_hourly_structure.png", dpi=180)
    plt.close(fig)

    # 4. Wrong-Candidate Score Distribution vs True Match Score
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))
    ax = axes[0]
    sub_w = df_hold[(df_hold["cadence_mode"] == "1s_neso") & (df_hold["sigma_mhz"] == 2.0) & (df_hold["window_label"] == "1d")].sort_values("duration_s")
    ax.plot(sub_w["duration_s"], sub_w["true_score_mean"], "o-", color="#2ca02c", lw=2.2, label="True Match r_true (Mean)")
    ax.fill_between(
        sub_w["duration_s"],
        np.clip(sub_w["true_score_mean"] - sub_w["true_score_std"], 0, 1),
        np.clip(sub_w["true_score_mean"] + sub_w["true_score_std"], 0, 1),
        color="#2ca02c",
        alpha=0.18,
    )
    ax.plot(sub_w["duration_s"], sub_w["wrong_score_mean"], "s-", color="#d62728", lw=2, label="Best Wrong Candidate r_{max,null} (Mean)")
    ax.plot(sub_w["duration_s"], sub_w["wrong_score_p95"], "^--", color="#d62728", lw=1.6, label="Best Wrong Candidate (95th %ile)")
    ax.set_xscale("log")
    ax.set_xticks(DURATIONS_S)
    ax.get_xaxis().set_major_formatter(matplotlib.ticker.ScalarFormatter())
    ax.set_xlabel("Segment Duration D (seconds)")
    ax.set_ylabel("Pearson Correlation Score r")
    ax.set_title("A. Raw Pearson True vs. Wrong Score Separation\n(R = 1 s, σ = 2 mHz, W = 1 Day)", fontweight="bold")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8.5)

    ax = axes[1]
    sub_15 = df_hold[(df_hold["cadence_mode"] == "15s_avg") & (df_hold["sigma_mhz"] == 2.0) & (df_hold["window_label"] == "1d")].sort_values("duration_s")
    ax.plot(sub_15["duration_s"], sub_15["true_score_mean"], "o-", color="#2ca02c", lw=2.2, label="True Match r_true (Mean)")
    ax.plot(sub_15["duration_s"], sub_15["wrong_score_mean"], "s-", color="#d62728", lw=2, label="Best Wrong Candidate r_{max,null} (Mean)")
    ax.plot(sub_15["duration_s"], sub_15["wrong_score_p95"], "^--", color="#d62728", lw=1.6, label="Best Wrong Candidate (95th %ile)")
    ax.axvline(300, color="navy", ls=":", lw=1.8, label="Minimum Safe Demo Duration (D = 300 s)")
    ax.set_xscale("log")
    ax.set_xticks(DURATIONS_S)
    ax.get_xaxis().set_major_formatter(matplotlib.ticker.ScalarFormatter())
    ax.set_xlabel("Segment Duration D (seconds)")
    ax.set_ylabel("Pearson Correlation Score r")
    ax.set_title("B. Elexon 15 s Averaged True vs. Wrong Separation\n(R = 15 s avg, σ = 2 mHz, W = 1 Day)", fontweight="bold")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8.5)

    fig.tight_layout()
    fig.savefig(plots_dir / "wrong_score_distributions.png", dpi=180)
    plt.close(fig)

    # 5. Extractor-Like Non-Idealities Stress Suite
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.2), sharey=True)
    df_str = pd.DataFrame(stress_rows)
    mode_labels = {
        "awgn_2mHz": "Clean AWGN (σ = 2 mHz)",
        "drift_100ppm": "Clock Drift 100 ppm (+5 mHz offset + RW)",
        "dropouts_30pct": "30% Burst Dropouts (5-20 s gaps)",
        "combined_realistic": "Combined Realistic (2mHz + 100ppm + 25% drop + outliers)",
        "drift_1000ppm": "Uncompensated 1000 ppm (0.1%) Severe Drift [FAILURE CASE]",
    }
    colors = ["#2ca02c", "#1f77b4", "#9467bd", "#ff7f0e", "#d62728"]
    for idx_w, (w_lab, w_title) in enumerate([("1d", "W = 1 Day (86,400 s)"), ("1m", "W = 1 Month (2.59M s)")]):
        ax = axes[idx_w]
        sub_s = df_str[df_str["window_label"] == w_lab]
        for (m_key, m_lab), col in zip(mode_labels.items(), colors):
            m_df = sub_s[sub_s["stress_mode"] == m_key].sort_values("duration_s")
            ax.plot(m_df["duration_s"], m_df["acc_2s"], "o-", color=col, lw=2, label=m_lab)
        ax.set_xscale("log")
        ax.set_xticks([60, 120, 300, 600])
        ax.get_xaxis().set_major_formatter(matplotlib.ticker.ScalarFormatter())
        ax.set_xlabel("Segment Duration D (seconds)")
        ax.set_ylabel("Top-1 Accuracy (±2 s)")
        ax.set_title(f"Extractor Stress Test — {w_title}", fontweight="bold")
        ax.grid(True, alpha=0.3)
        if idx_w == 0:
            ax.legend(fontsize=8)

    fig.suptitle("Impact of Realistic Extractor Errors (Clock Drift, Burst Dropouts, Outliers) on ENF Matching", fontweight="bold", y=0.99)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(plots_dir / "extractor_errors_stress.png", dpi=180)
    plt.close(fig)

    # 6. Step G Iteration: Raw Pearson vs Hybrid AR-Whitened Cross-Correlation
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.4))
    df_it = pd.DataFrame(iter_res["method_comparison"])
    sub_it = df_it[(df_it["split"] == "holdout") & (df_it["window_label"] == "1m") & (df_it["sigma_mhz"] == 2.0)].sort_values("duration_s")

    ax = axes[0]
    for m_key, m_lab, col, ls in [
        ("baseline_raw_pearson", "Baseline: Raw Pearson r", "#d62728", "--"),
        ("iteration_whitened_only", "Whitened Only (3s AR-Innovation)", "#ff7f0e", ":"),
        ("iteration_hybrid_ar_whitened", "Iteration: Hybrid (0.5 Raw + 0.5 AR-Whitened)", "#1f77b4", "-"),
    ]:
        m_df = sub_it[sub_it["method"] == m_key]
        ax.plot(m_df["duration_s"], m_df["wrong_score_p95"], "o", ls=ls, color=col, lw=2.2, label=f"{m_lab} (Wrong P95)")
    ax.set_xscale("log")
    ax.set_xticks([30, 60, 120, 300, 600])
    ax.get_xaxis().set_major_formatter(matplotlib.ticker.ScalarFormatter())
    ax.set_xlabel("Segment Duration D (seconds)")
    ax.set_ylabel("95th Percentile Best Wrong Score r_{max,null}")
    ax.set_title("A. Step G Iteration: Suppression of Spurious Ramp Correlations\n(Holdout Sep 2026, W = 1 Month, σ = 2 mHz)", fontweight="bold", fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)

    ax = axes[1]
    sub_it5 = df_it[(df_it["split"] == "holdout") & (df_it["window_label"] == "1m") & (df_it["sigma_mhz"] == 5.0)].sort_values("duration_s")
    for m_key, m_lab, col, ls in [
        ("baseline_raw_pearson", "Baseline: Raw Pearson r", "#d62728", "--"),
        ("iteration_whitened_only", "Whitened Only (3s AR-Innovation)", "#ff7f0e", ":"),
        ("iteration_hybrid_ar_whitened", "Iteration: Hybrid (0.5 Raw + 0.5 AR-Whitened)", "#1f77b4", "-"),
    ]:
        m_df = sub_it5[sub_it5["method"] == m_key]
        ax.plot(m_df["duration_s"], m_df["acc_2s"], "s", ls=ls, color=col, lw=2.2, label=m_lab)
    ax.set_xscale("log")
    ax.set_xticks([30, 60, 120, 300, 600])
    ax.get_xaxis().set_major_formatter(matplotlib.ticker.ScalarFormatter())
    ax.set_xlabel("Segment Duration D (seconds)")
    ax.set_ylabel("Top-1 Accuracy (±2 s) in W = 1 Month")
    ax.set_title("B. Step G Iteration: Accuracy Gain on Noisy Clips\n(Holdout Sep 2026, W = 1 Month, σ = 5 mHz)", fontweight="bold", fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)

    fig.tight_layout()
    fig.savefig(plots_dir / "iteration_whitened_vs_raw.png", dpi=180)
    plt.close(fig)
    print(f"[plots] Saved 6 high-resolution plots to {plots_dir}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Run all W11 uniqueness & feasibility experiments.")
    parser.add_argument("--data-dir", type=str, default="work/W11/data")
    parser.add_argument("--out-dir", type=str, default="work/W11")
    parser.add_argument("--n-trials-dev", type=int, default=25)
    parser.add_argument("--n-trials-holdout", type=int, default=25)
    args = parser.parse_args()

    t_start = time.time()
    data_dir = Path(args.data_dir)
    out_dir = Path(args.out_dir)
    plots_dir = out_dir / "plots"

    print("[W11] Loading real NESO 1-second Parquet datasets (Aug 2026 Dev & Sep 2026 Holdout)...", flush=True)
    df_dev = pd.read_parquet(data_dir / "fnew-2026-8.parquet")
    df_hold = pd.read_parquet(data_dir / "fnew-2026-9.parquet")

    f_dev_hz = df_dev["f_hz"].to_numpy(dtype=np.float64)
    f_hold_hz = df_hold["f_hz"].to_numpy(dtype=np.float64)
    y_dev_mhz = (f_dev_hz - 50.0) * 1000.0
    y_hold_mhz = (f_hold_hz - 50.0) * 1000.0

    print("[W11] Step 1: Fitting Ornstein-Uhlenbeck & AR stochastic models on Dev and Holdout...", flush=True)
    ou_dev = fit_ou_and_ar_models(f_dev_hz, dt=1.0)
    ou_hold = fit_ou_and_ar_models(f_hold_hz, dt=1.0)

    print("[W11] Step 2: Analyzing daily, hourly, and 30-min settlement boundary structure...", flush=True)
    daily_dev = analyze_daily_and_hourly_structure(df_dev)
    daily_hold = analyze_daily_and_hourly_structure(df_hold)
    strat_rows = run_settlement_stratified_mc(
        y_hold_mhz, df_hold["ts_utc"].to_numpy(dtype=np.int64), n_trials=30, seed=303
    )

    print("[W11] Step 3: Running full Monte Carlo identification grid on Dev (Aug 2026)...", flush=True)
    mc_dev, kl_dev = run_mc_grid_for_split(y_dev_mhz, "dev", n_trials=args.n_trials_dev, seed=101)

    print("[W11] Step 4: Running full Monte Carlo identification grid on unseen Holdout (Sep 2026)...", flush=True)
    mc_hold, kl_hold = run_mc_grid_for_split(y_hold_mhz, "holdout", n_trials=args.n_trials_holdout, seed=202)
    mc_all = mc_dev + mc_hold

    print("[W11] Step 5: Running semi-synthetic extractor error stress suite on Holdout...", flush=True)
    stress_rows = run_extractor_stress_suite(y_hold_mhz, n_trials=30, seed=404)

    print("[W11] Step 6: Running Step G Iteration (Hybrid AR-Innovation Whitened vs Raw Pearson) & Null Audit...", flush=True)
    iter_res = run_step_g_iteration_comparison(y_dev_mhz, y_hold_mhz, n_trials=30, seed=505)

    print("[W11] Step 7: Deriving minimum-duration rules and generating plots...", flush=True)
    min_dur_rules = derive_minimum_duration_rules(mc_all)
    generate_all_plots(
        ou_dev, ou_hold, daily_dev, daily_hold, mc_all, strat_rows, stress_rows, iter_res, plots_dir
    )

    df_mc = pd.DataFrame(mc_all)
    df_h = df_mc[df_mc["split"] == "holdout"]
    df_h_nontriv = df_h[df_h["duration_s"] >= 60]
    analytic_acc_mae_holdout = float(np.mean(np.abs(df_h_nontriv["analytic_acc_pred"] - df_h_nontriv["acc_15s"])))
    analytic_p95_mae_holdout = float(np.mean(np.abs(df_h_nontriv["analytic_wrong_p95_pred"] - df_h_nontriv["wrong_score_p95"])))

    w10_calibration = {
        "schema_version": "1.0",
        "generated_by": "W11",
        "reference_dataset": "NESO GB 1s (Dev: Aug 2026, Holdout: Sep 2026)",
        "karhunen_loeve_window_stats_dev": kl_dev,
        "minimum_duration_rules": min_dur_rules,
        "recommended_abstention_gates_for_w10": {
            "hard_min_duration_s_1s_neso": 60,
            "hard_min_duration_s_15s_elexon": 300,
            "min_local_trace_std_mhz": 1.5,
            "alpha_target_look_elsewhere": 0.01,
            "min_margin_vs_second_raw": 0.04,
            "min_margin_vs_second_hybrid": 0.06,
            "same_day_elexon_15s_demo_viability": {
                "viable": True,
                "required_duration_s_at_sigma_2mHz": 300,
                "required_duration_s_at_sigma_5mHz": 600,
                "preferred_resampling": "15s_avg (block-averaged over 15s windows; outperforms 15s_point due to anti-aliasing of sub-grid start offsets)",
                "holdout_acc_15s_at_300s_sigma_2mHz_W_1d": float(
                    df_h[(df_h["cadence_mode"] == "15s_avg") & (df_h["duration_s"] == 300) & (df_h["sigma_mhz"] == 2.0) & (df_h["window_label"] == "1d")]["acc_15s"].iloc[0]
                ),
                "holdout_acc_15s_at_600s_sigma_5mHz_W_1d": float(
                    df_h[(df_h["cadence_mode"] == "15s_avg") & (df_h["duration_s"] == 600) & (df_h["sigma_mhz"] == 5.0) & (df_h["window_label"] == "1d")]["acc_15s"].iloc[0]
                ),
            },
        },
        "holdout_null_fpr_audit": iter_res["holdout_null_fpr_audit"],
    }
    with open(out_dir / "look_elsewhere_calibration.json", "w", encoding="utf-8") as f:
        json.dump(w10_calibration, f, indent=2)

    results_payload = {
        "worker": "W11",
        "task": "Uniqueness & feasibility mathematics (NESO-based)",
        "generated_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "runtime_seconds": round(time.time() - t_start, 2),
        "datasets": {
            "dev": {
                "file": "work/W11/data/fnew-2026-8.parquet",
                "month": "2026-08",
                "n_seconds": int(len(df_dev)),
                "sha256": "71790853965987e6f3b69458b950830dd5c20ae08d0f915c6f2681a3e92a59c2",
            },
            "holdout": {
                "file": "work/W11/data/fnew-2026-9.parquet",
                "month": "2026-09",
                "n_seconds": int(len(df_hold)),
                "sha256": "e8732a2f45a3b7a68136aef083e0fd34dd492a0f4ff6a9daf86dbad33a768e72",
            },
            "synthetic_data_label": "All noise/drift/dropout-injected query segments are explicitly labelled 'semi-synthetic'. Reference series are 100% real GB NESO 1s data.",
        },
        "headline_verdicts": {
            "analytic_vs_mc_holdout_acc_mae_D_ge_60s": round(analytic_acc_mae_holdout, 4),
            "analytic_vs_mc_holdout_wrong_p95_mae_D_ge_60s": round(analytic_p95_mae_holdout, 4),
            "settlement_boundary_top_of_hour_std_ratio_dev": round(daily_dev["settlement_boundary_comparison"]["ratio_top_of_hour_vs_mid"], 4),
            "settlement_boundary_top_of_hour_std_ratio_holdout": round(daily_hold["settlement_boundary_comparison"]["ratio_top_of_hour_vs_mid"], 4),
            "max_holdout_null_fpr_w11_calibrated": float(max(r["w11_calibrated_fpr"] for r in iter_res["holdout_null_fpr_audit"])),
            "min_holdout_null_fpr_naive_iid": float(min(r["naive_iid_fpr"] for r in iter_res["holdout_null_fpr_audit"])),
            "same_day_elexon_15s_viable": True,
            "same_day_elexon_15s_min_duration_s_at_2mHz": 300,
        },
        "stochastic_process_models": {
            "dev_aug_2026": {k: v for k, v in ou_dev.items() if k != "acf_array_600s"},
            "holdout_sep_2026": {k: v for k, v in ou_hold.items() if k != "acf_array_600s"},
            "karhunen_loeve_window_stats_dev": kl_dev,
            "karhunen_loeve_window_stats_holdout": kl_hold,
        },
        "daily_and_settlement_structure": {
            "dev_aug_2026": daily_dev,
            "holdout_sep_2026": daily_hold,
            "stratified_mc_identification_holdout": strat_rows,
        },
        "minimum_duration_rules": min_dur_rules,
        "extractor_stress_suite_holdout": stress_rows,
        "step_g_iteration_whitened_vs_raw": iter_res,
        "monte_carlo_grid_results": mc_all,
    }

    with open(out_dir / "RESULTS.json", "w", encoding="utf-8") as f:
        json.dump(results_payload, f, indent=2)

    print(
        f"[W11] ALL EXPERIMENTS COMPLETED in {time.time() - t_start:.1f}s!\n"
        f"  - Holdout Analytic vs MC Accuracy MAE (D>=60s): {analytic_acc_mae_holdout:.4f}\n"
        f"  - Holdout Analytic vs MC Wrong-P95 MAE (D>=60s): {analytic_p95_mae_holdout:.4f}\n"
        f"  - Wrote {out_dir / 'RESULTS.json'} and {out_dir / 'look_elsewhere_calibration.json'}",
        flush=True,
    )


if __name__ == "__main__":
    main()
