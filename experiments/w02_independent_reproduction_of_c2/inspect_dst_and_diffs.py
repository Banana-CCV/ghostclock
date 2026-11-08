"""
Deep-dive inspection of hour-by-hour alignment between NESO 1s and Elexon 15s
across:
1. 2025-10-26 (BST->GMT transition)
2. 2026-03-29 (GMT->BST transition)
3. 2026-09-24..30 (September 2026)
4. 2025-11-01..07 (November 2025)
"""
import json
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
NESO_DIR = REPO_ROOT / "datasets" / "raw" / "neso"
ELEXON_DIR = REPO_ROOT / "datasets" / "raw" / "elexon"
WORK_DIR = Path(__file__).resolve().parent


def check_hourly_lags(df_neso: pd.DataFrame, df_el: pd.DataFrame, label: str) -> dict:
    neso_ts = df_neso["ts_utc"].to_numpy(dtype=np.int64)
    neso_f = df_neso["f_hz"].to_numpy(dtype=np.float64)
    ts_min = int(neso_ts[0])
    ts_max = int(neso_ts[-1])

    el_valid = df_el[(df_el["f_hz"] >= 47.0) & (df_el["f_hz"] <= 52.0)].copy()
    el_valid["hour_iso"] = pd.to_datetime(el_valid["ts_utc"], unit="s", utc=True).dt.strftime("%Y-%m-%dT%H:00Z")

    hourly_rows = []
    for hour_iso, grp in el_valid.groupby("hour_iso"):
        ets = grp["ts_utc"].to_numpy(dtype=np.int64)
        ef = grp["f_hz"].to_numpy(dtype=np.float64)
        row = {"hour_iso": hour_iso, "n": len(ets)}
        for tau in [-3600, -60, -15, -2, -1, 0, 1, 2, 15, 60, 3600]:
            t_idx = ets + tau - ts_min
            ok = (t_idx >= 0) & (t_idx < len(neso_f))
            if np.sum(ok) > 10:
                diff = (ef[ok] - neso_f[t_idx[ok]]) * 1000.0
                rmse = float(np.sqrt(np.mean(diff ** 2)))
                r = float(np.corrcoef(ef[ok], neso_f[t_idx[ok]])[0, 1]) if np.std(ef[ok]) > 0 else 0.0
                exact0 = float(np.mean(np.abs(diff) < 1e-4))
                row[f"rmse_tau_{tau}"] = round(rmse, 2)
                row[f"r_tau_{tau}"] = round(r, 4)
                if tau in (-3600, 0, 3600):
                    row[f"exact0_tau_{tau}"] = round(exact0, 3)
        hourly_rows.append(row)
    return {"label": label, "hours": hourly_rows}


def main():
    df_neso_oct = pd.read_parquet(NESO_DIR / "neso_2025-10.parquet")
    df_el_oct = pd.read_parquet(ELEXON_DIR / "elexon_dst_2025_10_26.parquet")
    res_oct = check_hourly_lags(df_neso_oct, df_el_oct, "2025-10-26_dst")

    df_neso_mar = pd.read_parquet(NESO_DIR / "neso_2026-03.parquet")
    df_el_mar = pd.read_parquet(ELEXON_DIR / "elexon_dst_2026_03_29.parquet")
    res_mar = check_hourly_lags(df_neso_mar, df_el_mar, "2026-03-29_dst")

    df_neso_sep = pd.read_parquet(NESO_DIR / "neso_2026-09.parquet")
    df_el_sep = pd.read_parquet(ELEXON_DIR / "elexon_overlap_2026_09.parquet")
    # Sample every 6th hour in Sep 2026 plus any hour where rmse_tau_0 > 15 mHz
    res_sep_all = check_hourly_lags(df_neso_sep, df_el_sep, "2026-09_overlap")
    sep_high_rmse = [h for h in res_sep_all["hours"] if h.get("rmse_tau_0", 0) > 15.0]

    out = {
        "oct_2025_dst": res_oct["hours"],
        "mar_2026_dst": res_mar["hours"],
        "sep_2026_high_rmse_hours_count": len(sep_high_rmse),
        "sep_2026_high_rmse_hours": sep_high_rmse[:30],
        "sep_2026_sample_normal_hours": res_sep_all["hours"][:10],
    }
    out_path = WORK_DIR / "dst_and_hourly_inspection.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Saved {out_path}")


if __name__ == "__main__":
    main()
