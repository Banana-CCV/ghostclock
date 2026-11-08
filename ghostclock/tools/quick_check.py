"""GhostClock quick check for a team recording (director tool).

usage: python -m ghostclock.tools.quick_check <video_or_audio> [--no-video] [--max-seconds N]
Writes $GHOSTCLOCK_OUT/quick/<stem>/report.json (default out/quick/<stem>) + PNGs. Uses C1's audio extractor and C4's
rolling-shutter extractor (both independently verified). Prints a plain-language verdict.
"""
import argparse, json, os, subprocess, sys, glob, shutil
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from ghostclock import audio_enf as c1   # noqa: E402  (audio, C1 extractor)
from ghostclock import rs_enf as c4      # noqa: E402  (video, C4 rolling-shutter extractor)
from ghostclock._paths import OUT_DIR, find_tool  # noqa: E402


def tool(name):
    p = find_tool(name)
    if not p:
        raise FileNotFoundError(f"{name} not found: put it on PATH or set GHOSTCLOCK_FFMPEG_DIR")
    return p


def probe(path):
    out = subprocess.run([tool("ffprobe"), "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
                         capture_output=True, text=True).stdout
    j = json.loads(out)
    v = next((s for s in j["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in j["streams"] if s["codec_type"] == "audio"), None)
    info = {"duration_s": float(j["format"].get("duration", 0)), "has_audio": a is not None, "has_video": v is not None}
    if v:
        fr = lambda s: (lambda n, d: float(n) / float(d) if float(d) else 0.0)(*s.split("/"))
        info.update(codec=v.get("codec_name"), width=v.get("width"), height=v.get("height"),
                    r_frame_rate=fr(v.get("r_frame_rate", "0/1")), avg_frame_rate=fr(v.get("avg_frame_rate", "0/1")),
                    nb_frames=v.get("nb_frames"),
                    rotation=next((sd.get("rotation") for sd in v.get("side_data_list", []) if "rotation" in sd), v.get("tags", {}).get("rotate")))
        info["vfr_suspect"] = abs(info["r_frame_rate"] - info["avg_frame_rate"]) > 0.05 * max(info["avg_frame_rate"], 1)
    if a:
        info.update(audio_codec=a.get("codec_name"), audio_rate=int(a.get("sample_rate", 0)))
    return info


def grid_likeness(f, q, q_min):
    m = np.isfinite(f) & (q >= q_min)
    if m.sum() < 10:
        return {"valid_windows": int(m.sum())}
    ff = f[m]
    return {"valid_windows": int(m.sum()), "median_hz": float(np.median(ff)),
            "std_mhz": float(np.std(ff) * 1e3),
            "range_mhz": float((np.percentile(ff, 95) - np.percentile(ff, 5)) * 1e3),
            "within_49p8_50p2": float(np.mean((ff > 49.8) & (ff < 50.2)))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("media")
    ap.add_argument("--no-video", action="store_true")
    ap.add_argument("--max-seconds", type=float, default=None)
    a = ap.parse_args()
    stem = Path(a.media).stem
    out = OUT_DIR / "quick" / stem
    out.mkdir(parents=True, exist_ok=True)
    rep = {"media": a.media, "probe": probe(a.media)}
    print(json.dumps(rep["probe"], indent=1))

    # ---- audio
    if rep["probe"]["has_audio"]:
        x, fs = c1.load_audio(a.media)
        if a.max_seconds:
            x = x[: int(a.max_seconds * fs)]
        win = 16.0 if len(x) / fs >= 40 else 8.0
        r = c1.extract_enf(x, fs, win_s=win)
        snr_db = 10 * np.log10(np.median(r["snrk"], axis=0) + 1e-12)
        rep["audio"] = {"window_s": win, "median_q_db": float(np.median(r["q"])),
                        "harmonic_median_snr_db": {f"{int(k*50)}Hz": round(float(s), 1) for k, s in zip(r["harmonics"], snr_db)},
                        "grid": grid_likeness(r["f"], r["q"], q_min=8.0)}
        np.savetxt(out / "audio_trace.csv", np.c_[r["t"], r["f"], r["q"]], delimiter=",", header="t_s,enf_hz,q_db", comments="")
        # spectrum plot
        xs, fss = c1.to_rate(x, fs, 1000) if fs > 1000 else (x, fs)
        n = min(len(xs), int(fss * 60))
        F = np.fft.rfftfreq(n * 8, 1 / fss); P = np.abs(np.fft.rfft(xs[:n] * np.hanning(n), n * 8)) ** 2
        sel = (F > 30) & (F < 360)
        fig, ax = plt.subplots(figsize=(11, 3.4))
        ax.semilogy(F[sel], P[sel], lw=0.6, color="#333")
        for k in range(1, 8):
            ax.axvline(50 * k, color="#d62728", alpha=0.25, lw=1)
        ax.set_xlabel("Hz"); ax.set_title(f"{stem}: audio spectrum, first {n/fss:.0f} s (red = mains harmonics)")
        fig.tight_layout(); fig.savefig(out / "audio_spectrum.png", dpi=130); plt.close(fig)
        fig, ax = plt.subplots(figsize=(11, 3))
        ax.plot(r["t"], r["f"], lw=1); ax.set_ylabel("Hz"); ax.set_xlabel("s"); ax.set_title(f"{stem}: audio ENF trace")
        fig.tight_layout(); fig.savefig(out / "audio_trace.png", dpi=130); plt.close(fig)

    # ---- video
    if rep["probe"]["has_video"] and not a.no_video:
        fps = rep["probe"]["avg_frame_rate"] or 30
        mf = int(a.max_seconds * fps) if a.max_seconds else None
        dur = rep["probe"]["duration_s"] if not a.max_seconds else min(a.max_seconds, rep["probe"]["duration_s"])
        win = 16.0 if dur >= 40 else 8.0
        v = c4.run_video(a.media, max_frames=mf, win_s=win, cache=str(out / "cells.npz"))
        tc, fe, q = v["rs"]
        ts, fs_, qs = v["strip"][:3] if isinstance(v["strip"], (tuple, list)) else (None, None, None)
        rep["video"] = {"fps_measured": v["fps"], "Tro_ms": v["Tro"] * 1e3, "alias_hz": v["alias"],
                        "degenerate_fps": v["degenerate"], "static_cells": int(v["mask"].sum()),
                        "rows_used": int(v["rows"].sum()), "median_q_rs_db": float(np.median(q)),
                        "grid": grid_likeness(np.asarray(fe), np.asarray(q), q_min=20.0)}
        np.savetxt(out / "video_rs_trace.csv", np.c_[tc, fe, q], delimiter=",", header="t_s,enf_hz,q_db", comments="")
        fig, ax = plt.subplots(figsize=(11, 3))
        ax.plot(tc, fe, lw=1, label="video (rolling shutter)")
        if "audio_trace.csv" in os.listdir(out):
            at = np.loadtxt(out / "audio_trace.csv", delimiter=",", skiprows=1)
            ax.plot(at[:, 0], at[:, 1], lw=1, alpha=0.7, label="audio hum")
            # audio-video agreement
            fi = np.interp(np.asarray(tc), at[:, 0], at[:, 1], left=np.nan, right=np.nan)
            m = np.isfinite(fi) & np.isfinite(fe)
            if m.sum() > 10:
                rep["audio_video_corr"] = float(np.corrcoef(np.asarray(fe)[m], fi[m])[0, 1])
        ax.legend(); ax.set_ylabel("Hz"); ax.set_xlabel("s"); ax.set_title(f"{stem}: ENF traces")
        fig.tight_layout(); fig.savefig(out / "traces.png", dpi=130); plt.close(fig)

    # ---- verdict (plain language, conservative)
    lines = []
    for mod in ("audio", "video"):
        g = rep.get(mod, {}).get("grid", {})
        if not g:
            continue
        ok = g.get("valid_windows", 0) >= 10 and g.get("within_49p8_50p2", 0) > 0.9 and g.get("range_mhz", 0) > 3
        steady = g.get("valid_windows", 0) >= 10 and g.get("range_mhz", 99) < 1.0
        lines.append(f"{mod.upper()}: " + ("grid-like ENF present (median %.3f Hz, wander %.1f mHz)" % (g["median_hz"], g["range_mhz"]) if ok
                     else "periodic but suspiciously steady (crystal/driver, not grid?)" if steady
                     else "no usable grid signal"))
    if "audio_video_corr" in rep:
        lines.append(f"audio vs video ENF correlation: {rep['audio_video_corr']:.3f}")
    rep["verdict"] = lines
    (out / "report.json").write_text(json.dumps(rep, indent=1, default=float), encoding="utf-8")
    print("\n".join(["VERDICT:"] + lines + [f"outputs: {out}"]))


if __name__ == "__main__":
    main()
