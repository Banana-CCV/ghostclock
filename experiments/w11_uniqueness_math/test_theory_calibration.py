"""
test_theory_calibration.py — Verify local detrended ACF, Bartlett N_eff, and
analytic extreme-value predictions against a fast pilot Monte Carlo on Dev (Aug 2026).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import pandas as pd
import scipy.fft
from work.W11.model_theory import (
    compute_local_detrended_acf,
    compute_bartlett_neff,
    analytic_uniqueness_prediction,
)


def main():
    df_dev = pd.read_parquet("work/W11/data/fnew-2026-8.parquet")
    f = df_dev["f_hz"].to_numpy(dtype=np.float64)
    n_total = len(f)

    rng = np.random.default_rng(42)
    n_trials = 60
    n_fft = scipy.fft.next_fast_len(n_total + 1200, real=True)
    Y_fft = scipy.fft.rfft(f, n=n_fft, workers=-1)

    cs1 = np.concatenate(([0.0], np.cumsum(f)))
    cs2 = np.concatenate(([0.0], np.cumsum(f * f)))

    for D in [30, 60, 120, 300, 600]:
        n_lags = n_total - D + 1
        sum_y = cs1[D : D + n_lags] - cs1[:n_lags]
        sum_y2 = cs2[D : D + n_lags] - cs2[:n_lags]
        var_y = np.maximum(sum_y2 - (sum_y * sum_y) / D, 1e-16)
        norm_y = np.sqrt(var_y)

        acf_loc, m_std, sd_std = compute_local_detrended_acf(f, D, n_windows=500, seed=42)
        neff0 = compute_bartlett_neff(D, acf_loc, m_std, 0.0)

        starts = rng.integers(0, n_lags, size=n_trials)
        queries = np.zeros((n_trials, D), dtype=np.float64)
        for i, s in enumerate(starts):
            seg = f[s : s + D] + rng.normal(0.0, 0.002, size=D)
            seg_zm = seg - np.mean(seg)
            queries[i] = seg_zm / max(np.linalg.norm(seg_zm), 1e-12)

        Q_fft = scipy.fft.rfft(queries, n=n_fft, axis=1, workers=-1)
        corr_full = scipy.fft.irfft(Y_fft[None, :] * np.conj(Q_fft), n=n_fft, axis=1, workers=-1)[:, :n_lags]
        corr_full /= norm_y[None, :]

        # Check W = 1 day (86400s) and W = 1 month
        for W in [3600, 86400, n_total]:
            wrong_maxes = []
            correct_2s = 0
            for i, s in enumerate(starts):
                if W == n_total:
                    a, b = 0, n_lags
                else:
                    w_lags = max(1, W - D + 1)
                    a = max(0, min(n_lags - w_lags, s - w_lags // 2))
                    b = a + w_lags
                r_win = corr_full[i, a:b].copy()
                best_idx = int(np.argmax(r_win)) + a
                if abs(best_idx - s) <= 2:
                    correct_2s += 1
                excl_lo = max(a, s - max(D, 60))
                excl_hi = min(b, s + max(D, 60) + 1)
                r_win[excl_lo - a : excl_hi - a] = -1.0
                wrong_maxes.append(float(np.max(r_win)))

            emp_acc = correct_2s / n_trials
            emp_w_mean = float(np.mean(wrong_maxes))
            emp_w_p95 = float(np.percentile(wrong_maxes, 95))
            pred = analytic_uniqueness_prediction(D, W, 2.0, 1, acf_loc, m_std, sd_std)
            print(
                f"D={D:4d}s W={W:7d}s | Neff0={neff0:5.1f} Neff2={pred['neff']:5.1f} | "
                f"Acc emp={emp_acc:.3f} pred={pred['pred_acc']:.3f} | "
                f"WrongMean emp={emp_w_mean:.3f} pred={pred['pred_wrong_mean']:.3f} | "
                f"WrongP95 emp={emp_w_p95:.3f} pred={pred['pred_wrong_p95']:.3f}"
            )


if __name__ == "__main__":
    main()
