"""Figures for C3 (all clip manipulations are SYNTHETIC, made from real ENF-WHU audio).

  plots/spectrum_orig_vs_1.75x_8s.png   original vs ffmpeg-asetrate 1.75x, 8 s, comb overlaid
  plots/heatmap_tpr_rate_holdout.png    holdout detection rate, k x length (+ atempo panel)
  plots/splice_phase_jump_example.png   ENF phase track and jump statistic around a 5 s deletion

Usage: python make_plots.py [--rec 090]
"""
import argparse
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import speed_check as sc  # noqa: E402
import splice_check as sp  # noqa: E402

PLOTS = os.path.join(HERE, "plots")
ROOT = r"<WORKSPACE>\datasets\raw\enf-whu\repo\ENF-WHU-Dataset"
INK, MUTED, BLUE, ORANGE, RED = "#1f2328", "#6e7781", "#2f6fb0", "#d0782a", "#c0392b"


def spectrum_figure(rec):
    fo = os.path.join(HERE, "demo", f"{rec}_orig_8s.wav")
    fs_ = os.path.join(HERE, "demo", f"{rec}_rate1.75_8s.wav")
    fig, axes = plt.subplots(2, 1, figsize=(11, 6.4), sharex=True)
    for ax, path, title in [(axes[0], fo, "Original 8 s clip (real ENF-WHU recording %s)" % rec),
                            (axes[1], fs_, "Same clip sped up 1.75x (SYNTHETIC: ffmpeg asetrate=8000*1.75,aresample=8000)")]:
        x, sr = sf.read(path)
        r = sc.analyse(x, sr, return_debug=True)
        f, snr = r["_debug"]["f"], r["_debug"]["snr"]
        m = (f >= 20) & (f <= 1000)
        ax.plot(f[m], snr[m], color=INK, lw=0.6)
        for n in range(1, 21):
            if n * 50 <= 1000:
                ax.axvline(n * 50, color=MUTED, ls=":", lw=0.8)
        if r.get("base_hz"):
            col = BLUE if r["decision"].startswith("CONSISTENT") else RED
            for n in range(1, 21):
                if n * r["base_hz"] <= 1000:
                    ax.axvline(n * r["base_hz"], color=col, ls="--", lw=1.0, alpha=0.8)
            for l in r["lines"]:
                ax.plot(l["f_hz"], l["snr_db"], "o", color=col, ms=5)
        ci = r.get("k_ci95")
        txt = f"{r['decision']}\nk = {r.get('k')}" + (f"  (95% CI {ci[0]:.4f}-{ci[1]:.4f})" if ci else "")
        ax.text(0.99, 0.95, txt, transform=ax.transAxes, ha="right", va="top", fontsize=9.5,
                bbox=dict(fc="white", ec=MUTED, lw=0.6))
        ax.set_title(title, fontsize=10.5, loc="left", color=INK)
        ax.set_ylabel("dB above local median")
        ax.set_ylim(-15, max(45, np.nanmax(snr[m]) + 3))
        ax.spines[["top", "right"]].set_visible(False)
    axes[1].set_xlabel("Frequency (Hz)    dotted grey: n x 50 Hz (real-time mains comb);  dashed: detected comb n x base")
    fig.tight_layout()
    out = os.path.join(PLOTS, "spectrum_orig_vs_1.75x_8s.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def heatmap_figure():
    res = json.load(open(os.path.join(HERE, "RESULTS.json")))["holdout"]
    ks = [0.8, 0.9, 0.95, 0.98, 1.02, 1.05, 1.1, 1.25, 1.5, 1.75, 2.0]
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8), gridspec_kw=dict(width_ratios=[5, 3.2]))
    for ax, method, Ls in [(axes[0], "rate", [5, 8, 15, 30, 60]), (axes[1], "tempo", [8, 30])]:
        M = np.full((len(Ls), len(ks)), np.nan)
        N = np.zeros_like(M, dtype=int)
        for i, L in enumerate(Ls):
            for j, k in enumerate(ks):
                c = res[f"speed_{method}"].get(f"k{k}_L{L}")
                if c and c["tpr"]["n"]:
                    M[i, j] = c["tpr"]["rate"]; N[i, j] = c["tpr"]["n"]
        im = ax.imshow(M, vmin=0, vmax=1, cmap="Blues", aspect="auto")
        for i in range(len(Ls)):
            for j in range(len(ks)):
                if not np.isnan(M[i, j]):
                    ax.text(j, i, f"{M[i, j]:.2f}", ha="center", va="center", fontsize=7.5 if method == "rate" else 6.2,
                            color="white" if M[i, j] > 0.55 else INK)
        ax.set_xticks(range(len(ks)), [str(k) for k in ks], fontsize=8)
        ax.set_yticks(range(len(Ls)), [f"{L} s" for L in Ls])
        ax.set_xlabel("speed factor k")
        nn = int(np.nanmax(N)) if N.size else 0
        ttl = ("asetrate (pitch+tempo, like sped-up CCTV)" if method == "rate" else
               "atempo (tempo only, pitch preserved)")
        ax.set_title(f"Holdout SPEED_ALTERED_REVIEW rate - {ttl}\n(n = {nn} clips per cell, one per holdout H1 recording)",
                     fontsize=9.5, loc="left")
    fig.colorbar(im, ax=axes, fraction=0.025, pad=0.02, label="detection rate")
    out = os.path.join(PLOTS, "heatmap_tpr_rate_holdout.png")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


