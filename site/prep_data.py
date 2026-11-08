# Regenerates site/data/*.json from the repo + a local Elexon live archive (set GHOSTCLOCK_ELEXON_LIVE).
import sys, json
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
import numpy as np, pandas as pd
from ghostclock.tools import blind_match as bm
R = str(__import__("pathlib").Path(__file__).resolve().parents[1])
OUT = R + r"\site\data"
tr = np.loadtxt(R + r"\experiments\team_recordings_venue\A001_11081142_C004\video_rs_trace_dark.csv", delimiter=",", skiprows=1)
t, f, q = tr[:,0], tr[:,1], tr[:,2]
# trace json
trace = {"t": [round(x,2) for x in t], "f": [round(x,5) if qq>=15 else None for x,qq in zip(f,q)],
         "source": "experiments/team_recordings_venue/A001_11081142_C004/video_rs_trace_dark.csv (q_db>=15 shown)"}
json.dump(trace, open(OUT+r"\trace.json","w"), separators=(",",":"))
qmin, win = 15.0, 16.0
tt = np.arange(np.ceil(t[0]), np.floor(t[-1]) + 1)
ff = np.interp(tt, t, f); qq = np.interp(tt, t, q)
good = (qq >= qmin) & (np.abs(ff - np.median(ff)) < 0.15)
w = good.astype(float) + 1e-6
ff = np.where(good, ff, np.median(ff[good]))
e = pd.read_parquet(__import__("os").environ.get("GHOSTCLOCK_ELEXON_LIVE", "data/gb/elexon_live.parquet"))
s0 = int(pd.Timestamp("2026-11-07T00:00:00Z").timestamp()); s1 = int(pd.Timestamp("2026-11-08T12:22:35Z").timestamp())
e = e[(e.ts_utc >= s0) & (e.ts_utc < s1)].dropna(); e = e[(e.f_hz > 49) & (e.f_hz < 51)]
rt = np.arange(int(e.ts_utc.min()), int(e.ts_utc.max()) + 1)
rf = np.interp(rt, e.ts_utc.to_numpy(), e.f_hz.to_numpy())
rf_s = bm.smooth(rf, win)
sc = bm.ncc_scan(rf_s, ff, w)
cand = rt[:len(sc)] - tt[0]
i1 = int(np.nanargmax(sc)); excl = np.abs(np.arange(len(sc)) - i1) > 120
i2 = int(np.nanargmax(np.where(excl, sc, -np.inf)))
print("best", pd.to_datetime(cand[i1], unit="s", utc=True), sc[i1], "second", pd.to_datetime(cand[i2], unit="s", utc=True), sc[i2], "hours", len(sc)/3600)
nb = 3000; edges = np.linspace(0, len(sc), nb+1).astype(int)
lt, ls = [], []
for a,b in zip(edges[:-1], edges[1:]):
    j = a + int(np.nanargmax(sc[a:b])); lt.append(int(cand[j])); ls.append(round(float(sc[j]),4))
null = [0.8313,0.8465,0.8289,0.8453,0.8348,0.7885,0.8155]
land = {"t": lt, "s": ls, "best_t": int(cand[i1]), "best_ncc": round(float(sc[i1]),4), "second_t": int(cand[i2]), "second_ncc": round(float(sc[i2]),4),
        "null_max": 0.8465, "null": null, "search": ["2026-11-07T00:00:00Z","2026-11-08T12:22:35Z"], "hours": round(len(sc)/3600,2),
        "note": "NCC of the venue trace at every 1 s offset of Elexon live (smoothed 16 s), qmin 15; max per bin of %d bins" % nb}
json.dump(land, open(OUT+r"\landscape.json","w"), separators=(",",":"))
seg = rf_s[i1:i1+len(ff)]
rec = np.where(good, ff, np.nan) - np.mean(ff[good]) + np.mean(seg[good])
step = 2
ov = {"t0": int(cand[i1] + tt[0]), "dt": step, "grid": [round(float(x),4) for x in seg[::step]],
      "rec": [None if np.isnan(x) else round(float(x),4) for x in rec[::step]], "ncc": round(float(sc[i1]),4)}
json.dump(ov, open(OUT+r"\overlay.json","w"), separators=(",",":"))
def load(p): return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
ag = {}
for c in ["case_a","case_e"]:
    ag[c] = load(R + r"\experiments\c5_argon_agent\runs\%s\trace.jsonl" % c)
json.dump(ag, open(OUT+r"\agent.json","w"), separators=(",",":"))
allj = {k: json.load(open(OUT+"\%s.json"%k)) for k in ["trace","landscape","overlay","agent"]}
open(OUT+r"\data.js","w").write("window.GC_DATA=" + json.dumps(allj, separators=(",",":")) + ";")
