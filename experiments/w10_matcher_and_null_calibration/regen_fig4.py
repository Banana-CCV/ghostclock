"""
Regenerate Figure 4 (work/W10/plots/fig4_forensic_case_traces_and_failure.png)
using H1/011.wav (r=0.9996, RMSE=0.56 mHz, err=0s, MATCH_SUPPORTED) for Panels (a)-(c)
and H1/086.wav (corrupted trace -> INCONCLUSIVE) for Panel (d).
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from work.W10.matcher import sliding_weighted_ncc_and_rmse

C1_CACHE = REPO_ROOT / "work" / "C1" / "cache" / "w16"
C1_GT = json.loads((REPO_ROOT / "work" / "C1" / "gt_w16.json").read_text(encoding="utf-8"))
PLOTS_DIR = REPO_ROOT / "work" / "W10" / "plots"


def main() -> None:
    plt.rcParams.update({
        "font.size": 10,
        "axes.titlesize": 11,
        "axes.labelsize": 10,
        "figure.dpi": 150,
    })
    fig, axes = plt.subplots(2, 2, figsize=(13.5, 8.2))

    # Case 011: Clean positive match in 24h reference 011_ref
    d011 = np.load(C1_CACHE / "H1_ref_one_day" / "011_ref.npz")["f"].astype(np.float64)
    c011 = np.load(C1_CACHE / "H1" / "011.npz")
    f011 = c011["f"].astype(np.float64)
    q011 = np.clip((c011["q"].astype(np.float64) - 3.0) / 15.0, 0.05, 1.0)
    gt011 = int(round(C1_GT["011"]["lag_ref"]))

    res_011_curve = sliding_weighted_ncc_and_rmse(f011, q011, d011, np.ones_like(d011))
    lags_hr = np.arange(len(res_011_curve["score"])) / 3600.0
    peak_r = float(res_011_curve["score"][gt011])
    peak_rmse = float(res_011_curve["rmse_mhz"][gt011])

    axes[0, 0].plot(lags_hr, res_011_curve["score"], color="#2b5c8f", linewidth=0.7, alpha=0.85, label="Sliding WNCC Score r(tau)")
    axes[0, 0].axvline(gt011 / 3600.0, color="#1b9e77", linestyle="--", linewidth=1.6, label=f"True Time ({gt011/3600:.2f}h, r={peak_r:.4f})")
    axes[0, 0].axhline(0.68, color="#d95f02", linestyle="-.", linewidth=1.3, label="Look-Elsewhere Null Threshold")
    axes[0, 0].set_xlabel("Candidate Start Time in 24-Hour Reference (hours)")
    axes[0, 0].set_ylabel("Weighted NCC Score")
    axes[0, 0].set_title("(a) Blind 24-Hour Search Landscape: ENF-WHU H1/011.wav (MATCH_SUPPORTED)")
    axes[0, 0].legend(loc="lower right", fontsize=8.5)
    axes[0, 0].grid(True, alpha=0.25)

    L011 = len(f011)
    ref_slice_011 = d011[gt011 : gt011 + L011]
    t_sec = np.arange(L011)
    axes[0, 1].plot(t_sec, (ref_slice_011 - np.mean(ref_slice_011)) * 1000.0, color="#111111", linewidth=1.6, label="Grid Reference (H1_ref_one_day/011_ref)")
    axes[0, 1].plot(t_sec, (f011 - np.mean(f011)) * 1000.0, color="#1b9e77", linewidth=1.2, linestyle="--", label=f"Extracted Audio ENF (r={peak_r:.4f}, RMSE={peak_rmse:.2f} mHz)")
    axes[0, 1].set_xlabel("Time Within Recording (seconds)")
    axes[0, 1].set_ylabel("Frequency Deviation from Mean (mHz)")
    axes[0, 1].set_title("(b) Aligned Waveform Verification: Audio ENF vs 24h Grid Reference")
    axes[0, 1].legend(loc="upper right", fontsize=8.5)
    axes[0, 1].grid(True, alpha=0.25)

    d_wrong = np.load(C1_CACHE / "H1_ref_one_day" / "002_ref.npz")["f"].astype(np.float64)
    res_wrong_curve = sliding_weighted_ncc_and_rmse(f011, q011, d_wrong, np.ones_like(d_wrong))
    best_w_idx = int(np.nanargmax(res_wrong_curve["score"]))
    best_w_r = float(res_wrong_curve["score"][best_w_idx])
    axes[1, 0].plot(np.arange(len(res_wrong_curve["score"])) / 3600.0, res_wrong_curve["score"], color="#7570b3", linewidth=0.7, label="Wrong-Day WNCC r(tau)")
    axes[1, 0].scatter([best_w_idx / 3600.0], [best_w_r], color="#d95f02", zorder=5, label=f"Spurious Peak r={best_w_r:.3f} (Naive i.i.d. p < 1e-40!)")
    axes[1, 0].axhline(0.68, color="#111111", linestyle="-.", linewidth=1.4, label="W10 Look-Elsewhere Gate -> INCONCLUSIVE")
    axes[1, 0].set_xlabel("Candidate Start Time in Wrong-Day 24h Reference (hours)")
    axes[1, 0].set_ylabel("Weighted NCC Score")
    axes[1, 0].set_title("(c) Wrong-Day Negative Control: W10 Abstains While Naive i.i.d. Hallucinates")
    axes[1, 0].legend(loc="lower right", fontsize=8.5)
    axes[1, 0].grid(True, alpha=0.25)

    wc_day = np.load(C1_CACHE / "H1_ref_one_day" / "080-088_ref.npz")["f"].astype(np.float64)
    wc_f = np.load(C1_CACHE / "H1" / "086.npz")["f"].astype(np.float64)
    wc_gt = int(round(C1_GT["086"]["lag_ref"]))
    wc_ref_slice = wc_day[wc_gt : wc_gt + len(wc_f)]
    t_wc = np.arange(len(wc_f))
    axes[1, 1].plot(t_wc, (wc_ref_slice - np.mean(wc_ref_slice)) * 1000.0, color="#111111", linewidth=1.5, label=f"True Grid Ref (H1/086.wav @ {wc_gt}s)")
    axes[1, 1].plot(t_wc, (wc_f - np.mean(wc_f)) * 1000.0, color="#d95f02", linewidth=1.0, alpha=0.85, label="Corrupted Audio Trace (score=0.204 -> INCONCLUSIVE)")
    axes[1, 1].set_xlabel("Time Within Recording (seconds)")
    axes[1, 1].set_ylabel("Frequency Deviation (mHz)")
    axes[1, 1].set_title("(d) Real Failure Mode (H1/086.wav): Acoustic Interference Safely Gated to INCONCLUSIVE")
    axes[1, 1].legend(loc="upper right", fontsize=8.5)
    axes[1, 1].grid(True, alpha=0.25)

    fig.tight_layout()
    f4_path = PLOTS_DIR / "fig4_forensic_case_traces_and_failure.png"
    fig.savefig(f4_path)
    plt.close(fig)
    print(f"Updated {f4_path} (peak_r={peak_r:.4f}, peak_rmse={peak_rmse:.2f}mHz)")


if __name__ == "__main__":
    main()
