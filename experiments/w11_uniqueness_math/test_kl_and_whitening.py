"""
test_kl_and_whitening.py — Verify updated Subspace Projection & Karhunen-Loeve
Extreme-Value analytic predictions against empirical Monte Carlo values on Dev.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import pandas as pd
from work.W11.model_theory import compute_kl_window_stats, analytic_uniqueness_prediction


def main():
    df_dev = pd.read_parquet("work/W11/data/fnew-2026-8.parquet")
    y = (df_dev["f_hz"].to_numpy(dtype=np.float64) - 50.0) * 1000.0
    n_total = len(y)

    for D in [30, 60, 120, 300, 600, 1200]:
        kl = compute_kl_window_stats(y, D, n_windows=400, seed=42)
        for sigma in [2.0, 5.0]:
            for W in [86400, n_total]:
                pred = analytic_uniqueness_prediction(D, W, sigma, 1, kl)
                print(
                    f"D={D:4d}s sig={sigma:4.1f} W={W:7d} | Neff_tail={pred['neff_tail']:5.1f} | "
                    f"TrueMean={pred['pred_true_mean']:.3f} | WrongMean={pred['pred_wrong_mean']:.3f} "
                    f"WrongP95={pred['pred_wrong_p95']:.3f} | PredAcc={pred['pred_acc']:.3f}"
                )


if __name__ == "__main__":
    main()
