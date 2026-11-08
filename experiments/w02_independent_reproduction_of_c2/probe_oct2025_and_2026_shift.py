"""
Investigate two critical empirical findings discovered during cross-check:
1. Why October 2025 (fnew-2025-10.csv) matched Elexon with RMSE=0.63 mHz (90% exact 0.000 Hz match)
   at lag tau = +3600 s (+1 hour, i.e. BST = UTC+1) even on 2025-10-26 05:00Z!
   When in October 2025 (or between Oct 31 and Nov 1, 2025) does NESO shift from UTC+1 to UTC+0?
2. Why March 2026 and September 2026 have RMSE ~5-6 mHz at tau=0 (and 96 mHz on 2026-09-27 09:00-11:00Z):
   Is there a lag or clock drift in NESO on 2026-09-27, or did NESO/Elexon change processing between 2025 and 2026?
"""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

REPO_ROOT = Path(__file__).resolve().parents[2]
NESO_DIR = REPO_ROOT / "datasets" / "raw" / "neso"
ELEXON_DIR = REPO_ROOT / "datasets" / "raw" / "elexon"
WORK_DIR = Path(__file__).resolve().parent


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "GhostClock-W02-Research/1.0"})
    s.mount("https://", HTTPAdapter(max_retries=Retry(total=4, backoff_factor=0.5)))
    return s


def fetch_elexon_window(sess: requests.Session, t0_iso: str, t1_iso: str) -> pd.DataFrame:
    url = "https://data.elexon.co.uk/bmrs/api/v1/system/frequency/stream"
    r = sess.get(url, params={"from": t0_iso, "to": t1_iso}, timeout=30)
    r.raise_for_status()
    df = pd.DataFrame(r.json())
    ts_sec = pd.to_datetime(df["measurementTime"], utc=True).dt.as_unit("s").astype("int64").to_numpy(dtype=np.int64)
    f_vals = pd.to_numeric(df["frequency"], errors="coerce").to_numpy(dtype=np.float64)
    return pd.DataFrame({"ts_utc": ts_sec, "f_hz": f_vals}).drop_duplicates("ts_utc").sort_values("ts_utc")


def find_best_lag(neso_ts: np.ndarray, neso_f: np.ndarray, el_ts: np.ndarray, el_f: np.ndarray, search_lags: list[int]) -> dict:
    ts_min = int(neso_ts[0])
    best = None
    for tau in search_lags:
        idx = el_ts + tau - ts_min
        ok = (idx >= 0) & (idx < len(neso_f))
        if np.sum(ok) < 20:
            continue
        diff = (el_f[ok] - neso_f[idx[ok]]) * 1000.0
        rmse = float(np.sqrt(np.mean(diff ** 2)))
        exact0 = float(np.mean(np.abs(diff) < 1e-4))
        r = float(np.corrcoef(el_f[ok], neso_f[idx[ok]])[0, 1]) if np.std(el_f[ok]) > 0 else 0.0
        cand = {"tau_s": int(tau), "rmse_mhz": round(rmse, 3), "exact0_frac": round(exact0, 4), "pearson_r": round(r, 5), "n": int(np.sum(ok))}
        if best is None or cand["rmse_mhz"] < best["rmse_mhz"]:
            best = cand
    return best


