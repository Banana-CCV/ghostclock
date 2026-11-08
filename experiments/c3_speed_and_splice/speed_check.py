"""GhostClock C3 -- no-reference playback-speed check from mains hum (ENF).

Idea: if a recording is played back k times faster (pitch+tempo, e.g. sped-up
CCTV), every mains-hum line n*f_grid moves to n*f_grid*k. We search the hum
family's base frequency b in [25, 120] Hz with a harmonic-sum (comb) score over
a long-window, zero-padded spectrum, then test the hypotheses

    H50: b ~ 50 Hz (k = 1, 50 Hz grid)     H60: b ~ 60 Hz (k = 1, 60 Hz grid)
    Hk : best b anywhere in range  -> k = b/50 (or b/60)

and require the explained lines to form a consistent harmonic family.

Decisions: CONSISTENT_WITH_REALTIME / SPEED_ALTERED_REVIEW / NO_GRID_SIGNAL /
AMBIGUOUS_50_vs_60.  A decision is a triage flag for a human reviewer, never
proof of tampering.

Usage:
    python speed_check.py FILE [--grid 50] [--start S] [--dur D] [--json]
FILE can be any audio file soundfile reads, or any audio/video ffmpeg reads.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import tempfile

import numpy as np
import soundfile as sf
from scipy.ndimage import maximum_filter1d, median_filter
from scipy.signal import resample_poly
from scipy import fft as sp_fft

HERE = os.path.dirname(os.path.abspath(__file__))

# --------------------------------------------------------------------------
# Parameters. THRESHOLDS ARE FIXED ON DEV ONLY (see tune_speed.py / RESULTS.json)
# --------------------------------------------------------------------------
DEFAULT_PARAMS = dict(
    sr=2500,            # analysis sample rate (Hz)
    fmin=24.0,          # lowest line considered (Hz)
    fmax=1000.0,        # highest harmonic considered (Hz)
    b_lo=25.0, b_hi=120.0, b_step=0.005,   # base-frequency search grid (Hz)
    bg_width_hz=4.0,    # running-median background width
    t_line=12.0,        # dB above background for a slot to count as a hum line
    t_present=8.0,      # dB above background for a slot to count as "not missing"
    w_cap=25.0,         # cap on per-line excess (dB)
    w_bonus=3.0,        # bonus per explained line
    lam=1.5,            # penalty per missing harmonic slot below the top explained one
    tol0=0.6,           # tolerance: tol(f) = tol0/T + tol1*f  (Hz)
    tol1=0.0005,
    grid_tol_hz=0.2,    # GB operational band (+/-0.2 Hz, NESO); statutory is +/-1%
    k_tol=0.006,        # |k-1| allowed for the k=1 hypotheses (grid band + measurement)
    n_harm=12,          # harmonics 1..n_harm of each candidate base
    s_k1=10.0,          # min score of the k=1 (50/60 Hz) family to call it present
    margin=1e9,         # H50/H60 accepted only if score >= best - margin
    amb_margin=3.0,     # 50 vs 60 ambiguous if both present and scores within this
    s_alt=20.0,         # min score of the off-nominal family to flag SPEED_ALTERED
    min_lines_alt=2,    # minimum explained lines for SPEED_ALTERED
    n_boot=400,
)

_PARAMS_FILE = os.path.join(HERE, "speed_params.json")


def load_params() -> dict:
    p = dict(DEFAULT_PARAMS)
    if os.path.exists(_PARAMS_FILE):
        with open(_PARAMS_FILE) as fh:
            p.update(json.load(fh))
    return p


# --------------------------------------------------------------------------
# I/O
# --------------------------------------------------------------------------
def find_ffmpeg() -> str:
    pats = [os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*\*\bin\ffmpeg.exe")]
    for p in pats:
        hits = sorted(glob.glob(p))
        if hits:
            return hits[-1]
    return "ffmpeg"


def load_audio(path: str, start: float = 0.0, dur: float | None = None):
    """Return mono float64 signal and its sample rate (video -> audio track via ffmpeg)."""
    try:
        info = sf.info(path)
        sr = info.samplerate
        a = int(start * sr)
        b = None if dur is None else a + int(dur * sr)
        x, sr = sf.read(path, start=a, stop=b, always_2d=True)
        return x.mean(axis=1), sr
    except Exception:
        pass
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "a.wav")
        cmd = [find_ffmpeg(), "-v", "error", "-y", "-ss", str(start), "-i", path]
        if dur is not None:
            cmd += ["-t", str(dur)]
        cmd += ["-vn", "-ac", "1", "-c:a", "pcm_s16le", out]
        subprocess.run(cmd, check=True)
        x, sr = sf.read(out, always_2d=True)
        return x.mean(axis=1), sr


def to_analysis_rate(x, sr, target):
    if sr == target:
        return x.astype(float)
    from math import gcd
    g = gcd(int(sr), int(target))
    return resample_poly(x.astype(float), int(target) // g, int(sr) // g)


# --------------------------------------------------------------------------
# Spectrum helpers
# --------------------------------------------------------------------------
def snr_spectrum(x, sr, fmax, bg_width_hz, df_target=0.02):
    """Long-window Hann spectrum (zero-padded) and SNR in dB vs a running median."""
    x = x - x.mean()
    n = len(x)
    nfft = 1 << int(np.ceil(np.log2(max(4 * n, sr / df_target))))
    X = sp_fft.rfft(x * np.hanning(n), nfft, workers=-1)
    nkeep = int((fmax + 5) * nfft / sr) + 1
    X = X[:nkeep]
    f = np.arange(nkeep) * (sr / nfft)
    keep = slice(None)
    P = 10 * np.log10(np.abs(X[keep]) ** 2 + 1e-30)
    df = f[1] - f[0]
    # background on a decimated grid (~native resolution / 2) for speed
    step = max(1, int(round((0.5 / (n / sr)) / df)))
    Pc = P[::step]
    w = max(3, int(round(bg_width_hz / (df * step))) | 1)
    bg = median_filter(Pc, size=w, mode="nearest")
    bg = np.interp(f, f[::step], bg)
    return f, P, P - bg


def parabolic_peak(f, y, i):
    if 0 < i < len(y) - 1:
        a, b, c = y[i - 1], y[i], y[i + 1]
        den = a - 2 * b + c
        d = 0.5 * (a - c) / den if den != 0 else 0.0
        d = float(np.clip(d, -0.5, 0.5))
        return f[i] + d * (f[1] - f[0]), b - 0.25 * (a - c) * d
    return f[i], y[i]


# --------------------------------------------------------------------------
# Comb search
# --------------------------------------------------------------------------
def comb_parts(f, snr, T, p):
    """Harmonic-sum comb over base b: returns b grid, summed line excess, #lines, #missing slots.

    score(b) = sum_n w_n(b) - lam * missing(b), n = 1..n_harm, n*b in [fmin, fmax].
    w_n = min(SNR, w_cap) - t_line + w_bonus where SNR(n*b) >= t_line (max over +/-tol).
    missing = slots below the highest explained harmonic whose SNR < t_present.
    """
    df = f[1] - f[0]
    tol_rep = p["tol0"] / T + p["tol1"] * 300.0
    win = max(1, int(round(2 * tol_rep / df)) | 1)
    smax = maximum_filter1d(snr, size=win, mode="nearest")
    b = np.arange(p["b_lo"], p["b_hi"] + 1e-9, p["b_step"])
    n = np.arange(1, int(p["n_harm"]) + 1)
    F = b[:, None] * n[None, :]
    valid = (F >= p["fmin"]) & (F <= p["fmax"])
    S = np.interp(F.ravel(), f, smax).reshape(F.shape)
    S[~valid] = -np.inf
    hit = S >= p["t_line"]
    present = S >= p["t_present"]
    w = np.where(hit, np.minimum(S, p["w_cap"]) - p["t_line"] + p["w_bonus"], 0.0)
    idx = np.where(hit, n[None, :], 0).max(axis=1)
    below_top = (n[None, :] <= idx[:, None]) & valid
    missing = (below_top & ~present).sum(axis=1)
    return b, w.sum(axis=1), hit.sum(axis=1), missing


def refine_base(f, P, snr, b0, T, p, max_n=None):
    """LS fit f_n = n*b over local peaks near n*b0 that pass t_line. Returns b, lines."""
    lines = []
    nmax = min(int(p["n_harm"]), int(np.floor(p["fmax"] / b0)))
    for n in range(1, nmax + 1):
        fc = n * b0
        if fc < p["fmin"]:
            continue
        tol = p["tol0"] / T + p["tol1"] * fc
        lo, hi = np.searchsorted(f, [fc - tol, fc + tol])
        if hi <= lo:
            continue
        i = lo + int(np.argmax(snr[lo:hi]))
        if snr[i] < p["t_line"]:
            continue
        fp, _ = parabolic_peak(f, P, i)
        lines.append((n, float(fp), float(snr[i])))
    if not lines:
        return b0, lines
    nn = np.array([l[0] for l in lines], float)
    ff = np.array([l[1] for l in lines])
    ww = np.minimum(np.array([l[2] for l in lines]), p["w_cap"]) - p["t_line"] + p["w_bonus"]
    b = float(np.sum(ww * nn * ff) / np.sum(ww * nn * nn))
    return b, lines


def measure_lines_at(x, sr, b, harmonics, p):
    """Base-frequency estimate in one sub-window using known harmonic indices."""
    T = len(x) / sr
    f, P, snr = snr_spectrum(x, sr, p["fmax"], p["bg_width_hz"], df_target=0.02)
    num = den = 0.0
    for n in harmonics:
        fc = n * b
        tol = p["tol0"] / T + p["tol1"] * fc + 0.5 / T
        lo, hi = np.searchsorted(f, [fc - tol, fc + tol])
        if hi <= lo:
            continue
        i = lo + int(np.argmax(snr[lo:hi]))
        if snr[i] < p["t_present"]:
            continue
        fp, _ = parabolic_peak(f, P, i)
        w = min(snr[i], p["w_cap"])
        num += w * n * fp
        den += w * n * n
    return num / den if den > 0 else np.nan


# --------------------------------------------------------------------------
# Main analysis
# --------------------------------------------------------------------------
def features(x, sr, p, lams=None):
    """Spectrum + comb features. Returns (feat dict per lambda, spectrum tuple)."""
    x = to_analysis_rate(np.asarray(x, float), sr, p["sr"])
    sr = p["sr"]
    T = len(x) / sr
    f, P, snr = snr_spectrum(x, sr, p["fmax"], p["bg_width_hz"])
    b, wsum, nlines, missing = comb_parts(f, snr, T, p)
    kt = p["k_tol"]
    m50 = (b >= 50 * (1 - kt)) & (b <= 50 * (1 + kt))
    m60 = (b >= 60 * (1 - kt)) & (b <= 60 * (1 + kt))
    out = {}
    for lam in (lams or [p["lam"]]):
        score = wsum - lam * missing
        j50 = np.flatnonzero(m50)[np.argmax(score[m50])]
        j60 = np.flatnonzero(m60)[np.argmax(score[m60])]
        jb = int(np.argmax(score))
        out[lam] = dict(T=T, s50=float(score[j50]), b50=float(b[j50]), n50=int(nlines[j50]),
                        s60=float(score[j60]), b60=float(b[j60]), n60=int(nlines[j60]),
                        sbest=float(score[jb]), bbest=float(b[jb]), nbest=int(nlines[jb]),
                        best_in_k1=bool(m50[jb] or m60[jb]))
    return out, (x, sr, T, f, P, snr, b)


def decide(ft, p):
    """Decision from comb features (pure function of thresholds fixed on dev)."""
    s50, s60, sb = ft["s50"], ft["s60"], ft["sbest"]
    sk1 = max(s50, s60)
    if sk1 >= p["s_k1"] and sk1 >= sb - p["margin"]:
        if min(s50, s60) >= p["s_k1"] and abs(s50 - s60) <= p["amb_margin"]:
            return "AMBIGUOUS_50_vs_60"
        return "CONSISTENT_WITH_REALTIME"
    if sb >= p["s_alt"] and ft["nbest"] >= p["min_lines_alt"] and not ft["best_in_k1"]:
        return "SPEED_ALTERED_REVIEW"
    if sk1 >= p["s_k1"]:
        return "CONSISTENT_WITH_REALTIME"
    return "NO_GRID_SIGNAL"


def analyse(x, sr, params=None, grid=50.0, ci=True, seed=0, return_debug=False):
    p = dict(load_params() if params is None else params)
    fts, (x, sr, T, f, P, snr, b) = features(x, sr, p)
    ft = fts[p["lam"]]
    decision = decide(ft, p)
    out = dict(decision=decision, duration_s=round(T, 3),
               score_50=round(ft["s50"], 2), score_60=round(ft["s60"], 2),
               score_best=round(ft["sbest"], 2), b_best=round(ft["bbest"], 4))
    if decision in ("CONSISTENT_WITH_REALTIME", "AMBIGUOUS_50_vs_60"):
        b_sel, g_sel = (ft["b50"], 50.0) if ft["s50"] >= ft["s60"] else (ft["b60"], 60.0)
    elif decision == "SPEED_ALTERED_REVIEW":
        b_sel, g_sel = ft["bbest"], float(grid)
    else:
        b_sel, g_sel = np.nan, float(grid)
    lines = []
    if np.isfinite(b_sel):
        b_sel, lines = refine_base(f, P, snr, b_sel, T, p)
    out["grid_assumed"] = g_sel
    out["n_lines"] = len(lines)
    out["lines"] = [dict(n=n, f_hz=round(fr, 4), snr_db=round(s, 1)) for n, fr, s in lines]
    if not np.isfinite(b_sel):
        out.update(k=None, k_ci95=None, base_hz=None)
    else:
        out["base_hz"] = round(b_sel, 4)
        out["k"] = round(b_sel / g_sel, 5)
        out["k_alternatives"] = {"if_50Hz_grid": round(b_sel / 50, 5), "if_60Hz_grid": round(b_sel / 60, 5),
                                 # octave ambiguity: the base found may really be the 100 Hz
                                 # (2 x 50) family with the true fundamental absent
                                 "if_base_is_100Hz_family": round(b_sel / 100, 5)}
        out["k_ci95"], out["k_ci95_incl_grid_band"] = (None, None)
        if ci and lines:
            out["k_ci95"], out["k_ci95_incl_grid_band"] = _bootstrap_ci(x, sr, b_sel, [l[0] for l in lines], g_sel, p, seed)
    if return_debug:
        out["_debug"] = dict(f=f, snr=snr, P=P)
    return out


def _bootstrap_ci(x, sr, b, harmonics, g, p, seed):
    """95% CI of k by bootstrap over sub-windows (length T/2, hop T/8 -> 5 windows)."""
    n = len(x)
    L = n // 2
    hop = max(1, n // 8)
    ests = []
    for s in range(0, n - L + 1, hop):
        e = measure_lines_at(x[s:s + L], sr, b, harmonics, p)
        if np.isfinite(e):
            ests.append(e)
    if len(ests) < 2:
        return None, None
    ests = np.array(ests)
    rng = np.random.default_rng(seed)
    bs = rng.choice(ests, size=(p["n_boot"], len(ests)), replace=True).mean(axis=1)
    lo, hi = np.percentile(bs, [2.5, 97.5])
    # centre the interval on the full-window estimate (sub-window mean can be biased)
    lo, hi = b - (np.mean(bs) - lo), b + (hi - np.mean(bs))
    gt = p["grid_tol_hz"]
    return ([round(float(lo / g), 5), round(float(hi / g), 5)],
            [round(float(lo / (g + gt)), 5), round(float(hi / (g - gt)), 5)])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    ap.add_argument("--grid", type=float, default=50.0, help="expected grid for k reporting (GB: 50)")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--dur", type=float, default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    x, sr = load_audio(a.file, a.start, a.dur)
    r = analyse(x, sr, grid=a.grid)
    r["file"] = a.file
    if a.json:
        print(json.dumps(r, indent=1))
    else:
        print(f"{a.file}: {r['decision']}  k={r.get('k')}  CI95={r.get('k_ci95')}  "
              f"(incl. grid band {r.get('k_ci95_incl_grid_band')})  base={r.get('base_hz')} Hz  lines={r['n_lines']}")
        for l in r["lines"]:
            print(f"   n={l['n']:2d}  {l['f_hz']:9.4f} Hz  SNR {l['snr_db']:.1f} dB")
    return r


if __name__ == "__main__":
    main()
