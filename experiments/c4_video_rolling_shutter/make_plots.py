"""make_plots.py -- C4 demo figures (REAL MOV2 + SYNTHETIC cases).
Run after run_real.py and synth_eval.py.  Figures -> plots/.
"""
import glob
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(HERE, "plots")
os.makedirs(P, exist_ok=True)
plt.rcParams.update({"figure.dpi": 110, "font.size": 9, "axes.spines.top": False,
                     "axes.spines.right": False})
C_RS, C_NV, C_ST, C_REF = "#1f6fb4", "#d9822b", "#8a8a8a", "#222222"


def banding_figure(frames, title, out, f_light=100.0, Tro=None):
    """frames: (N, H, W) uint8 luminance (consecutive). Residual = frame - temporal mean."""
    fr = frames.astype(np.float32)
    mu = fr.mean(axis=0)
    res = fr[len(fr) // 2] - mu
    lo, hi = np.percentile(res, [1, 99])
    stretched = np.clip((res - lo) / (hi - lo + 1e-9), 0, 1)
    prof = np.median(res, axis=1)   # robust row profile (median across columns)
    fig, ax = plt.subplots(1, 3, figsize=(12, 3.6), gridspec_kw=dict(width_ratios=[4, 4, 1.3]))
    ax[0].imshow(fr[len(fr) // 2], cmap="gray", vmin=0, vmax=255, aspect="auto")
    ax[0].set_title("decoded frame (luma)")
    ax[1].imshow(stretched, cmap="gray", aspect="auto")
    ax[1].set_title(f"residual = frame - mean of {len(fr)} frames, contrast-stretched\n"
                    f"(1st-99th pct = [{lo:.2f}, {hi:.2f}] grey levels)")
    ax[2].plot(prof, np.arange(len(prof)), color=C_RS, lw=0.8)
    ax[2].invert_yaxis(); ax[2].set_title("row mean of\nresidual"); ax[2].set_xlabel("grey levels")
    for a in ax[:2]:
        a.set_xticks([]); a.set_yticks([])
    if Tro is not None:
        ax[2].text(0.02, 0.01, f"T_ro~{Tro*1e3:.1f} ms\n-> {f_light*Tro:.2f} bands/frame",
                   transform=ax[2].transAxes, fontsize=7)
    fig.suptitle(title, fontsize=10)
    fig.tight_layout(); fig.savefig(out); plt.close(fig)


def spectrogram_figure(z, fps, title, out, f0=100.0, win_s=32.0, ref=None, lag=0.0):
    n = int(win_s * fps); hop = int(fps)
    nfft = 1 << int(np.ceil(np.log2(n * 8)))
    f = np.fft.fftshift(np.fft.fftfreq(nfft, 1 / fps))
    sel = np.abs(f) <= 0.3
    win = np.hanning(n)
    S, tc = [], []
    for i in range(0, len(z) - n + 1, hop):
        Pw = np.abs(np.fft.fftshift(np.fft.fft(z[i:i + n] * win, nfft))) ** 2
        S.append(10 * np.log10(Pw[sel] / np.median(Pw) + 1e-12)); tc.append((i + n / 2) / fps)
    S = np.array(S).T
    fig, ax = plt.subplots(figsize=(9, 3.6))
    im = ax.imshow(S, aspect="auto", origin="lower", cmap="magma",
                   extent=[tc[0], tc[-1], f0 + f[sel][0], f0 + f[sel][-1]],
                   vmin=np.percentile(S, 75), vmax=np.percentile(S, 99.9))
    if ref is not None:
        ax.plot(ref[0] - lag, 2 * ref[1], color="cyan", lw=0.7, alpha=0.8,
                label="2 x reference ENF (mains WAV)")
        ax.set_xlim(tc[0], tc[-1])
        ax.legend(loc="upper right", fontsize=7)
    ax.set_xlabel("video time (s)"); ax.set_ylabel("light frequency (Hz)")
    ax.set_title(title, fontsize=10)
    fig.colorbar(im, ax=ax, label="dB over median")
    fig.tight_layout(); fig.savefig(out); plt.close(fig)


def overlay_figure(t_rs, f_rs, t_nv, f_nv, t_ref, f_ref, title, out, ref_label, m_rs, m_nv,
                   strip=None, m_st=None):
    fig, ax = plt.subplots(2, 1, figsize=(9, 5.2), sharex=True,
                           gridspec_kw=dict(height_ratios=[3, 1.2]))
    ax[0].plot(t_ref, f_ref, color=C_REF, lw=1.8, label=ref_label)
    ax[0].plot(t_nv, f_nv, color=C_NV, lw=0.7, alpha=0.8,
               label=f"naive whole-frame mean (r={m_nv.get('corr', np.nan):.3f}, "
                     f"RMSE={m_nv.get('rmse_mHz', np.nan):.1f} mHz)")
    if strip is not None:
        ax[0].plot(strip[0], strip[1], color=C_ST, lw=0.8, ls="--",
                   label=f"strip-wise alias baseline (r={m_st.get('corr', np.nan):.3f}, "
                         f"RMSE={m_st.get('rmse_mHz', np.nan):.1f} mHz)")
    ax[0].plot(t_rs, f_rs, color=C_RS, lw=1.1,
               label=f"rolling-shutter extractor (r={m_rs.get('corr', np.nan):.3f}, "
                     f"RMSE={m_rs.get('rmse_mHz', np.nan):.1f} mHz)")
    lo = min(np.percentile(f_ref, 0.5), np.percentile(f_rs, 2)) - 0.015
    hi = max(np.percentile(f_ref, 99.5), np.percentile(f_rs, 98)) + 0.015
    ax[0].set_ylim(lo, hi)
    ax[0].set_ylabel("ENF (Hz)"); ax[0].legend(fontsize=7, loc="best", frameon=False)
    ax[0].set_title(title, fontsize=10)
    ax[1].plot(t_rs, (f_rs - np.interp(t_rs, t_ref, f_ref)) * 1e3, color=C_RS, lw=0.8)
    ax[1].axhline(0, color="#999", lw=0.5)
    ax[1].set_ylabel("RS - ref (mHz)"); ax[1].set_xlabel("video time (s)")
    fig.tight_layout(); fig.savefig(out); plt.close(fig)


def tro_figure(curves, out):
    fig, ax = plt.subplots(figsize=(7, 3.2))
    for lab, g, sc, true in curves:
        ln, = ax.plot(g * 1e3, sc / np.max(sc), lw=1, label=lab)
        if true is not None:
            ax.axvline(true * 1e3, ls=":", lw=0.8, color=ln.get_color())
    ax.set_xlabel("candidate T_ro (ms)  (negative = bottom-up read-out)")
    ax.set_ylabel("peak sharpness (normalised)")
    ax.set_title("T_ro search: spectral peak sharpness near f0 (dotted = true value, SYNTHETIC only)",
                 fontsize=9)
    ax.legend(fontsize=6, frameon=False)
    fig.tight_layout(); fig.savefig(out); plt.close(fig)


def synth_summary_figure(out):
    rows = []
    for f in sorted(glob.glob(os.path.join(HERE, "synth", "SYNTH_*_eval.json"))):
        e = json.load(open(f))
        rows.append((e["case"], e["rolling_shutter"]["rmse_mHz"], e["naive_frame_mean"]["rmse_mHz"],
                     e["rolling_shutter"]["corr"], e["naive_frame_mean"]["corr"],
                     e["strip_alias_baseline"]["rmse_mHz"], e["strip_alias_baseline"]["corr"]))
    if not rows:
        return
    fig, ax = plt.subplots(1, 2, figsize=(11, 3.8))
    y = np.arange(len(rows))
    ax[0].barh(y - 0.27, [r[1] for r in rows], 0.27, color=C_RS, label="rolling shutter")
    ax[0].barh(y, [r[5] for r in rows], 0.27, color=C_ST, label="strip-wise alias")
    ax[0].barh(y + 0.27, [r[2] for r in rows], 0.27, color=C_NV, label="naive frame mean")
    ax[0].set_xscale("log"); ax[0].set_xlabel("RMSE vs truth (mHz, log)")
    ax[0].set_yticks(y); ax[0].set_yticklabels([r[0] for r in rows], fontsize=7)
    ax[0].invert_yaxis(); ax[0].legend(fontsize=7, frameon=False)
    ax[1].barh(y - 0.27, [r[3] for r in rows], 0.27, color=C_RS)
    ax[1].barh(y, [r[6] for r in rows], 0.27, color=C_ST)
    ax[1].barh(y + 0.27, [r[4] for r in rows], 0.27, color=C_NV)
    ax[1].set_xlim(-1, 1); ax[1].axvline(0, color="#999", lw=0.5)
    ax[1].set_xlabel("Pearson r vs truth"); ax[1].set_yticks([]); ax[1].invert_yaxis()
    fig.suptitle("SYNTHETIC rolling-shutter benchmark (240 s each, H.264) - NOT real data",
                 fontsize=10)
    fig.tight_layout(); fig.savefig(out); plt.close(fig)


if __name__ == "__main__":
    # ---------- real
    rp = os.path.join(HERE, "real_MOV2_results.npz")
    d = None
    if os.path.exists(rp):
        d = np.load(rp, allow_pickle=True)
        info = json.load(open(os.path.join(HERE, "real_MOV2_results.json")))
        # quietest 2 s of the clip (lowest per-frame motion score) for the banding demo
        from scipy.ndimage import uniform_filter1d
        import av
        k0 = int(np.argmin(uniform_filter1d(d["motion"], 60))) - 30
        c = av.open(os.path.join(HERE, "..", "..", info["video"])); st = c.streams.video[0]
        t0 = k0 / float(d["fps"]) - 1.0
        c.seek(int(max(t0, 0) / st.time_base), stream=st)
        frames = []
        for x in c.decode(st):
            if x.time >= k0 / float(d["fps"]) - 1e-3:
                frames.append(x.to_ndarray(format="gray"))
            if len(frames) >= 60:
                break
        c.close()
        banding_figure(np.stack(frames), f"REAL: Zenodo MOV2_20190508_200450A, quietest 2 s "
                       f"(t={k0/float(d['fps']):.1f}-{(k0+60)/float(d['fps']):.1f} s)",
                       os.path.join(P, "real_MOV2_banding_residual.png"), Tro=info["Tro_ms"] / 1e3)
        lag = info["rolling_shutter"]["best_lag_s"]
        spectrogram_figure(d["z"], float(d["fps"]),
                           f"REAL MOV2: rolling-shutter baseband spectrogram (T_ro={info['Tro_ms']:.2f} ms)",
                           os.path.join(P, "real_MOV2_row_spectrogram.png"),
                           ref=(d["tr"], d["fr"]), lag=lag)
        overlay_figure(d["tc"], d["fe"], d["tn"], d["fn"], d["tr"] - lag, d["fr"],
                       f"REAL MOV2 vs mains reference (lag {lag:.1f} s from corr. search; "
                       f"filename lag {info['nominal_lag_s']} s)",
                       os.path.join(P, "real_MOV2_overlay.png"), "reference ENF (mains WAV)",
                       info["rolling_shutter"]["at_best_lag"],
                       info["naive_frame_mean"]["at_best_lag"],
                       strip=(d["ts"], d["fs_strip"]),
                       m_st=info["strip_alias_baseline"]["at_best_lag"])
        lc = info["rolling_shutter_full_lag_curve"]
        fig, ax = plt.subplots(figsize=(7, 3))
        ax.plot(lc["lags"], lc["corr"], color=C_RS, lw=1)
        ax.axvline(info["nominal_lag_s"], color="#999", ls=":", lw=1,
                   label=f"filename-implied lag ({info['nominal_lag_s']} s)")
        ax.axvline(lag, color=C_RS, ls="--", lw=0.8, label=f"best lag {lag:.1f} s")
        ax.set_xlabel("lag = reference time - video time (s)"); ax.set_ylabel("Pearson r")
        ax.set_title("REAL MOV2: rolling-shutter ENF vs reference, correlation over all lags",
                     fontsize=9)
        ax.legend(fontsize=7, frameon=False)
        fig.tight_layout(); fig.savefig(os.path.join(P, "real_MOV2_lag_search.png")); plt.close(fig)
    # ---------- synthetic
    curves = []
    for f in sorted(glob.glob(os.path.join(HERE, "synth", "SYNTH_*_eval.json"))):
        e = json.load(open(f)); case = e["case"]
        base = f.replace("_eval.json", "")
        rs = np.loadtxt(base + "_rolling_shutter_trace.csv", delimiter=",", skiprows=1)
        nv = np.loadtxt(base + "_naive_frame_mean_trace.csv", delimiter=",", skiprows=1)
        stp = np.loadtxt(base + "_strip_alias_baseline_trace.csv", delimiter=",", skiprows=1)
        overlay_figure(rs[:, 0], rs[:, 1], nv[:, 0], nv[:, 1], rs[:, 0], rs[:, 3],
                       f"SYNTHETIC {case}",
                       os.path.join(P, f"SYNTH_{case.replace('+', '_')}_overlay.png"),
                       "SYNTHETIC truth (window-averaged)", e["rolling_shutter"],
                       e["naive_frame_mean"], strip=(stp[:, 0], stp[:, 1]),
                       m_st=e["strip_alias_baseline"])
        dg = np.load(base + "_diag.npz")
        if "+" not in case:
            curves.append((f"SYNTH {case}", dg["Tro_grid"], dg["Tro_score"], e["Tro_true_ms"] / 1e3))
        if case == "fps30_tro25":
            spectrogram_figure(dg["z"], float(dg["fps"]), f"SYNTHETIC {case}: baseband spectrogram",
                               os.path.join(P, f"SYNTH_{case}_row_spectrogram.png"))
            import av
            c = av.open(base + ".mp4"); fr = []
            for i, x in enumerate(c.decode(video=0)):
                if i >= 600:
                    fr.append(x.to_ndarray(format="gray"))
                if i >= 659:
                    break
            c.close()
            banding_figure(np.stack(fr), f"SYNTHETIC {case} (frames 600-659)",
                           os.path.join(P, f"SYNTH_{case}_banding_residual.png"), Tro=0.025)
    if d is not None:
        curves.append(("REAL MOV2 (both directions)", d["gb"], d["sb"], None))
    tro_figure(curves, os.path.join(P, "Tro_search.png"))
    synth_summary_figure(os.path.join(P, "SYNTH_summary.png"))
    print("plots written to", P)
