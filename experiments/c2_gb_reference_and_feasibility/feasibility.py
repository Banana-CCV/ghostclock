"""Semi-synthetic feasibility probe: can a 1 s / 15 s GB reference date an ENF segment?

Real NESO 1 s data (Aug + Sep 2026, Sep-15 flat-filled outage masked) -> cut N random
segments of D minutes, add white Gaussian noise sigma = 2 mHz (SEMI-SYNTHETIC: real grid
ENF, synthetic measurement noise), search each in a 24 h window containing it with
mean-removed normalised cross-correlation (NCC, FFT-based) against:
  ref_1s      : the 1 s reference
  ref_15s_pt  : the reference point-sampled every 15 s (on the absolute ts % 15 == 0 grid,
                the way Elexon FREQ is stamped)
  ref_15s_avg : 15 s block means of the reference (blocks [15i, 15i+15))
For the 15 s references the query is reduced the same way for each of the 15 sub-step
phases (point-sample / block-mean of the query), so the search keeps 1 s resolution.
Success = |top-1 start - true start| <= 15 s.

Usage: python -I work/C2/feasibility.py [--n 1000] [--seed 0]
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import fftconvolve

ROOT = Path(__file__).resolve().parents[2]
GB = ROOT / "datasets" / "raw" / "gb"
MONTHS = ["2026_08", "2026_09"]
DURS_MIN = [2, 5, 10, 20]
SIGMA = 0.002
WIN = 86400
TOL = 15


def load_series():
    parts = []
    for m in MONTHS:
        df = pd.read_parquet(GB / f"neso_{m}.parquet")
        side = json.loads((GB / f"neso_{m}.json").read_text())
        f = df.f_hz.values.astype(float).copy()
        t = df.ts_utc.values
        for a, b in side.get("bad_intervals", []):
            f[(t >= a) & (t <= b)] = np.nan
        parts.append((t, f))
    t = np.concatenate([p[0] for p in parts])
    f = np.concatenate([p[1] for p in parts])
    assert np.all(np.diff(t) == 1), "series must be contiguous 1 s"
    return t, f


def ncc_scores(q, r):
    """Mean-removed NCC of template q against every placement in r (len(r)-len(q)+1)."""
    L = len(q)
    qz = q - q.mean()
    qn = np.sqrt(np.sum(qz ** 2))
    num = fftconvolve(r, qz[::-1], mode="valid")
    cs = np.r_[0.0, np.cumsum(r)]
    cs2 = np.r_[0.0, np.cumsum(r * r)]
    s = cs[L:] - cs[:-L]
    s2 = cs2[L:] - cs2[:-L]
    var = np.maximum(s2 - s * s / L, 1e-18)
    return num / (qn * np.sqrt(var) + 1e-18)


def search_1s(q, r):
    sc = ncc_scores(q, r)
    return int(np.argmax(sc)), float(sc.max())


def search_15(q, r, w0, mode, r15=None):
    """r is the 1 s window starting at absolute second w0 (used only to build the 15 s ref,
    unless r15 - a real 15 s series on the same absolute grid - is given).
    Returns best start offset (1 s resolution) within the window."""
    # absolute 15-s grid inside the window
    g0 = (-w0) % 15                      # first window index on the absolute grid
    n15 = (len(r) - g0) // 15
    if r15 is not None:
        pass
    elif mode == "pt":
        r15 = r[g0:g0 + 15 * n15:15]
    else:
        r15 = r[g0:g0 + 15 * n15].reshape(n15, 15).mean(axis=1)
    best = (-np.inf, None)
    L = len(q)
    for ph in range(15):
        # Let candidate start c = g0 + 15*k - j for j in 0..14 => query index j lands on grid point k.
        j = ph
        if mode == "pt":
            qs = q[j::15]
        else:
            nb = (L - j) // 15
            qs = q[j:j + 15 * nb].reshape(nb, 15).mean(axis=1)
        if len(qs) < 4:
            continue
        sc = ncc_scores(qs, r15)
        k = int(np.argmax(sc))
        c = g0 + 15 * k - j
        if sc[k] > best[0] and c >= 0:
            best = (float(sc[k]), c)
    return best[1], best[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--durs", type=str, default=",".join(map(str, DURS_MIN)), help="comma list of minutes")
    ap.add_argument("--out", type=str, default="feasibility.json")
    ap.add_argument("--sigma", type=float, default=SIGMA, help="noise std in Hz (default 0.002)")
    ap.add_argument("--elexon", action="store_true",
                    help="only method ref_elexon_real: query from NESO 1 s, reference = REAL Elexon 15 s")
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)
    t, f = load_series()
    N = len(f)
    if args.elexon:
        e = pd.concat([pd.read_parquet(GB / f"elexon_{m}.parquet") for m in MONTHS])
        e_at = np.full(N, np.nan)
        i = e.ts_utc.values - t[0]
        ok = (i >= 0) & (i < N)
        e_at[i[ok]] = e.f_hz.values[ok]
    res = {}
    t_start = time.time()
    for Dm in [int(x) for x in args.durs.split(",")]:
        D = Dm * 60
        hits = {"ref_elexon_real": 0} if args.elexon else {"ref_1s": 0, "ref_15s_pt": 0, "ref_15s_avg": 0}
        errs = {k: [] for k in hits}
        n = 0
        while n < args.n:
            s = int(rng.integers(0, N - D))
            w = s - int(rng.integers(0, WIN - D + 1))
            if w < 0 or w + WIN > N:
                continue
            r = f[w:w + WIN]
            if np.isnan(r).any():
                continue
            q = f[s:s + D] + rng.normal(0, args.sigma, D)
            true = s - w
            if args.elexon:
                g0 = (-int(t[w])) % 15
                n15 = (WIN - g0) // 15
                r15 = e_at[w + g0:w + g0 + 15 * n15:15]
                if np.isnan(r15).any():
                    continue
                found = (("ref_elexon_real", search_15(q, r, int(t[w]), "pt", r15=r15)[0]),)
            else:
                found = (("ref_1s", search_1s(q, r)[0]), ("ref_15s_pt", search_15(q, r, int(t[w]), "pt")[0]),
                         ("ref_15s_avg", search_15(q, r, int(t[w]), "avg")[0]))
            for k, c in found:
                e = abs(c - true) if c is not None else 10 ** 9
                errs[k].append(e)
                hits[k] += e <= TOL
            n += 1
        res[f"D={Dm}min"] = {
            "n": n,
            **{f"P_top1_within_15s_{k}": round(hits[k] / n, 4) for k in hits},
            **{f"median_abs_err_s_{k}": float(np.median(errs[k])) for k in errs},
        }
        print(Dm, res[f"D={Dm}min"], f"{time.time() - t_start:.0f}s", flush=True)
    out = {
        "label": "SEMI-SYNTHETIC: real NESO 1 s GB frequency (Aug-Sep 2026) + white Gaussian noise",
        "sigma_hz": args.sigma, "method_set": "elexon_real" if args.elexon else "neso_decimated", "search_window_s": WIN, "tolerance_s": TOL, "metric": "mean-removed NCC, top-1",
        "seed": args.seed, "reference_months": MONTHS, "results": res,
    }
    (Path(__file__).parent / args.out).write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