def splice_figure(rec, start=40.0, L=30, cut_at=14.0, d=5):
    x, sr = sf.read(os.path.join(ROOT, "H1", rec + ".wav"))
    a = int(start * sr)
    clean = x[a: a + L * sr]
    ci = int(cut_at * sr)
    spliced = np.concatenate([x[a: a + ci], x[a + ci + d * sr: a + L * sr + d * sr]])
    fig, axes = plt.subplots(2, 2, figsize=(12, 5.6), sharex=True)
    for col, (y, title) in enumerate([(clean, f"Unmodified 30 s clip (real, rec {rec})"),
                                      (spliced, f"SYNTHETIC: {d} s deleted at t = {cut_at} s")]):
        r = sp.analyse(y, sr)
        tf, J, ph = r["_trace"]
        # detrend phase by the median slope to show the jump
        slope = np.median(np.diff(ph))
        axes[0, col].plot(tf, ph - slope * np.arange(len(ph)), color=INK, lw=1)
        axes[0, col].set_title(title + f"\n{r['decision']}  max jump {r['max_jump_rad']} rad", fontsize=9.5, loc="left")
        axes[0, col].set_ylabel("ENF phase, detrended (rad)")
        axes[1, col].plot(tf, J, color=BLUE, lw=1)
        axes[1, col].axhline(r["theta_rad"], color=RED, ls="--", lw=1, label=f"theta = {r['theta_rad']} rad (dev-tuned)")
        axes[1, col].set_ylabel("jump statistic J (rad)")
        axes[1, col].set_xlabel(f"time (s)   tracked line {r.get('f_track_hz')} Hz")
        axes[1, col].legend(fontsize=8, loc="upper left")
        if col == 1:
            for ax in axes[:, col]:
                ax.axvline(cut_at, color=ORANGE, lw=1.2, alpha=0.7)
        for ax in axes[:, col]:
            ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    out = os.path.join(PLOTS, "splice_phase_jump_example.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rec", default="090")
    ap.add_argument("--splice-rec", default="090")
    ap.add_argument("--only", default="spectrum,heatmap,splice")
    a = ap.parse_args()
    os.makedirs(PLOTS, exist_ok=True)
    if "spectrum" in a.only:
        print(spectrum_figure(a.rec))
    if "heatmap" in a.only:
        print(heatmap_figure())
    if "splice" in a.only:
        print(splice_figure(a.splice_rec))
