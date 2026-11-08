"""Decode a (dark) phone video into rolling-shutter cells and extract the ENF trace (C4 method, dark-scene mask).
usage: python -m ghostclock.tools.decode_and_extract <video> [--lo 3] [--win 16]"""
import sys, json, argparse, time
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from ghostclock import rs_enf as c4
from ghostclock._paths import OUT_DIR

ap = argparse.ArgumentParser(); ap.add_argument("video"); ap.add_argument("--lo", type=float, default=3.0)
ap.add_argument("--win", type=float, default=16.0)
a = ap.parse_args()
q = OUT_DIR / "quick" / Path(a.video).stem
q.mkdir(parents=True, exist_ok=True)
cache = q / "cells.npz"
t0 = time.time()
if not cache.exists():
    cells, pts, clipf, meta, _ = c4.decode_cells(a.video, row_bin=4, n_col=16)
    np.savez(cache, cells=cells, pts=pts, clipf=clipf, meta=np.array(meta), kept=np.zeros(0))
else:
    d = np.load(cache, allow_pickle=True); cells, pts, clipf, meta = d["cells"], d["pts"], d["clipf"], d["meta"].item()
print(f"decoded {cells.shape} in {time.time()-t0:.0f}s", flush=True)
m = cells.mean(axis=0)
mask = (m > a.lo) & (m < 225)
t, fps, tinfo = c4.regular_frame_times(pts)
s, naive, rows, motion = c4.row_signals(cells, mask, fps, 60.0)
Tro, grid, sc = c4.estimate_Tro(s, t, fps, meta["H"], meta["row_bin"], 100.0, rows, n_use=min(len(t), int(180 * fps)))
tc, fe, qq, z = c4.rs_enf_trace(s, t, fps, meta["H"], meta["row_bin"], Tro, 50.0, rows, a.win)
fe, qq = np.asarray(fe), np.asarray(qq)
res = {"video": a.video, "frames": int(cells.shape[0]), "fps": fps, "Tro_ms": Tro * 1e3, "brightness_p50": float(np.median(m)),
       "usable_cells": int(mask.sum()), "windows": int(len(fe)), "median_q_db": float(np.median(qq)),
       "frac_q_ge_20": float((qq >= 20).mean()), "median_hz": float(np.median(fe)),
       "range_mhz_p5_p95": float((np.percentile(fe, 95) - np.percentile(fe, 5)) * 1e3), "timing": tinfo}
np.savetxt(q / "video_rs_trace_dark.csv", np.c_[tc, fe, qq], delimiter=",", header="t_s,enf_hz,q_db", comments="")
json.dump(res, open(q / "video_dark_report.json", "w"), indent=1, default=float)
print(json.dumps(res, indent=1, default=float))
