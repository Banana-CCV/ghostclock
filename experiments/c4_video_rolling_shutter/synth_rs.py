r"""synth_rs.py -- SYNTHETIC rolling-shutter flicker video generator (clearly synthetic).

Renders a static textured scene lit by a mains lamp whose light output follows a known
ENF trace, through a rolling-shutter + exposure model, then encodes H.264 with ffmpeg.

Light:   L(t) = 1 + m1 cos(phi(t)) + m2 cos(2 phi(t)),  phi(t) = 2 pi \int 2 f_enf(s) ds
Row r of frame k starts exposing at t_kr = k/fps + r*T_ro/H and integrates for T_exp:
         harmonic h gets gain sinc(h*2f*T_exp) and is sampled at the exposure centre.
Extras:  moving dark object (motion), slow auto-exposure gain drift, Gaussian noise,
         8-bit quantisation, clipped "window" patch, H.264 (libx264, CRF) encode.

The ground-truth ENF trace is written next to the video as *_truth.csv (t_s, enf_hz).
ALL OUTPUTS OF THIS SCRIPT ARE SYNTHETIC.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess

import numpy as np
from scipy.ndimage import gaussian_filter

FFMPEG = (glob.glob(os.path.expandvars(
    r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*\*\bin\ffmpeg.exe")) or ["ffmpeg"])[0]


def enf_random_walk(dur_s, seed, f_grid=50.0, sigma_mhz_per_min=15.0, tau_s=600.0):
    """1 s ENF trace: Ornstein-Uhlenbeck around f_grid; ~sigma mHz change per minute."""
    rng = np.random.default_rng(seed)
    n = int(dur_s) + 2
    step = sigma_mhz_per_min / np.sqrt(60.0) * 1e-3  # per-second increment std
    x = np.zeros(n)
    x[0] = rng.normal(0, 0.02)
    for i in range(1, n):
        x[i] = x[i - 1] * (1 - 1 / tau_s) + rng.normal(0, step)
    # add a little fast (few-second) wander
    x += gaussian_filter(rng.normal(0, 2e-3, n), 3)
    return np.arange(n, dtype=float), f_grid + x


def render(out_mp4, fps=30.0, dur_s=240.0, T_ro=0.025, T_exp=0.002, W=640, H=360, m1=0.05,
           m2=0.01, noise=1.5, crf=20, seed=1, f_grid=50.0, enf=None, motion=True,
           ae_drift=0.02, base=150.0):
    rng = np.random.default_rng(seed)
    if enf is None:
        t_enf, f_enf = enf_random_walk(dur_s, seed, f_grid)
    else:
        t_enf, f_enf = enf
    # light phase on a 2 kHz grid
    fs_ph = 2000.0
    tg = np.arange(0, dur_s + 1.0, 1 / fs_ph)
    fl = 2 * np.interp(tg, t_enf, f_enf)
    phi = 2 * np.pi * np.cumsum(fl) / fs_ph + rng.uniform(0, 2 * np.pi)
    f_light = 2 * f_grid
    g1 = np.sinc(f_light * T_exp)          # np.sinc(x) = sin(pi x)/(pi x)
    g2 = np.sinc(2 * f_light * T_exp)
    # scene reflectance: multi-scale texture + edges + clipped window + dark corner
    S = (0.6 + 0.25 * gaussian_filter(rng.normal(size=(H, W)), 12) / 0.03
         + 0.10 * gaussian_filter(rng.normal(size=(H, W)), 2) / 0.12)
    S = np.clip(S, 0.15, 1.3)
    S[40:120, 420:560] = 2.5                       # bright window -> clips at 255
    S[H - 70:, W - 120:] = 0.08                    # dark corner
    for x0 in range(60, W, 140):                   # vertical edges (picture frames)
        S[:, x0:x0 + 3] *= 0.5
    S = S.astype(np.float32)
    rows = np.arange(H)
    n_frames = int(dur_s * fps)
    cmd = [FFMPEG, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "gray",
           "-s", f"{W}x{H}", "-r", f"{fps}", "-i", "-", "-c:v", "libx264", "-preset", "veryfast",
           "-crf", str(crf), "-pix_fmt", "yuv420p", out_mp4]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    # noise bank (speed): 64 independent Gaussian frames, drawn at random per output frame
    bank = noise * rng.standard_normal((64, H, W), dtype=np.float32)
    out8 = np.empty((H, W), np.uint8)
    for k in range(n_frames):
        t_rows = k / fps + rows * T_ro / H + T_exp / 2
        ph = np.interp(t_rows, tg, phi)
        L = 1 + m1 * g1 * np.cos(ph) + m2 * g2 * np.cos(2 * ph)
        gain = base * (1 + ae_drift * np.sin(2 * np.pi * k / fps / 47.0))
        img = S * (gain * L)[:, None].astype(np.float32)
        if motion:  # a person-sized dark object walking back and forth in the lower-left
            xc = int((W * 0.45) * (0.5 + 0.5 * np.sin(2 * np.pi * k / fps / 20.0)))
            img[H // 2:H - 20, xc:xc + 70] *= 0.35
        img += bank[rng.integers(64)]
        img += 0.5
        np.clip(img, 0, 255, out=img)
        out8[:] = img
        p.stdin.write(out8.tobytes())
    p.stdin.close(); p.wait()
    truth = out_mp4.replace(".mp4", "_truth.csv")
    np.savetxt(truth, np.c_[t_enf, f_enf], delimiter=",", header="t_s,enf_hz_SYNTHETIC_TRUTH",
               comments="")
    params = dict(SYNTHETIC=True, fps=fps, dur_s=dur_s, T_ro_ms=T_ro * 1e3, T_exp_ms=T_exp * 1e3,
                  W=W, H=H, m1=m1, m2=m2, noise=noise, crf=crf, seed=seed, motion=motion,
                  ae_drift=ae_drift, exposure_gain_100Hz=float(g1),
                  frame_mean_gain_100Hz=float(np.sinc(f_light * T_ro)))
    json.dump(params, open(out_mp4.replace(".mp4", "_params.json"), "w"), indent=1)
    return truth, params


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--fps", type=float, default=30)
    ap.add_argument("--dur", type=float, default=240)
    ap.add_argument("--tro-ms", type=float, default=25)
    ap.add_argument("--texp-ms", type=float, default=2)
    ap.add_argument("--m1", type=float, default=0.05)
    ap.add_argument("--noise", type=float, default=1.5)
    ap.add_argument("--crf", type=int, default=20)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    print(render(a.out, a.fps, a.dur, a.tro_ms / 1e3, a.texp_ms / 1e3, m1=a.m1, noise=a.noise,
                 crf=a.crf, seed=a.seed))
