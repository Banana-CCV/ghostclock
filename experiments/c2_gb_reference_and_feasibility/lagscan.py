"""Per-day best lag of Elexon vs NESO 1 s (lag k: Elexon(t) ~ NESO(t+k)). Usage: python -I work/C2/lagscan.py 2025_10 2026_08 2026_09"""
import sys, json
import numpy as np, pandas as pd
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import crosscheck  # noqa: E402  (provides elexon_month fetch+cache)
GB = Path(__file__).resolve().parents[2] / "datasets" / "raw" / "gb"
CAND = sorted(set(list(range(-90, 91)) + list(range(3600 - 90, 3600 + 91)) + list(range(-3600 - 90, -3600 + 91))))
out = {}
for m in sys.argv[1:]:
    n = pd.read_parquet(GB / f"neso_{m}.parquet")
    e = crosscheck.elexon_month(int(m[:4]), int(m[5:]))
    side = json.loads((GB / f"neso_{m}.json").read_text())
    t0 = int(n.ts_utc.iloc[0]); f1 = np.full(int(n.ts_utc.iloc[-1]) - t0 + 1, np.nan); f1[n.ts_utc.values - t0] = n.f_hz.values
    for a, b in side.get("bad_intervals", []):
        f1[a - t0:b - t0 + 1] = np.nan
    days = {}
    for d0 in range(t0, t0 + len(f1), 86400):
        s = e[(e.ts_utc >= d0) & (e.ts_utc < d0 + 86400)]
        idx = s.ts_utc.values - t0; fe = s.f_hz.values
        res = []
        for k in CAND:
            j = idx + k; ok = (j >= 0) & (j < len(f1))
            dd = fe[ok] - f1[j[ok]]; dd = dd[np.isfinite(dd)]
            if len(dd) > 500: res.append((float(np.sqrt(np.mean(dd ** 2)) * 1000), k, len(dd)))
        res.sort()
        day = pd.Timestamp(d0, unit="s").strftime("%Y-%m-%d")
        days[day] = {"best_lag_s": res[0][1], "rmse_mhz": round(res[0][0], 3), "n": res[0][2]} if res else None
        if res:
            r0 = [x for x in res if x[1] == 0]
            days[day]["rmse_lag0_mhz"] = round(r0[0][0], 3) if r0 else None
    out[m] = days
    print(m, {d: (v["best_lag_s"], v["rmse_mhz"]) if v else None for d, v in days.items()}, flush=True)
(Path(__file__).parent / "lagscan.json").write_text(json.dumps(out, indent=1))
