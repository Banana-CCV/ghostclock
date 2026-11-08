"""
inspect_null_tail.py — Fix the (f - 50.0) centering and measure exact empirical null
and true-match correlation distributions across D, sigma, W, R on Dev (Aug 2026).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import pandas as pd
import scipy.fft
from scipy import stats


def main():
    df_dev = pd.read_parquet("work/W11/data/fnew-2026-8.parquet")
    # Center around 50.0 Hz in mHz for maximum numerical precision!
    y = (df_dev["f_hz"].to_numpy(dtype=np.float64) - 50.0) * 1000.0
    n_total = len(y)

    rng = np.random.default_rng(42)
    n_trials = 80
    n_fft = scipy.fft.next_fast_len(n_total + 1200, real=True)
    Y_fft = scipy.fft.rfft(y, n=n_fft, workers=-1)

    cs1 = np.concatenate(([0.0], np.cumsum(y)))
    cs2 = np.concatenate(([0.0], np.cumsum(y * y)))

    for D in [30, 60, 120, 300, 600, 1200]:
        n_lags = n_total - D + 1
        sum_y = cs1[D : D + n_lags] - cs1[:n_lags]
        sum_y2 = cs2[D : D + n_lags] - cs2[:n_lags]
        var_y = np.maximum(sum_y2 - (sum_y * sum_y) / D, 0.04 * D)  # min 0.2 mHz std floor
        norm_y = np.sqrt(var_y)

        starts = rng.integers(0, n_lags, size=n_trials)
        q_clean = np.zeros((n_trials, D), dtype=np.float64)
        q_noise = np.zeros((n_trials, D), dtype=np.float64)
        seg_clean_zm = np.zeros((n_trials, D), dtype=np.float64)
        seg_noise_zm = np.zeros((n_trials, D), dtype=np.float64)

        for i, s in enumerate(starts):
            c_seg = y[s : s + D]
            n_seg = rng.normal(0.0, 1.0, size=D)
            seg_clean_zm[i] = c_seg - np.mean(c_seg)
            seg_noise_zm[i] = n_seg - np.mean(n_seg)

        C_fft = scipy.fft.rfft(seg_clean_zm, n=n_fft, axis=1, workers=-1)
        N_fft = scipy.fft.rfft(seg_noise_zm, n=n_fft, axis=1, workers=-1)
        A_clean = scipy.fft.irfft(Y_fft[None, :] * np.conj(C_fft), n=n_fft, axis=1, workers=-1)[:, :n_lags]
        A_noise = scipy.fft.irfft(Y_fft[None, :] * np.conj(N_fft), n=n_fft, axis=1, workers=-1)[:, :n_lags]

        for sigma in [0.0, 2.0, 5.0, 10.0]:
            q_comb = seg_clean_zm + sigma * seg_noise_zm
            q_norms = np.maximum(np.linalg.norm(q_comb, axis=1), 1e-12)
            corr_all = (A_clean + sigma * A_noise) / (q_norms[:, None] * norm_y[None, :])
            np.clip(corr_all, -1.0, 1.0, out=corr_all)

            # Sample random single-lag null correlations to inspect bulk vs tail
            sample_null = corr_all[:, ::1000].ravel()
            var_null = float(np.var(sample_null))
            neff_bulk = 1.0 / max(var_null, 1e-6)

            for W in [3600, 86400, n_total]:
                w_max = []
                true_scores = []
                acc2 = 0
                for i, s in enumerate(starts):
                    true_scores.append(float(corr_all[i, s]))
                    if W == n_total:
                        a, b = 0, n_lags
                    else:
                        w_lags = max(1, W - D + 1)
                        a = max(0, min(n_lags - w_lags, s - w_lags // 2))
                        b = a + w_lags
                    r_win = corr_all[i, a:b].copy()
                    best_idx = int(np.argmax(r_win)) + a
                    if abs(best_idx - s) <= 2:
                        acc2 += 1
                    excl_lo = max(a, s - max(D, 60))
                    excl_hi = min(b, s + max(D, 60) + 1)
                    r_win[excl_lo - a : excl_hi - a] = -1.0
                    w_max.append(float(np.max(r_win)))

                if W in [86400, n_total] and sigma in [2.0, 5.0]:
                    print(
                        f"D={D:4d}s sig={sigma:4.1f} W={W:7d} | Neff_bulk={neff_bulk:5.1f} | "
                        f"TrueMean={np.mean(true_scores):.3f} | WrongMean={np.mean(w_max):.3f} "
                        f"WrongP95={np.percentile(w_max, 95):.3f} | Acc2s={acc2/n_trials:.3f}"
                    )


if __name__ == "__main__":
    main()
