"""Animated GIF of the REAL blind search (venue video vs 36 h of GB grid). Run from the repo root:
python results/animations/make_scan_gif.py --trace experiments/team_recordings_venue/A001_11081142_C004/video_rs_trace_dark.csv --ref <elexon_live.parquet>"""
import argparse, sys
from pathlib import Path
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, PillowWriter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ghostclock.tools.blind_match import smooth, ncc_scan  # noqa: E402

ap = argparse.ArgumentParser(); ap.add_argument("--trace", required=True); ap.add_argument("--ref", required=True)
ap.add_argument("--out", default=str(ROOT / "results/animations/blind_scan_36h_REAL.gif"))
a = ap.parse_args()
tr = np.loadtxt(a.trace, delimiter=",", skiprows=1)
tt = np.arange(np.ceil(tr[0, 0]), np.floor(tr[-1, 0]) + 1)
ff = np.interp(tt, tr[:, 0], tr[:, 1]); qq = np.interp(tt, tr[:, 0], tr[:, 2])
good = (qq >= 15) & (np.abs(ff - np.median(ff)) < 0.15)
w = good + 1e-6; ff = np.where(good, ff, np.median(ff[good]))
e = pd.read_parquet(a.ref); s0 = int(pd.Timestamp("2026-11-07T00:00Z").timestamp()); s1 = int(pd.Timestamp("2026-11-08T12:22:35Z").timestamp())
e = e[(e.ts_utc >= s0) & (e.ts_utc < s1)].dropna(); e = e[(e.f_hz > 49) & (e.f_hz < 51)]
rt = np.arange(int(e.ts_utc.min()), int(e.ts_utc.max()) + 1); rf = smooth(np.interp(rt, e.ts_utc, e.f_hz), 16)
sc = ncc_scan(rf, ff, w); x = (rt[: len(sc)] - tt[0] - s0) / 3600.0
nb = 1400; edges = np.linspace(0, len(sc), nb + 1).astype(int)
xb = np.array([x[i:j][np.argmax(sc[i:j])] for i, j in zip(edges[:-1], edges[1:])])
yb = np.array([sc[i:j].max() for i, j in zip(edges[:-1], edges[1:])])
ib = int(np.argmax(yb)); best_t = pd.to_datetime(s0 + xb[ib] * 3600, unit="s").strftime("%H:%M:%S")

plt.rcParams.update({"font.family": "DejaVu Sans"})
fig, ax = plt.subplots(figsize=(8, 3.0), dpi=90); fig.patch.set_facecolor("#0b0f17"); ax.set_facecolor("#0b0f17")
for s in ax.spines.values(): s.set_color("#2a3242")
ax.tick_params(colors="#8b95a7", labelsize=8); ax.set_xlim(0, xb.max()); ax.set_ylim(-0.9, 1.08)
ax.set_xticks([0, 6, 12, 18, 24, 30, 36]); ax.set_xticklabels(["7 Nov 00:00", "06:00", "12:00", "18:00", "8 Nov 00:00", "06:00", "12:00"])
ax.axhline(0.847, color="#ff5d73", ls="--", lw=0.9); ax.text(0.3, 0.87, "best score on 7 wrong days (0.847)", color="#ff5d73", fontsize=7)
line, = ax.plot([], [], color="#7aa2c8", lw=0.7); cur = ax.axvline(0, color="#e8eef8", lw=0.8, alpha=0.6)
dot = ax.scatter([], [], s=60, color="#5ef0b3", zorder=5)
title = ax.set_title("Blind search: our venue video vs 36 h of GB grid frequency", color="#e8eef8", fontsize=10, loc="left")
lab = ax.text(0.99, 0.05, "", transform=ax.transAxes, ha="right", color="#5ef0b3", fontsize=10, weight="bold")
ax.set_ylabel("match score", color="#8b95a7", fontsize=8)
N = 60; HOLD = 25

def frame(k):
    n = min(nb, int(nb * (k + 1) / N))
    line.set_data(xb[:n], yb[:n]); cur.set_xdata([xb[n - 1]] * 2)
    if n >= ib + 1:
        dot.set_offsets([[xb[ib], yb[ib]]]); lab.set_text(f"match: 8 Nov {best_t} UTC  (score {yb[ib]:.3f})")
    return line, cur, dot, lab

fig.tight_layout()
FuncAnimation(fig, frame, frames=N + HOLD, blit=False).save(a.out, writer=PillowWriter(fps=15))
print("wrote", a.out, "best", best_t, round(float(yb[ib]), 3))
