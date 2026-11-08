#!/usr/bin/env python3
"""
GhostClock Worker W06: Diagnostic & Publication Plot Generator
==============================================================
Generates the required scientific figures in `work/W06/plots/` from real
ENF-WHU Dev split runs (`work/W06/RESULTS.json` and `work/W06/audio_enf.py`):
1. `spectrogram_tracked_ridge.png`: Multi-harmonic narrowband spectrograms
   (100, 200, 300 Hz + weighted combined spectrum) with tracked ridge overlay,
   ground-truth reference trace, and time-varying harmonic weights.
2. `extracted_vs_reference_overlays.png`: Extracted vs reference ENF trace
   overlays across 4 representative Dev H1 recordings (clean multi-harmonic,
   corrupted 5th-harmonic recovery on 005.wav, moderate SNR, and failure case).
3. `error_histograms_and_ablations.png`: Frame-level frequency error (mHz)
   histograms, method ablation comparison, and STFT window-length trade-off curve.
4. `presence_roc_and_robustness.png`: ENF-presence ROC curves (Dev H1 vs H0),
   presence score distributions, FFmpeg MP3/AAC codec robustness, and AWGN curve.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from audio_enf import extract_audio_enf_detailed, extract_reference_enf, load_config

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = REPO_ROOT / "datasets" / "raw" / "enf-whu" / "repo" / "ENF-WHU-Dataset"
WORK_DIR = Path(__file__).resolve().parent
PLOTS_DIR = WORK_DIR / "plots"


def set_plot_style() -> None:
    plt.rcParams.update({
        "figure.dpi": 150,
        "savefig.dpi": 180,
        "font.size": 10,
        "axes.titlesize": 11,
        "axes.labelsize": 10,
        "legend.fontsize": 8.5,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "axes.grid": True,
        "grid.alpha": 0.3,
    })


def plot_spectrogram_with_ridge(cfg: Dict[str, Any]) -> Path:
    """Plot 1: Narrowband spectrograms, tracked ridge, reference trace, and harmonic weights."""
    cid = "003"
    wav_path = DATASET_DIR / "H1" / f"{cid}.wav"
    ref_path = DATASET_DIR / "H1_ref" / f"{cid}_ref.wav"

    res = extract_audio_enf_detailed(wav_path, cfg)
    t_ref, f_ref = extract_reference_enf(ref_path, window_s=cfg["window_s"], hop_s=cfg["hop_s"])

    t = res["t"]
    f_est = res["f_raw"]
    q = res["q"]
    f0_grid = res["f0_grid"]
    spec_combined = res["spec_combined"]
    norm_profiles = res["norm_profiles"]
    harmonics = res["harmonics"]
    w_harm = res["weights_harm"]

    n = min(len(t), len(f_ref))
    t = t[:n]
    f_est = f_est[:n]
    f_ref = f_ref[:n]
    q = q[:n]
    spec_combined = spec_combined[:n]

    r_val = float(np.corrcoef(f_est, f_ref)[0, 1])
    rmse_mhz = float(np.sqrt(np.mean((f_est - f_ref) ** 2)) * 1000.0)

    fig, axes = plt.subplots(4, 1, figsize=(11, 10.5), sharex=True, gridspec_kw={"height_ratios": [1.3, 1.3, 1.2, 0.9]})

    # Panel 1: 2nd Harmonic (100 Hz mapped to 50 Hz fundamental-equivalent) spectrogram
    idx_h2 = harmonics.index(2) if 2 in harmonics else 0
    spec_h2_db = 10.0 * np.log10(np.maximum(norm_profiles[idx_h2, :n, :].T, 1e-4))
    im0 = axes[0].pcolormesh(t, f0_grid, spec_h2_db, shading="auto", cmap="magma", vmin=-25, vmax=0)
    axes[0].plot(t, res["f_harm"][idx_h2, :n], color="#00e5ff", lw=1.1, alpha=0.85, label="2nd Harmonic Ridge (100 Hz / 2)")
    axes[0].plot(t, f_ref, color="#ffffff", lw=1.0, ls="--", alpha=0.85, label="Ground-Truth Reference (H1_ref)")
    axes[0].set_ylabel("Freq (Hz, eq. 50Hz)")
    axes[0].set_title(f"ENF-WHU H1/{cid}.wav — (a) 2nd Harmonic (100 Hz) Narrowband STFT Spectrogram & Tracked Ridge")
    axes[0].legend(loc="upper right", framealpha=0.85)
    fig.colorbar(im0, ax=axes[0], label="Norm. Power (dB)", pad=0.015)

    # Panel 2: Weighted Multi-Harmonic Combined Spectrogram + Tracked Ridge
    spec_comb_db = 10.0 * np.log10(np.maximum(spec_combined.T, 1e-4))
    im1 = axes[1].pcolormesh(t, f0_grid, spec_comb_db, shading="auto", cmap="viridis", vmin=-20, vmax=0)
    axes[1].plot(t, f_est, color="#ff3d00", lw=1.4, label=f"W06 Multi-Harmonic Ridge (r={r_val:.4f}, RMSE={rmse_mhz:.2f} mHz)")
    axes[1].plot(t, f_ref, color="#ffffff", lw=1.1, ls="--", alpha=0.9, label="Ground-Truth Reference")
    axes[1].set_ylabel("Freq (Hz, eq. 50Hz)")
    axes[1].set_title("(b) SNR-Weighted Multi-Harmonic Combined Spectrum & Tracked Fundamental-Equivalent Ridge")
    axes[1].legend(loc="upper right", framealpha=0.85)
    fig.colorbar(im1, ax=axes[1], label="Comb. Power (dB)", pad=0.015)

    # Panel 3: Direct Trace Overlay (zoomed in mHz around 50 Hz)
    axes[2].plot(t, (f_ref - 50.0) * 1000.0, color="#111111", lw=1.6, label="Reference ENF (H1_ref)")
    axes[2].plot(t, (res["f_harm"][idx_h2, :n] - 50.0) * 1000.0, color="#1e88e5", lw=1.0, alpha=0.65, label="Single Harmonic (100 Hz only)")
    axes[2].plot(t, (f_est - 50.0) * 1000.0, color="#d81b60", lw=1.3, label="W06 Multi-Harmonic Combined f(t)")
    axes[2].set_ylabel("Deviation (mHz)")
    axes[2].set_title("(c) Extracted vs. Reference Frequency Deviation Around 50.000 Hz")
    axes[2].legend(loc="upper right", ncol=3)
    # Add dummy colorbar spacer for alignment
    cbar_dummy2 = fig.colorbar(im1, ax=axes[2], pad=0.015)
    cbar_dummy2.ax.set_visible(False)

    # Panel 4: Per-Harmonic Dynamic Weights w_h(t) and Quality q(t)
    colors_h = ["#757575", "#1e88e5", "#8e24aa", "#43a047", "#fb8c00", "#e53935", "#00897b"]
    for idx_h, h in enumerate(harmonics):
        mw = float(np.mean(w_harm[idx_h, :n]))
        if mw >= 0.02 or h in {1, 2, 4, 6}:
            axes[3].plot(t, w_harm[idx_h, :n], lw=1.2, color=colors_h[idx_h % len(colors_h)], label=f"h={h} ({h*50} Hz, mean w={mw:.2f})")
    axes[3].plot(t, q, color="#000000", lw=1.4, ls=":", label=f"Frame Quality q(t) (med={np.median(q):.3f})")
    axes[3].set_ylim(-0.05, 1.08)
    axes[3].set_ylabel("Weight / Quality")
    axes[3].set_xlabel("Time from Media Start (s)")
    axes[3].set_title("(d) Dynamic Per-Harmonic Weights w_h(t) and Frame Quality Score q(t)")
    axes[3].legend(loc="upper right", ncol=4)
    cbar_dummy3 = fig.colorbar(im1, ax=axes[3], pad=0.015)
    cbar_dummy3.ax.set_visible(False)

    fig.tight_layout()
    out_path = PLOTS_DIR / "spectrogram_tracked_ridge.png"
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def plot_extracted_vs_reference_overlays(cfg: Dict[str, Any], results: Dict[str, Any]) -> Path:
    """Plot 2: Extracted vs Reference trace overlays across 4 representative Dev H1 recordings."""
    per_rec = results["diagnostics"]["per_recording_dev_h1"]
    rec_map = {r["id"]: r for r in per_rec}

    # Select 4 informative Dev H1 cases:
    # 1. Corrupted harmonic recovery showcase ('005' if in dev, else best clip)
    # 2. High-SNR multi-harmonic clip ('003' or top clip)
    # 3. Median-SNR typical clip
    # 4. Worst Dev H1 failure case (explainable low-SNR / interference failure)
    sorted_recs = sorted(per_rec, key=lambda x: x["r"], reverse=True)
    case_ids: List[str] = []
    for preferred in ["005", "003"]:
        if preferred in rec_map and preferred not in case_ids:
            case_ids.append(preferred)
    if len(case_ids) < 2:
        for r in sorted_recs[:3]:
            if r["id"] not in case_ids:
                case_ids.append(r["id"])
            if len(case_ids) == 2:
                break
    mid_rec = sorted_recs[len(sorted_recs) // 2]["id"]
    if mid_rec not in case_ids:
        case_ids.append(mid_rec)
    worst_rec = sorted_recs[-1]["id"]
    if worst_rec not in case_ids:
        case_ids.append(worst_rec)

    fig, axes = plt.subplots(len(case_ids), 1, figsize=(11, 9.5), sharex=False)
    if len(case_ids) == 1:
        axes = [axes]

    for ax, cid in zip(axes, case_ids):
        wav_path = DATASET_DIR / "H1" / f"{cid}.wav"
        ref_path = DATASET_DIR / "H1_ref" / f"{cid}_ref.wav"
        res = extract_audio_enf_detailed(wav_path, cfg)
        t_ref, f_ref = extract_reference_enf(ref_path, window_s=cfg["window_s"], hop_s=cfg["hop_s"])

        t = res["t"]
        n = min(len(t), len(f_ref))
        t = t[:n]
        f_ref = f_ref[:n]
        f_hyb = res["f_raw"][:n]
        f_unw = np.mean(res["f_harm"][:, :n], axis=0)
        idx_2 = res["harmonics"].index(2) if 2 in res["harmonics"] else 0
        f_100 = res["f_harm"][idx_2, :n]

        r_hyb = float(np.corrcoef(f_hyb, f_ref)[0, 1])
        rmse_hyb = float(np.sqrt(np.mean((f_hyb - f_ref) ** 2)) * 1000.0)
        r_100 = float(np.corrcoef(f_100, f_ref)[0, 1])
        rmse_100 = float(np.sqrt(np.mean((f_100 - f_ref) ** 2)) * 1000.0)
        r_unw = float(np.corrcoef(f_unw, f_ref)[0, 1])
        rmse_unw = float(np.sqrt(np.mean((f_unw - f_ref) ** 2)) * 1000.0)

        ax.plot(t, (f_ref - 50.0) * 1000.0, color="#111111", lw=1.7, label="Ground-Truth Reference (H1_ref)")
        ax.plot(
            t,
            (f_unw - 50.0) * 1000.0,
            color="#9e9e9e",
            lw=1.0,
            ls="--",
            alpha=0.75,
            label=f"Unweighted Multi-Harmonic (r={r_unw:.3f}, RMSE={rmse_unw:.1f} mHz)",
        )
        ax.plot(
            t,
            (f_100 - 50.0) * 1000.0,
            color="#1e88e5",
            lw=1.1,
            alpha=0.75,
            label=f"Single 100 Hz Baseline (r={r_100:.3f}, RMSE={rmse_100:.1f} mHz)",
        )
        ax.plot(
            t,
            (f_hyb - 50.0) * 1000.0,
            color="#d81b60",
            lw=1.5,
            label=f"W06 Weighted Multi-Harmonic (r={r_hyb:.3f}, RMSE={rmse_hyb:.1f} mHz, q={np.median(res['q']):.2f})",
        )
        ax.set_ylabel("f - 50 Hz (mHz)")
        ax.set_xlabel("Time from Media Start (s)")
        h_used = res["meta"]["harmonics_used"]
        ax.set_title(
            f"Dev H1/{cid}.wav — Active Harmonics {h_used} | SNR={res['meta']['quality_summary']['snr_db']:.1f} dB | "
            f"Presence Score={res['presence']['score']:.2f}"
        )
        ax.legend(loc="upper right", ncol=2)

    fig.tight_layout()
    out_path = PLOTS_DIR / "extracted_vs_reference_overlays.png"
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def plot_error_histograms_and_ablations(cfg: Dict[str, Any], results: Dict[str, Any]) -> Path:
    """Plot 3: Frame-level error histograms, recording-level method ablations, and window sweep."""
    cache_npz = WORK_DIR / "error_samples_cache.npz"
    if cache_npz.exists():
        c_data = np.load(cache_npz)
        e_hyb = c_data["e_hyb"]
        e_100 = c_data["e_100"]
        e_unw = c_data["e_unw"]
        e_50 = c_data["e_50"]
    else:
        per_rec = results["diagnostics"]["per_recording_dev_h1"]
        dev_ids = [r["id"] for r in per_rec]
        sample_ids = dev_ids[:: max(1, len(dev_ids) // 12)][:12]
        err_hyb_all, err_100_all, err_unw_all, err_50_all = [], [], [], []
        for cid in sample_ids:
            wav_path = DATASET_DIR / "H1" / f"{cid}.wav"
            ref_path = DATASET_DIR / "H1_ref" / f"{cid}_ref.wav"
            res = extract_audio_enf_detailed(wav_path, cfg)
            _, f_ref = extract_reference_enf(ref_path, window_s=cfg["window_s"], hop_s=cfg["hop_s"])
            n = min(len(res["f_raw"]), len(f_ref))
            f_r = f_ref[:n]
            err_hyb_all.append((res["f_raw"][:n] - f_r) * 1000.0)
            idx_2 = res["harmonics"].index(2) if 2 in res["harmonics"] else 0
            idx_1 = res["harmonics"].index(1) if 1 in res["harmonics"] else 0
            err_100_all.append((res["f_harm"][idx_2, :n] - f_r) * 1000.0)
            err_50_all.append((res["f_harm"][idx_1, :n] - f_r) * 1000.0)
            err_unw_all.append((np.mean(res["f_harm"][:, :n], axis=0) - f_r) * 1000.0)
        e_hyb = np.concatenate(err_hyb_all)
        e_100 = np.concatenate(err_100_all)
        e_unw = np.concatenate(err_unw_all)
        e_50 = np.concatenate(err_50_all)

    fig, axes = plt.subplots(2, 2, figsize=(12, 8.8))

    # Panel A: Frame-level error histogram (mHz)
    bins = np.linspace(-60, 60, 121)
    axes[0, 0].hist(e_50, bins=bins, density=True, alpha=0.35, color="#757575", label=f"Single 50 Hz (MAE={np.mean(np.abs(e_50)):.1f} mHz)")
    axes[0, 0].hist(e_unw, bins=bins, density=True, alpha=0.45, color="#fb8c00", label=f"Unweighted 1..6 (MAE={np.mean(np.abs(e_unw)):.1f} mHz)")
    axes[0, 0].hist(e_100, bins=bins, density=True, alpha=0.50, color="#1e88e5", label=f"Single 100 Hz (MAE={np.mean(np.abs(e_100)):.1f} mHz)")
    axes[0, 0].hist(e_hyb, bins=bins, density=True, alpha=0.65, color="#d81b60", label=f"W06 Weighted Hybrid (MAE={np.mean(np.abs(e_hyb)):.1f} mHz)")
    axes[0, 0].set_xlim(-60, 60)
    axes[0, 0].set_xlabel("Frame Estimation Error f_est(t) - f_ref(t) (mHz)")
    axes[0, 0].set_ylabel("Probability Density")
    axes[0, 0].set_title("(a) Frame-Level Frequency Error Histogram on Dev H1")
    axes[0, 0].legend(loc="upper right")

    # Panel B: Method Ablation Bar Chart (Median Pearson r & Median RMSE)
    abl = results["experiment_1_method_ablation_dev_h1"]
    m_keys = ["single_50hz", "unweighted_mean", "single_100hz", "wmle_spectral", "snr_weighted_trace", "snr_robust_hybrid"]
    m_labels = ["50 Hz\nOnly", "Unweighted\nMean (1..6)", "100 Hz\nBaseline", "WMLE\nSpectral", "SNR-Weighted\nTrace", "W06 Robust\nHybrid"]
    med_r = [abl[k]["pearson_r"]["median"] for k in m_keys]
    p25_r = [abl[k]["pearson_r"]["p25"] for k in m_keys]
    p75_r = [abl[k]["pearson_r"]["p75"] for k in m_keys]
    x_pos = np.arange(len(m_keys))
    bars = axes[0, 1].bar(
        x_pos,
        med_r,
        yerr=[np.array(med_r) - np.array(p25_r), np.array(p75_r) - np.array(med_r)],
        capsize=4,
        color=["#9e9e9e", "#ffb74d", "#64b5f6", "#4db6ac", "#7986cb", "#d81b60"],
        edgecolor="#222222",
    )
    axes[0, 1].axhline(0.70, color="#2e7d32", ls="--", lw=1.2, label="Pre-Declared Gate (r >= 0.70)")
    axes[0, 1].set_xticks(x_pos)
    axes[0, 1].set_xticklabels(m_labels, fontsize=8.5)
    axes[0, 1].set_ylim(0.0, 1.08)
    axes[0, 1].set_ylabel("Median Pearson r (with IQR)")
    axes[0, 1].set_title(f"(b) Multi-Harmonic Method Ablation on Dev H1 (N={abl['snr_robust_hybrid']['n_recordings']})")
    for b, v in zip(bars, med_r):
        axes[0, 1].text(b.get_x() + b.get_width() / 2.0, v + 0.02, f"{v:.3f}", ha="center", va="bottom", fontsize=8.5, fontweight="bold")
    axes[0, 1].legend(loc="lower right")

    # Panel C: Effect of STFT Window Length (4, 8, 12, 16, 24 s)
    ws = results["experiment_2_window_length_sweep_dev_h1"]
    w_keys = ["4s", "8s", "12s", "16s", "24s"]
    w_vals = [4, 8, 12, 16, 24]
    w_med_r = [ws[k]["pearson_r"]["median"] for k in w_keys]
    w_mean_r = [ws[k]["pearson_r"]["mean"] for k in w_keys]
    w_med_rmse = [ws[k]["rmse_mhz"]["median"] for k in w_keys]

    ax_w1 = axes[1, 0]
    ax_w2 = ax_w1.twinx()
    l1 = ax_w1.plot(w_vals, w_med_r, "o-", color="#d81b60", lw=2.0, label="Median Pearson r")
    l2 = ax_w1.plot(w_vals, w_mean_r, "s--", color="#ad1457", lw=1.4, alpha=0.8, label="Mean Pearson r")
    l3 = ax_w2.plot(w_vals, w_med_rmse, "^-", color="#1e88e5", lw=2.0, label="Median RMSE (mHz)")
    ax_w1.axvline(16, color="#2e7d32", ls=":", lw=1.4, label="Frozen Default (16 s)")
    ax_w1.set_xlabel("STFT Window Length (seconds, hop = 1 s)")
    ax_w1.set_ylabel("Pearson Correlation r", color="#d81b60")
    ax_w2.set_ylabel("Median RMSE (mHz)", color="#1e88e5")
    ax_w1.set_xticks(w_vals)
    ax_w1.set_ylim(0.5, 1.02)
    ax_w2.grid(False)
    lines = l1 + l2 + l3
    labels = [l.get_label() for l in lines]
    ax_w1.legend(lines, labels, loc="center right")
    ax_w1.set_title("(c) Effect of STFT Window Length on Dev H1 Accuracy")

    # Panel D: Recording-Level RMSE Histogram (W06 Hybrid vs Single 100 Hz)
    rec_rmses_hyb = [r["rmse_mhz"] for r in results["diagnostics"]["per_recording_dev_h1"]]
    axes[1, 1].hist(rec_rmses_hyb, bins=np.linspace(0, 60, 25), color="#d81b60", alpha=0.75, edgecolor="#222222", label=f"W06 Hybrid (med={np.median(rec_rmses_hyb):.2f} mHz)")
    axes[1, 1].axvline(15.0, color="#2e7d32", ls="--", lw=1.5, label="Pre-Declared Gate (15.0 mHz)")
    axes[1, 1].axvline(float(np.median(rec_rmses_hyb)), color="#111111", ls="-", lw=1.5, label=f"Dev Median ({np.median(rec_rmses_hyb):.2f} mHz)")
    axes[1, 1].set_xlabel("Recording-Level RMSE vs Reference (mHz)")
    axes[1, 1].set_ylabel("Number of Dev H1 Recordings")
    axes[1, 1].set_title("(d) Recording-Level RMSE Distribution Across Dev H1")
    axes[1, 1].legend(loc="upper right")

    fig.tight_layout()
    out_path = PLOTS_DIR / "error_histograms_and_ablations.png"
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def plot_presence_roc_and_robustness(results: Dict[str, Any]) -> Path:
    """Plot 4: ENF-Presence ROC curves, H1 vs H0 histograms, Codec & AWGN robustness."""
    fig, axes = plt.subplots(2, 2, figsize=(12, 8.8))

    # Panel A: ROC Curves on Dev H1 vs Dev H0
    roc_data = results["experiment_3_roc_curves"]
    det_specs = [
        ("w06_composite", "W06 Composite Detector", "#d81b60", "-", 2.2),
        ("multi_harmonic_snr_only", "Multi-Harmonic SNR Only", "#1e88e5", "--", 1.6),
        ("hua2021_tf_variance_only", "Hua et al. (2021) TF Variance Only", "#43a047", "-.", 1.6),
        ("single_100hz_snr_only", "Single 100 Hz SNR Only", "#fb8c00", ":", 1.6),
    ]
    for key, label, col, ls, lw in det_specs:
        d = roc_data[key]
        axes[0, 0].plot(d["fpr"], d["tpr"], color=col, ls=ls, lw=lw, label=f"{label} (AUC={d['auc']:.3f})")
    axes[0, 0].plot([0, 1], [0, 1], color="#9e9e9e", ls="--", lw=1.0)
    axes[0, 0].set_xlim(-0.02, 1.02)
    axes[0, 0].set_ylim(-0.02, 1.02)
    axes[0, 0].set_xlabel("False Positive Rate (FPR on Dev H0)")
    axes[0, 0].set_ylabel("True Positive Rate (TPR on Dev H1)")
    axes[0, 0].set_title(
        f"(a) ENF-Presence Detection ROC (Dev H1 N={results['split_provenance']['n_dev_h1']} vs "
        f"H0 N={results['split_provenance']['n_dev_h0']})"
    )
    axes[0, 0].legend(loc="lower right")

    # Panel B: Presence Score Distribution on Dev H1 vs Dev H0
    h1_scores = [r["presence_score"] for r in results["diagnostics"]["per_recording_dev_h1"]]
    h0_scores = [r["presence_score"] for r in results["diagnostics"]["per_recording_dev_h0"]]
    bins_p = np.linspace(0.0, 1.0, 26)
    axes[0, 1].hist(h0_scores, bins=bins_p, alpha=0.65, color="#546e7a", edgecolor="#222222", label=f"Dev H0 (No ENF, n={len(h0_scores)})")
    axes[0, 1].hist(h1_scores, bins=bins_p, alpha=0.65, color="#d81b60", edgecolor="#222222", label=f"Dev H1 (With ENF, n={len(h1_scores)})")
    axes[0, 1].axvline(0.48, color="#2e7d32", ls="--", lw=1.6, label="Frozen Threshold (0.48)")
    axes[0, 1].set_xlabel("W06 ENF-Presence Score")
    axes[0, 1].set_ylabel("Recording Count")
    axes[0, 1].set_title("(b) ENF-Presence Score Separation on Dev H1 vs. Dev H0")
    axes[0, 1].legend(loc="upper left")

    # Panel C: FFmpeg Lossy Codec Re-Encoding Robustness (MP3 & AAC @ 32/64 kbps)
    codec_res = results["experiment_4a_codec_robustness_dev_subset"]
    c_keys = ["wav_uncompressed", "mp3_64k", "mp3_32k", "aac_64k", "aac_32k"]
    c_labels = ["WAV\n(Orig)", "MP3\n64 kbps", "MP3\n32 kbps", "AAC\n64 kbps", "AAC\n32 kbps"]
    c_med_r = [codec_res[k]["pearson_r"]["median"] for k in c_keys]
    c_p25_r = [codec_res[k]["pearson_r"]["p25"] for k in c_keys]
    c_p75_r = [codec_res[k]["pearson_r"]["p75"] for k in c_keys]
    x_c = np.arange(len(c_keys))
    bars_c = axes[1, 0].bar(
        x_c,
        c_med_r,
        yerr=[np.array(c_med_r) - np.array(c_p25_r), np.array(c_p75_r) - np.array(c_med_r)],
        capsize=4,
        color=["#2e7d32", "#1e88e5", "#64b5f6", "#8e24aa", "#ba68c8"],
        edgecolor="#222222",
    )
    axes[1, 0].set_xticks(x_c)
    axes[1, 0].set_xticklabels(c_labels)
    axes[1, 0].set_ylim(0.0, 1.08)
    axes[1, 0].set_ylabel("Median Pearson r (with IQR)")
    axes[1, 0].set_title("(c) Robustness to FFmpeg MP3/AAC Re-Encoding (Dev Subset)")
    for b, v in zip(bars_c, c_med_r):
        axes[1, 0].text(b.get_x() + b.get_width() / 2.0, v + 0.02, f"{v:.3f}", ha="center", va="bottom", fontsize=8.5, fontweight="bold")

    # Panel D: Synthetic AWGN Broadband Noise Robustness
    awgn_res = results["experiment_4b_synthetic_awgn_robustness_dev_subset"]
    snr_keys = ["awgn_+10dB", "awgn_+0dB", "awgn_-5dB", "awgn_-10dB", "awgn_-15dB"]
    snr_vals = [10, 0, -5, -10, -15]
    hyb_r = [awgn_res[k]["w06_hybrid"]["pearson_r"]["median"] for k in snr_keys]
    base_r = [awgn_res[k]["single_100hz_baseline"]["pearson_r"]["median"] for k in snr_keys]
    axes[1, 1].plot(snr_vals, hyb_r, "o-", color="#d81b60", lw=2.0, label="W06 Weighted Multi-Harmonic")
    axes[1, 1].plot(snr_vals, base_r, "s--", color="#1e88e5", lw=1.6, label="Single 100 Hz Baseline")
    axes[1, 1].invert_xaxis()
    axes[1, 1].set_xlabel("Injected Synthetic AWGN Broadband SNR (dB, lower = noisier)")
    axes[1, 1].set_ylabel("Median Pearson Correlation r")
    axes[1, 1].set_ylim(0.0, 1.05)
    axes[1, 1].set_title("(d) Robustness to Synthetic Additive White Gaussian Noise")
    axes[1, 1].legend(loc="lower left")

    fig.tight_layout()
    out_path = PLOTS_DIR / "presence_roc_and_robustness.png"
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def main() -> None:
    set_plot_style()
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    cfg["decode_via_ffmpeg"] = False

    results_path = WORK_DIR / "RESULTS.json"
    if not results_path.exists():
        raise FileNotFoundError(f"Run evaluate_dev.py first; missing {results_path}")
    with open(results_path, "r", encoding="utf-8") as f:
        results = json.load(f)

    p1 = plot_spectrogram_with_ridge(cfg)
    print(f"Saved Plot 1: {p1}")
    p2 = plot_extracted_vs_reference_overlays(cfg, results)
    print(f"Saved Plot 2: {p2}")
    p3 = plot_error_histograms_and_ablations(cfg, results)
    print(f"Saved Plot 3: {p3}")
    p4 = plot_presence_roc_and_robustness(results)
    print(f"Saved Plot 4: {p4}")


if __name__ == "__main__":
    main()