def main():
    sess = make_session()
    out = {}

    # 1. Check October 2025 across multiple dates: Oct 1, Oct 15, Oct 25, Oct 26, Oct 27, Oct 31
    df_neso_oct = pd.read_parquet(NESO_DIR / "neso_2025-10.parquet")
    neso_oct_ts = df_neso_oct["ts_utc"].to_numpy(dtype=np.int64)
    neso_oct_f = df_neso_oct["f_hz"].to_numpy(dtype=np.float64)

    oct_probes = []
    for day in [1, 15, 25, 26, 27, 28, 30, 31]:
        t0 = f"2025-10-{day:02d}T10:00:00Z"
        t1 = f"2025-10-{day:02d}T14:00:00Z"
        el = fetch_elexon_window(sess, t0, t1)
        lags_to_try = list(range(-60, 61)) + list(range(3540, 3661)) + list(range(-3660, -3539))
        best = find_best_lag(neso_oct_ts, neso_oct_f, el["ts_utc"].to_numpy(), el["f_hz"].to_numpy(), lags_to_try)
        at_0 = find_best_lag(neso_oct_ts, neso_oct_f, el["ts_utc"].to_numpy(), el["f_hz"].to_numpy(), [0])
        at_3600 = find_best_lag(neso_oct_ts, neso_oct_f, el["ts_utc"].to_numpy(), el["f_hz"].to_numpy(), [3600])
        oct_probes.append({"window": f"{t0}..{t1}", "best": best, "at_tau_0": at_0, "at_tau_3600": at_3600})
    out["oct_2025_daily_lag_checks"] = oct_probes

    #Also check the boundary between 2025-10-31 22:00Z and 2025-11-01 02:00Z!
    df_neso_nov = pd.read_parquet(NESO_DIR / "neso_2025-11.parquet")
    df_oct_nov = pd.concat([df_neso_oct.iloc[-7200:], df_neso_nov.iloc[:7200]], ignore_index=True)
    el_boundary = fetch_elexon_window(sess, "2025-10-31T21:00:00Z", "2025-11-01T02:00:00Z")
    boundary_hours = []
    el_boundary["hour"] = pd.to_datetime(el_boundary["ts_utc"], unit="s", utc=True).dt.strftime("%Y-%m-%dT%H:00Z")
    for h_iso, grp in el_boundary.groupby("hour"):
        b_0 = find_best_lag(df_oct_nov["ts_utc"].to_numpy(), df_oct_nov["f_hz"].to_numpy(), grp["ts_utc"].to_numpy(), grp["f_hz"].to_numpy(), [0])
        b_3600 = find_best_lag(df_oct_nov["ts_utc"].to_numpy(), df_oct_nov["f_hz"].to_numpy(), grp["ts_utc"].to_numpy(), grp["f_hz"].to_numpy(), [3600])
        boundary_hours.append({"hour_utc": h_iso, "at_tau_0": b_0, "at_tau_3600": b_3600})
    out["oct31_to_nov1_2025_boundary"] = boundary_hours

    # 2. Check what happened on 2026-09-27 09:00..11:00Z (where RMSE at tau=0 was 96 mHz!)
    df_neso_sep = pd.read_parquet(NESO_DIR / "neso_2026-09.parquet")
    df_el_sep = pd.read_parquet(ELEXON_DIR / "elexon_overlap_2026_09.parquet")
    sep_ts = df_neso_sep["ts_utc"].to_numpy(dtype=np.int64)
    sep_f = df_neso_sep["f_hz"].to_numpy(dtype=np.float64)

    # Search wide lags [-7200..+7200] in steps of 1s for 2026-09-27T10:00Z
    t_anom_0 = int(datetime(2026, 9, 27, 10, 0, 0, tzinfo=timezone.utc).timestamp())
    t_anom_1 = int(datetime(2026, 9, 27, 11, 0, 0, tzinfo=timezone.utc).timestamp())
    el_anom = df_el_sep[(df_el_sep["ts_utc"] >= t_anom_0) & (df_el_sep["ts_utc"] < t_anom_1)]
    wide_best = find_best_lag(sep_ts, sep_f, el_anom["ts_utc"].to_numpy(), el_anom["f_hz"].to_numpy(), list(range(-7200, 7201, 1)))
    out["sep_27_2026_10z_wide_lag_search"] = wide_best

    # Also check what NESO and Elexon values look like during 2026-09-27 08:30Z..12:00Z
    n_anom_slice = df_neso_sep[(df_neso_sep["ts_utc"] >= t_anom_0 - 5400) & (df_neso_sep["ts_utc"] <= t_anom_1 + 3600)]
    e_anom_slice = df_el_sep[(df_el_sep["ts_utc"] >= t_anom_0 - 5400) & (df_el_sep["ts_utc"] <= t_anom_1 + 3600)]
    out["sep_27_2026_neso_stats"] = {
        "min": float(n_anom_slice["f_hz"].min()),
        "max": float(n_anom_slice["f_hz"].max()),
        "mean": float(n_anom_slice["f_hz"].mean()),
        "std": float(n_anom_slice["f_hz"].std()),
        "sample_10z": n_anom_slice.iloc[5400:5410][["ts_utc", "f_hz"]].to_dict(orient="records"),
    }
    out["sep_27_2026_elexon_stats"] = {
        "min": float(e_anom_slice["f_hz"].min()),
        "max": float(e_anom_slice["f_hz"].max()),
        "mean": float(e_anom_slice["f_hz"].mean()),
        "std": float(e_anom_slice["f_hz"].std()),
        "sample_10z": e_anom_slice[(e_anom_slice["ts_utc"] >= t_anom_0) & (e_anom_slice["ts_utc"] <= t_anom_0 + 120)][["ts_utc", "f_hz"]].to_dict(orient="records"),
    }

    # 3. Also check July 2026 and August 2026 vs Elexon! Are July/Aug 2026 at tau=0 or tau=+3600?
    for ym, d_str in [("2026-07", "2026-07-15"), ("2026-08", "2026-08-15"), ("2026-03", "2026-03-15"), ("2026-03", "2026-03-30")]:
        df_n = pd.read_parquet(NESO_DIR / f"neso_{ym}.parquet")
        el_w = fetch_elexon_window(sess, f"{d_str}T10:00:00Z", f"{d_str}T14:00:00Z")
        b_all = find_best_lag(
            df_n["ts_utc"].to_numpy(),
            df_n["f_hz"].to_numpy(),
            el_w["ts_utc"].to_numpy(),
            el_w["f_hz"].to_numpy(),
            list(range(-60, 61)) + [-3600, 3600],
        )
        b_0 = find_best_lag(df_n["ts_utc"].to_numpy(), df_n["f_hz"].to_numpy(), el_w["ts_utc"].to_numpy(), el_w["f_hz"].to_numpy(), [0])
        b_3600 = find_best_lag(df_n["ts_utc"].to_numpy(), df_n["f_hz"].to_numpy(), el_w["ts_utc"].to_numpy(), el_w["f_hz"].to_numpy(), [3600])
        out[f"check_{d_str}"] = {"best": b_all, "at_tau_0": b_0, "at_tau_3600": b_3600}

    out_path = WORK_DIR / "oct2025_and_2026_shift.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
