"""GhostClock C3 -- ENF phase-discontinuity splice check (Rodriguez, Apolinario &
Biscainho 2010 style: track the phase of the narrow-band ENF component and flag
abrupt phase jumps that natural, slowly varying mains frequency cannot produce).

Pipeline
  1. resample to 2 kHz; pick the strongest hum line near n*50 (or n*60) Hz,
     n*f <= 950 Hz, from a long-window spectrum (or use --fh);
  2. zero-phase band-pass (Butterworth, +/- (bw0 + bw1*n) Hz) around that line;
  3. analytic signal, demodulated by the measured line frequency -> phase phi(t)
     sampled in 0.1 s frames (complex mean per frame);
  4. jump statistic J(t) = | wrap( phi(t+w) - phi(t-w) - slope_local * 2w ) |,
     w = 1.0 s, slope_local = median frame-to-frame phase increment over +/-ctx s
     (excluding the centre), i.e. the phase change across t that is NOT explained
     by the local (natural) frequency;
  5. flag SPLICE_SUSPECTED if max J > theta (radians; fixed on dev only), with
     candidate times = local maxima of J above theta.

A flag is a reason for human review, not proof of tampering.

Usage: python splice_check.py FILE [--start S] [--dur D] [--fh 100] [--json]
"""
from __future__ import annotations

import argparse
import json
import os

import numpy as np
from scipy.signal import butter, hilbert, sosfiltfilt
from scipy.ndimage import median_filter

from speed_check import load_audio, snr_spectrum, to_analysis_rate, parabolic_peak

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PARAMS = dict(
    sr=2000, bw0=0.2, bw1=0.03, frame_s=0.1, w_s=1.0, ctx_s=5.0, edge_s=2.5,
    t_line=12.0,        # dB above background for a usable ENF line
    max_n=19, max_f=950.0, grids=(50.0, 60.0), line_tol_rel=0.006,
    theta=1.0,          # radians; overwritten by splice_params.json (dev-tuned)
)
_PARAMS_FILE = os.path.join(HERE, "splice_params.json")


def load_params():
    p = dict(DEFAULT_PARAMS)
    if os.path.exists(_PARAMS_FILE):
        p.update(json.load(open(_PARAMS_FILE)))
    return p


def pick_line(x, sr, p):
    f, P, snr = snr_spectrum(x, sr, p["max_f"] + 5, 4.0, df_target=0.02)
    best = None
    for g in p["grids"]:
        for n in range(1, p["max_n"] + 1):
            fc = n * g
            if fc > p["max_f"]:
                continue
            tol = fc * p["line_tol_rel"] + 0.6 / (len(x) / sr)
            lo, hi = np.searchsorted(f, [fc - tol, fc + tol])
            if hi <= lo:
                continue
            i = lo + int(np.argmax(snr[lo:hi]))
            if best is None or snr[i] > best[3]:
                best = (g, n, float(parabolic_peak(f, P, i)[0]), float(snr[i]))
    return best  # (grid, n, f_line, snr_db)


def phase_track(x, sr, fh, p, n=2):
    bw = p["bw0"] + p["bw1"] * n      # ENF excursions scale with the harmonic index
    sos = butter(2, [fh - bw, fh + bw], btype="bandpass", fs=sr, output="sos")
    y = sosfiltfilt(sos, x)
    t = np.arange(len(y)) / sr
    z = hilbert(y) * np.exp(-2j * np.pi * fh * t)
    L = int(round(p["frame_s"] * sr))
    nf = len(z) // L
    zf = z[: nf * L].reshape(nf, L).mean(axis=1)
    tf = (np.arange(nf) + 0.5) * p["frame_s"]
    return tf, zf


def jump_statistic(zf, p):
    dphi = np.angle(zf[1:] * np.conj(zf[:-1]))           # per-frame increments
    phi = np.concatenate([[0.0], np.cumsum(dphi)])        # unwrapped phase
    w = int(round(p["w_s"] / p["frame_s"]))
    c = int(round(p["ctx_s"] / p["frame_s"]))
    n = len(phi)
    J = np.full(n, np.nan)
    slope = median_filter(dphi, size=2 * c + 1, mode="nearest")   # natural local frequency
    for k in range(w, n - w):
        s = slope[min(k, len(slope) - 1)]
        J[k] = abs(np.angle(np.exp(1j * (phi[k + w] - phi[k - w] - s * 2 * w))))
    return J


def analyse(x, sr, params=None, fh=None):
    p = dict(load_params() if params is None else params)
    x = to_analysis_rate(np.asarray(x, float), sr, p["sr"])
    sr = p["sr"]
    T = len(x) / sr
    line = pick_line(x, sr, p)
    out = dict(duration_s=round(T, 3))
    if fh is None:
        if line is None or line[3] < p["t_line"]:
            out.update(decision="NO_GRID_SIGNAL", line=None, max_jump_rad=None, candidates_s=[])
            return out
        fh = line[2]
    out["line"] = dict(grid=line[0], n=line[1], f_hz=round(line[2], 4), snr_db=round(line[3], 1)) if line else None
    tf, zf = phase_track(x, sr, fh, p, n=line[1] if line else max(1, round(fh / 50)))
    J = jump_statistic(zf, p)
    e = int(round(p["edge_s"] / p["frame_s"]))
    Jv = J.copy(); Jv[:e] = np.nan; Jv[-e:] = np.nan
    if np.all(np.isnan(Jv)):
        out.update(decision="TOO_SHORT", max_jump_rad=None, candidates_s=[])
        return out
    k = int(np.nanargmax(Jv))
    mx = float(Jv[k])
    cands = []
    above = np.where(Jv > p["theta"])[0]
    if len(above):
        # one candidate per contiguous run, at its maximum
        runs = np.split(above, np.where(np.diff(above) > 1)[0] + 1)
        cands = [round(float(tf[r[np.nanargmax(Jv[r])]]), 2) for r in runs]
    out.update(decision="SPLICE_SUSPECTED" if mx > p["theta"] else "NO_SPLICE_DETECTED",
               max_jump_rad=round(mx, 3), median_jump_rad=round(float(np.nanmedian(Jv)), 3), t_max_jump_s=round(float(tf[k]), 2), candidates_s=cands,
               theta_rad=p["theta"], f_track_hz=round(fh, 4))
    out["_trace"] = (tf, J, np.unwrap(np.angle(zf)))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file"); ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--dur", type=float, default=None); ap.add_argument("--fh", type=float, default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    x, sr = load_audio(a.file, a.start, a.dur)
    r = analyse(x, sr, fh=a.fh)
    r.pop("_trace", None)
    r["file"] = a.file
    print(json.dumps(r, indent=1) if a.json else
          f"{a.file}: {r['decision']}  max_jump={r.get('max_jump_rad')} rad at {r.get('t_max_jump_s')} s  "
          f"candidates={r.get('candidates_s')}  line={r.get('line')}")
    return r


if __name__ == "__main__":
    main()
