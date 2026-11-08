"""Re-run C4's rolling-shutter pipeline on a DARK clip from cached cells, with a low brightness floor.
usage: python work/director/dark_video_check.py <quick_dir> [--lo 3]"""
import sys, json, argparse
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "work" / "C4"))
import rs_enf as c4

ap = argparse.ArgumentParser(); ap.add_argument("qdir"); ap.add_argument("--lo", type=float, default=3.0)
a = ap.parse_args()
q = Path(a.qdir)
d = np.load(q / "cells.npz", allow_pickle=True)
cells, pts, clipf, meta = d["cells"], d["pts"], d["clipf"], d["meta"].item()
m = cells.mean(axis=0)
print(f"cells {cells.shape}; cell mean brightness pct 5/50/95 = {np.percentile(m,[5,50,95]).round(1)}; clipped frac median {np.median(clipf):.3f}")
# low-light: clip_lo=18 counted dark pixels as 'clipped'; recompute clip only for highs is not possible
# from cache, so ignore clipf for dark cells and use brightness window [lo, 225].
mask = (m > a.lo) & (m < 225)
print("static/usable cells:", int(mask.sum()), "of", mask.size)
t, fps, tinfo = c4.regular_frame_times(pts)
f0 = 100.0
al, _ = c4.alias_of(f0, fps)
s, naive, rows, motion = c4.row_signals(cells, mask, fps, 60.0)
n_use = len(t)
Tro, grid, sc = c4.estimate_Tro(s, t, fps, meta["H"], meta["row_bin"], f0, rows, n_use=n_use)
win = 8.0
tc, fe, qq, z = c4.rs_enf_trace(s, t, fps, meta["H"], meta["row_bin"], Tro, 50.0, rows, win)
fe = np.asarray(fe); qq = np.asarray(qq)
good = qq >= 20
res = {"fps": fps, "alias_hz": al, "Tro_ms": Tro * 1e3, "rows_used": int(rows.sum()), "usable_cells": int(mask.sum()),
       "windows": int(len(fe)), "median_q_db": float(np.median(qq)), "frac_q_ge_20": float(good.mean()),
       "median_hz": float(np.median(fe)), "range_mhz": float((np.percentile(fe, 95) - np.percentile(fe, 5)) * 1e3)}
print(json.dumps(res, indent=1))
np.savetxt(q / "video_rs_trace_dark.csv", np.c_[tc, fe, qq], delimiter=",", header="t_s,enf_hz,q_db", comments="")
json.dump(res, open(q / "video_dark_report.json", "w"), indent=1)
# compare to audio trace if present
af = q / "audio_trace.csv"
if af.exists():
    at = np.loadtxt(af, delimiter=",", skiprows=1)
    fi = np.interp(tc, at[:, 0], at[:, 1], left=np.nan, right=np.nan)
    mm = np.isfinite(fi)
    if mm.sum() > 5:
        print(f"audio-vs-video: corr {np.corrcoef(fe[mm], fi[mm])[0,1]:.3f}, mean diff {np.mean(fe[mm]-fi[mm])*1e3:.1f} mHz over {mm.sum()} windows")
