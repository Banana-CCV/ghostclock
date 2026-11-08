"""
Verify:
1. Exact match between fnew-2025-10.csv first hour (labelled 2025-10-01 00:00..01:00)
   and Elexon UTC 2025-09-30T23:00:00Z..2025-10-01T00:00:00Z.
2. What happened during the 3-hour window 2026-09-27 09:00..12:00 UTC between NESO and Elexon.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
NESO_DIR = REPO_ROOT / "datasets" / "raw" / "neso"
ELEXON_DIR = REPO_ROOT / "datasets" / "raw" / "elexon"
WORK_DIR = Path(__file__).resolve().parent


def main():
    df_neso_oct = pd.read_parquet(NESO_DIR / "neso_2025-10.parquet")
    # Fetch Elexon 2025-09-30T22:00:00Z to 2025-10-01T02:00:00Z
    r = requests.get(
        "https://data.elexon.co.uk/bmrs/api/v1/system/frequency/stream",
        params={"from": "2025-09-30T22:00:00Z", "to": "2025-10-01T02:00:00Z"},
        timeout=30,
    )
    df_el = pd.DataFrame(r.json())
    df_el["ts_utc"] = pd.to_datetime(df_el["measurementTime"], utc=True).dt.as_unit("s").astype("int64")
    df_el["f_hz"] = pd.to_numeric(df_el["frequency"], errors="coerce")
    df_el = df_el.drop_duplicates("ts_utc").sort_values("ts_utc")

    # Compare NESO labelled 2025-10-01 00:00:00..01:00:00 (ts_utc = 1759276800..1759280400)
    # against Elexon 2025-09-30T23:00:00Z..2025-10-01T00:00:00Z (ts_utc = 1759273200..1759276800)
    neso_first_hr = df_neso_oct.iloc[:3601].copy()
    neso_first_hr["true_ts_utc_if_bst"] = neso_first_hr["ts_utc"] - 3600
    m = pd.merge(
        df_el,
        neso_first_hr,
        left_on="ts_utc",
        right_on="true_ts_utc_if_bst",
        suffixes=("_elexon", "_neso"),
    )
    diff_mhz = (m["f_hz_elexon"] - m["f_hz_neso"]) * 1000.0

    # Now inspect 2026-09-27 08:00Z to 13:00Z in detail
    df_neso_sep = pd.read_parquet(NESO_DIR / "neso_2026-09.parquet")
    df_el_sep = pd.read_parquet(ELEXON_DIR / "elexon_overlap_2026_09.parquet")
    t0 = int(datetime(2026, 9, 27, 8, 0, 0, tzinfo=timezone.utc).timestamp())
    t1 = int(datetime(2026, 9, 27, 13, 0, 0, tzinfo=timezone.utc).timestamp())
    m_sep = pd.merge(
        df_el_sep[(df_el_sep["ts_utc"] >= t0) & (df_el_sep["ts_utc"] <= t1)],
        df_neso_sep[(df_neso_sep["ts_utc"] >= t0) & (df_neso_sep["ts_utc"] <= t1)],
        on="ts_utc",
        suffixes=("_elexon", "_neso"),
    )
    m_sep["diff_mhz"] = (m_sep["f_hz_elexon"] - m_sep["f_hz_neso"]) * 1000.0
    m_sep["abs_diff_mhz"] = m_sep["diff_mhz"].abs()
    bad_sep = m_sep[m_sep["abs_diff_mhz"] > 20.0]

    # Check when on 2026-09-27 the divergence starts and ends
    out = {
        "oct1_2025_first_hour_as_bst_vs_elexon_sep30_23z": {
            "n_matched_15s_points": int(len(m)),
            "rmse_mhz": round(float(np.sqrt(np.mean(diff_mhz ** 2))), 4),
            "exact0_frac": round(float(np.mean(np.abs(diff_mhz) < 1e-4)), 4),
            "pearson_r": round(float(np.corrcoef(m["f_hz_elexon"], m["f_hz_neso"])[0, 1]), 6),
            "first_5_pairs": m[["measurementTime", "f_hz_elexon", "f_hz_neso"]].head(5).to_dict(orient="records"),
        },
        "sep27_2026_divergence_window": {
            "n_points_gt_20mhz": int(len(bad_sep)),
            "first_divergent_iso": datetime.fromtimestamp(int(bad_sep["ts_utc"].iloc[0]), tz=timezone.utc).isoformat() if not bad_sep.empty else None,
            "last_divergent_iso": datetime.fromtimestamp(int(bad_sep["ts_utc"].iloc[-1]), tz=timezone.utc).isoformat() if not bad_sep.empty else None,
        },
    }

    # Check if Elexon or NESO was shifted by some lag on 2026-09-27 09:30..10:30Z over +/- 86400s
    t_mid0 = int(datetime(2026, 9, 27, 9, 30, 0, tzinfo=timezone.utc).timestamp())
    t_mid1 = int(datetime(2026, 9, 27, 10, 30, 0, tzinfo=timezone.utc).timestamp())
    el_mid = df_el_sep[(df_el_sep["ts_utc"] >= t_mid0) & (df_el_sep["ts_utc"] <= t_mid1)]
    sep_ts = df_neso_sep["ts_utc"].to_numpy(dtype=np.int64)
    sep_f = df_neso_sep["f_hz"].to_numpy(dtype=np.float64)
    ts_min = int(sep_ts[0])
    el_ts_arr = el_mid["ts_utc"].to_numpy(dtype=np.int64)
    el_f_arr = el_mid["f_hz"].to_numpy(dtype=np.float64)

    best_tau = 0
    best_r = -1.0
    best_rmse = 9999.0
    # Vectorized search over tau in [-43200, +43200] step 15s, plus fine step 1s around top hit
    for tau in range(-43200, 43201, 5):
        idx = el_ts_arr + tau - ts_min
        if idx[0] < 0 or idx[-1] >= len(sep_f):
            continue
        nf = sep_f[idx]
        r_val = float(np.corrcoef(el_f_arr, nf)[0, 1])
        if r_val > best_r:
            best_r = r_val
            best_tau = tau
            best_rmse = float(np.sqrt(np.mean(((el_f_arr - nf) * 1000.0) ** 2)))
    # Refine +/- 10s around best_tau
    for tau in range(best_tau - 10, best_tau + 11, 1):
        idx = el_ts_arr + tau - ts_min
        if idx[0] < 0 or idx[-1] >= len(sep_f):
            continue
        nf = sep_f[idx]
        rmse_val = float(np.sqrt(np.mean(((el_f_arr - nf) * 1000.0) ** 2)))
        r_val = float(np.corrcoef(el_f_arr, nf)[0, 1])
        if rmse_val < best_rmse:
            best_rmse = rmse_val
            best_tau = tau
            best_r = r_val

    out["sep27_2026_best_lag_in_plusminus_12h"] = {
        "best_tau_s": best_tau,
        "best_rmse_mhz": round(best_rmse, 3),
        "best_pearson_r": round(best_r, 5),
    }

    out_path = WORK_DIR / "verify_oct2025_and_sep27.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
