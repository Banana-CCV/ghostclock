"""Director spot-check of C2: archiver liveness/coverage, and NESO-vs-Elexon RMSE at lag 0 for Nov 2025 vs Sep 2026."""
import json, numpy as np, pandas as pd
from pathlib import Path

import os
# needs the GB reference parquet files (not committed): set GHOSTCLOCK_GB_DIR (default data/gb)
HERE = Path(__file__).resolve().parent
G = Path(os.environ.get("GHOSTCLOCK_GB_DIR", HERE.parent / "data" / "gb"))
live = pd.read_parquet(G / "elexon_live.parquet")
ts = live["ts_utc"].astype("int64")
print(f"elexon_live rows={len(live)} first={pd.to_datetime(ts.min(), unit='s')} last={pd.to_datetime(ts.max(), unit='s')} "
      f"lag_now_min={(pd.Timestamp.utcnow().timestamp() - ts.max())/60:.1f} nan={live['f_hz'].isna().sum()}")

def rmse(month, day_start):
    n = pd.read_parquet(G / f"neso_{month}.parquet")
    e = pd.read_parquet(G / f"elexon_{month}.parquet")
    t0 = int(pd.Timestamp(day_start, tz="UTC").timestamp()); t1 = t0 + 6 * 3600
    n = n[(n.ts_utc >= t0) & (n.ts_utc < t1)].set_index("ts_utc")["f_hz"]
    e = e[(e.ts_utc >= t0) & (e.ts_utc < t1)].set_index("ts_utc")["f_hz"]
    out = {}
    for lag in (-3600, 0, 3600):
        j = pd.concat([e, n.rename(lambda x: x - lag)], axis=1, join="inner").dropna()
        if len(j):
            out[lag] = round(float(np.sqrt(((j.iloc[:, 0] - j.iloc[:, 1]) ** 2).mean()) * 1000), 2)
    return out

print("Nov 2025 (NESO vs Elexon RMSE mHz by NESO lag s):", rmse("2025_11", "2025-11-12"))
print("Sep 2026 (NESO vs Elexon RMSE mHz by NESO lag s):", rmse("2026_09", "2026-09-10"))
r = json.loads((HERE.parent / "experiments" / "c2_gb_reference_and_feasibility" / "RESULTS.json").read_text(encoding="utf-8"))
print("RESULTS.json keys:", list(r)[:15])
