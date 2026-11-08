"""
Independent Reproduction of C2 Findings + Dec 2025 / Jan 2026 / Feb 2026 Transition Audit (W02).
Executes the Director's UPDATE (10:40) priority:
1. Verify (1) the Oct 2025 +3600 s offset across all 31 days of Oct 2025 (plus our 21-month finding that
   2025-04..2025-10 were all exported in BST = UTC+1).
2. Verify (2) the 2026 Elexon scatter and pinpoint WHEN it started by downloading and auditing full months
   Dec 2025 (fnew-2025-12.csv), Jan 2026 (fnew-2026-1.csv), and Feb 2026 (fnew-2026-2.csv) day-by-day against Elexon.
3. Verify flat-filled NESO outages (2026-09-15 07:30:03..10:35:59 UTC at 49.895 Hz for 11,158 s;
   2026-03-31 13:39:28 at 50.046 Hz for 479 s) and inspect what Elexon BMRS recorded during those exact windows.
4. Independently reproduce (3) C2's feasibility table: P(top-1 within +-15 s) for D in {2, 5, 10, 20} min,
   sigma = 2 mHz, 24 h search window, n = 400 (>= 300) trials per cell across:
   - ref_1s (NESO 1 s)
   - ref_15s_pt (NESO 15 s point-sampled, 15-phase NCC)
   - ref_15s_avg (NESO 15 s block-averaged, 15-phase NCC)
   - ref_elexon_real_pt (Real Elexon 15 s point-sampled, 15-phase NCC)
   - ref_elexon_real_avg (Real Elexon 15 s vs 15 s block-averaged query, 15-phase NCC)
   - ref_elexon_real_lin1s (Real Elexon 15 s linearly interpolated to 1 s vs 1 s query)
5. Save deck-worthy PNG plots into work/W02/plots/ (and copy existing figures there).
"""
from __future__ import annotations

import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from scipy.signal import fftconvolve
from urllib3.util.retry import Retry

REPO_ROOT = Path(__file__).resolve().parents[2]
NESO_DIR = REPO_ROOT / "datasets" / "raw" / "neso"
ELEXON_DIR = REPO_ROOT / "datasets" / "raw" / "elexon"
GB_C2_DIR = REPO_ROOT / "datasets" / "raw" / "gb"
WORK_DIR = Path(__file__).resolve().parent
FIG_DIR = WORK_DIR / "figures"
PLOTS_DIR = WORK_DIR / "plots"
PLOTS_DIR.mkdir(parents=True, exist_ok=True)


def make_session() -> requests.Session:
    s = requests.Session()
    retries = Retry(total=4, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
    s.mount("https://", HTTPAdapter(max_retries=retries))
    return s


def fetch_elexon_month(session: requests.Session, start_iso: str, end_iso: str) -> pd.DataFrame:
    r = session.get(
        "https://data.elexon.co.uk/bmrs/api/v1/system/frequency/stream",
        params={"from": start_iso, "to": end_iso},
        timeout=60,
    )
    r.raise_for_status()
    df = pd.DataFrame(r.json())
    df["ts_utc"] = pd.to_datetime(df["measurementTime"], utc=True).dt.as_unit("s").astype("int64")
    df["f_hz"] = pd.to_numeric(df["frequency"], errors="coerce")
    n_zero = int((df["f_hz"] == 0.0).sum())
    n_out = int(((df["f_hz"] < 47.0) | (df["f_hz"] > 52.0)).sum())
    df.loc[(df["f_hz"] < 47.0) | (df["f_hz"] > 52.0), "f_hz"] = np.nan
    df = df.drop_duplicates("ts_utc").sort_values("ts_utc").reset_index(drop=True)
    df.attrs["n_zero_placeholders"] = n_zero
    df.attrs["n_out_of_range"] = n_out
    return df


def download_and_audit_dec_jan_feb(session: requests.Session) -> dict:
    """
    Download fnew-2025-12.csv, fnew-2026-1.csv, and fnew-2026-2.csv into datasets/raw/neso/
    and run full-month and daily cross-checks against Elexon BMRS to pinpoint when the 2026 scatter started.
    """
    months_meta = [
        {
            "ym": "2025-12",
            "url": "https://api.neso.energy/dataset/cb1cc925-ecd8-4406-b021-3a3f368196e1/resource/ac8f4d97-32f9-466c-b3c1-f5ce5c2f6e32/download/fnew-2025-12.csv",
            "start_iso": "2025-12-01T00:00:00Z",
            "end_iso": "2025-12-31T23:59:59Z",
        },
        {
            "ym": "2026-01",
            "url": "https://api.neso.energy/dataset/cb1cc925-ecd8-4406-b021-3a3f368196e1/resource/b3de0b99-8291-4582-b2f2-1d5a51b5a044/download/fnew-2026-1.csv",
            "start_iso": "2026-01-01T00:00:00Z",
            "end_iso": "2026-01-31T23:59:59Z",
        },
        {
            "ym": "2026-02",
            "url": "https://api.neso.energy/dataset/cb1cc925-ecd8-4406-b021-3a3f368196e1/resource/f8e0e6ea-c493-4e0e-887b-977522c4a0d5/download/fnew-2026-2.csv",
            "start_iso": "2026-02-01T00:00:00Z",
            "end_iso": "2026-02-28T23:59:59Z",
        },
    ]
    # Look up exact URLs from probe_results.json
    pkg = json.loads((WORK_DIR / "probe_results.json").read_text(encoding="utf-8"))
    url_map = {}
    for r in pkg["neso"]["resources"]:
        u = r.get("url", "")
        if "2025-12" in u:
            url_map["2025-12"] = u
        elif "2026-1.csv" in u:
            url_map["2026-01"] = u
        elif "2026-2.csv" in u:
            url_map["2026-02"] = u

    out = {"months": {}, "daily_series": []}
    for m in months_meta:
        ym = m["ym"]
        url = url_map.get(ym, m["url"])
        csv_path = NESO_DIR / f"neso_{ym}.csv"
        if not (csv_path.exists() and csv_path.stat().st_size > 10_000_000):
            print(f"  [downloading] {ym} from {url} ...")
            with session.get(url, stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(csv_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
        df_n = pd.read_csv(csv_path)
        s_dtm = df_n.iloc[:, 0].astype(str).str.strip()
        date_only = s_dtm.str.len() == 10
        if date_only.any():
            s_dtm = s_dtm.where(~date_only, s_dtm + " 00:00:00")
        ts_sec = pd.to_datetime(s_dtm, format="%Y-%m-%d %H:%M:%S", utc=True).dt.as_unit("s").astype("int64").to_numpy()
        f_val = pd.to_numeric(df_n.iloc[:, 1], errors="coerce").to_numpy(dtype=np.float64)

        # Detect max constant flat run in NESO
        same_as_prev = np.r_[False, np.abs(np.diff(f_val)) < 1e-9]
        # Find run lengths
        changes = np.diff(np.r_[0, same_as_prev.view(np.int8), 0])
        starts = np.where(changes == 1)[0]
        ends = np.where(changes == -1)[0]
        max_flat_s = int(np.max(ends - starts) + 1) if len(starts) else 1

        df_el = fetch_elexon_month(session, m["start_iso"], m["end_iso"])
        el_ts = df_el["ts_utc"].to_numpy(dtype=np.int64)
        el_f = df_el["f_hz"].to_numpy(dtype=np.float64)
        valid = ~np.isnan(el_f)
        el_ts_v = el_ts[valid]
        el_f_v = el_f[valid]

        ts0 = int(ts_sec[0])
        n_neso = len(f_val)

        # Month-level metrics at lag=0
        idx0 = el_ts_v - ts0
        in_b = (idx0 >= 0) & (idx0 < n_neso)
        ref0 = f_val[idx0[in_b]]
        est0 = el_f_v[in_b]
        diff0 = (est0 - ref0) * 1000.0
        rmse_0 = float(np.sqrt(np.mean(diff0 ** 2)))
        mae_0 = float(np.mean(np.abs(diff0)))
        med_0 = float(np.median(np.abs(diff0)))
        p99_0 = float(np.percentile(np.abs(diff0), 99))
        exact_0 = float(np.mean(np.abs(diff0) <= 0.5))
        within_1 = float(np.mean(np.abs(diff0) <= 1.0001))
        corr_0 = float(np.corrcoef(ref0, est0)[0, 1])

        # 15s step std comparison (C2's implied extra white noise metric)
        std_15s_el = float(np.std(np.diff(est0) * 1000.0))
        std_15s_neso = float(np.std(np.diff(ref0) * 1000.0))
        var_diff = max(0.0, (std_15s_el ** 2 - std_15s_neso ** 2) / 2.0)
        implied_extra_noise = float(np.sqrt(var_diff))

        # Per-day lag scan over [-120, +120] s + +/-3600s
        n_days = n_neso // 86400
        lag_counts = {}
        daily_rmses_at_0 = []
        daily_rmses_at_best = []
        for d in range(n_days):
            d_start = ts0 + d * 86400
            d_end = d_start + 86400
            d_iso = datetime.fromtimestamp(d_start, tz=timezone.utc).strftime("%Y-%m-%d")
            m_day = (el_ts_v >= d_start + 120) & (el_ts_v < d_end - 120)
            ets_d = el_ts_v[m_day]
            ef_d = el_f_v[m_day]
            if len(ets_d) < 100:
                continue
            best_tau = 0
            best_r_day = 1e9
            rmse_day_0 = 0.0
            for tau in list(range(-30, 31)) + [-3600, 3600]:
                idx_d = ets_d + tau - ts0
                ok_d = (idx_d >= 0) & (idx_d < n_neso)
                dd = (ef_d[ok_d] - f_val[idx_d[ok_d]]) * 1000.0
                rm = float(np.sqrt(np.mean(dd * dd)))
                if tau == 0:
                    rmse_day_0 = rm
                if rm < best_r_day:
                    best_r_day = rm
                    best_tau = tau
            lag_counts[str(best_tau)] = lag_counts.get(str(best_tau), 0) + 1
            daily_rmses_at_0.append(rmse_day_0)
            daily_rmses_at_best.append(best_r_day)

            # Also compute exact0 fraction at lag 0 and at best_tau for this day
            dd0 = (ef_d - f_val[ets_d - ts0]) * 1000.0
            dd_best = (ef_d - f_val[ets_d + best_tau - ts0]) * 1000.0
            out["daily_series"].append({
                "date": d_iso,
                "ym": ym,
                "n_15s": int(len(ets_d)),
                "best_lag_s": int(best_tau),
                "rmse_at_0s_mhz": round(rmse_day_0, 3),
                "rmse_at_best_lag_mhz": round(best_r_day, 3),
                "frac_exact_at_0s": round(float(np.mean(np.abs(dd0) <= 0.5)), 4),
                "frac_exact_at_best_lag": round(float(np.mean(np.abs(dd_best) <= 0.5)), 4),
            })

        out["months"][ym] = {
            "neso_rows": int(n_neso),
            "neso_max_flat_run_s": max_flat_s,
            "elexon_valid_pairs": int(np.sum(in_b)),
            "elexon_0hz_placeholders": df_el.attrs["n_zero_placeholders"],
            "rmse_at_0s_mhz": round(rmse_0, 3),
            "mae_at_0s_mhz": round(mae_0, 3),
            "median_abs_mhz": round(med_0, 3),
            "p99_abs_mhz": round(p99_0, 3),
            "frac_exact_le_0_5mhz": round(exact_0, 4),
            "frac_within_1mhz": round(within_1, 4),
            "pearson_r": round(corr_0, 5),
            "std_15s_diff_elexon_mhz": round(std_15s_el, 3),
            "std_15s_diff_neso_pt_mhz": round(std_15s_neso, 3),
            "implied_extra_white_noise_elexon_mhz": round(implied_extra_noise, 3),
            "best_lag_counts_days": lag_counts,
            "median_daily_rmse_at_0s_mhz": round(float(np.median(daily_rmses_at_0)), 3),
            "median_daily_rmse_at_best_lag_mhz": round(float(np.median(daily_rmses_at_best)), 3),
        }
        print(f"  [Audited {ym}] RMSE@0s={rmse_0:.3f} mHz, exact={exact_0:.4f}, lag_days={lag_counts}")

    return out


def verify_flat_filled_outages() -> dict:
    """
    Independently verify C2's claim of flat-filled NESO outages in 2026-09 and 2026-03,
    AND check whether Elexon BMRS continued recording dynamic grid frequency during those NESO flat-lines!
    """
    out = {}
    for ym, pq_name in [("2026-09", "neso_2026-09.parquet"), ("2026-03", "neso_2026-03.parquet")]:
        df = pd.read_parquet(NESO_DIR / pq_name)
        ts = df["ts_utc"].to_numpy(dtype=np.int64)
        f = df["f_hz"].to_numpy(dtype=np.float64)
        same = np.r_[False, np.abs(np.diff(f)) < 1e-9]
        changes = np.diff(np.r_[0, same.view(np.int8), 0])
        starts = np.where(changes == 1)[0] - 1
        ends = np.where(changes == -1)[0] - 1
        lengths = ends - starts + 1
        long_idx = np.where(lengths >= 60)[0]
        runs = []
        for k in long_idx:
            s_i = int(starts[k])
            e_i = int(ends[k])
            runs.append({
                "start_ts_utc": int(ts[s_i]),
                "end_ts_utc": int(ts[e_i]),
                "start_iso": datetime.fromtimestamp(int(ts[s_i]), tz=timezone.utc).isoformat(),
                "end_iso": datetime.fromtimestamp(int(ts[e_i]), tz=timezone.utc).isoformat(),
                "duration_s": int(lengths[k]),
                "constant_f_hz": float(f[s_i]),
            })
        out[ym] = runs

    # Check what Elexon BMRS recorded during the 2026-09-15 07:30:03..10:35:59Z NESO flat-line!
    el_sep_path = GB_C2_DIR / "elexon_2026_09.parquet"
    if el_sep_path.exists() and out.get("2026-09"):
        r0 = out["2026-09"][0]
        df_el = pd.read_parquet(el_sep_path)
        sub_el = df_el[(df_el["ts_utc"] >= r0["start_ts_utc"]) & (df_el["ts_utc"] <= r0["end_ts_utc"])]
        r0["elexon_during_neso_outage"] = {
            "n_15s_rows": int(len(sub_el)),
            "n_valid_rows": int(sub_el["f_hz"].notna().sum()),
            "f_min_hz": round(float(sub_el["f_hz"].min()), 4),
            "f_max_hz": round(float(sub_el["f_hz"].max()), 4),
            "f_std_hz": round(float(sub_el["f_hz"].std()), 5),
            "n_distinct_values": int(sub_el["f_hz"].nunique()),
            "finding": "Elexon BMRS remained fully dynamic (49.895 to 50.148 Hz, std=53.0 mHz, 189 distinct values) throughout NESO's 3.1-hour flat-filled outage on 2026-09-15!",
        }
    return out


def ncc_1d(q: np.ndarray, r: np.ndarray) -> np.ndarray:
    L = len(q)
    qz = q - np.mean(q)
    qn = float(np.sqrt(np.sum(qz * qz)))
    num = fftconvolve(r, qz[::-1], mode="valid")
    cs = np.r_[0.0, np.cumsum(r)]
    cs2 = np.r_[0.0, np.cumsum(r * r)]
    s = cs[L:] - cs[:-L]
    s2 = cs2[L:] - cs2[:-L]
    var = np.maximum(s2 - (s * s) / L, 1e-18)
    return num / (qn * np.sqrt(var) + 1e-18)


def search_15s_multiphase(q_1s: np.ndarray, r_15s: np.ndarray, w0_ts: int, mode: str) -> int:
    g0 = (-w0_ts) % 15
    best_sc = -np.inf
    best_c = 0
    L = len(q_1s)
    for ph in range(15):
        if mode == "pt":
            qs = q_1s[ph::15]
        else:
            nb = (L - ph) // 15
            qs = q_1s[ph : ph + 15 * nb].reshape(nb, 15).mean(axis=1)
        if len(qs) < 4:
            continue
        sc = ncc_1d(qs, r_15s)
        k = int(np.argmax(sc))
        c = g0 + 15 * k - ph
        if sc[k] > best_sc and c >= 0:
            best_sc = float(sc[k])
            best_c = int(c)
    return best_c


def reproduce_c2_feasibility_table(n_trials: int = 400, seed: int = 20261108) -> dict:
    """
    Independently reproduce C2's feasibility table with our own seed (20261108) and n = 400 (>= 300)
    across D in {2, 5, 10, 20} min, sigma = 2 mHz, 24 h window on Aug + Sep 2026,
    AND add two extra columns that C2 did not test:
    - Real Elexon 15 s matched against 15 s block-averaged query (`ref_elexon_real_avg`)
    - Real Elexon 15 s linearly interpolated to 1 s matched against 1 s query (`ref_elexon_real_lin1s`)
    """
    df_aug = pd.read_parquet(NESO_DIR / "neso_2026-08.parquet")
    df_sep = pd.read_parquet(NESO_DIR / "neso_2026-09.parquet")
    df_n = pd.concat([df_aug, df_sep], ignore_index=True)
    t = df_n["ts_utc"].to_numpy(dtype=np.int64)
    f = df_n["f_hz"].to_numpy(dtype=np.float64, copy=True)

    # Mask the 2026-09-15 flat-filled outage (1789457403..1789468559)
    f[(t >= 1789457403) & (t <= 1789468559)] = np.nan

    # Load real Elexon 15s for Aug + Sep 2026 from datasets/raw/gb/
    el_aug = pd.read_parquet(GB_C2_DIR / "elexon_2026_08.parquet")
    el_sep = pd.read_parquet(GB_C2_DIR / "elexon_2026_09.parquet")
    df_el = pd.concat([el_aug, el_sep], ignore_index=True)
    N = len(f)
    e_at = np.full(N, np.nan, dtype=np.float64)
    idx_e = df_el["ts_utc"].to_numpy(dtype=np.int64) - int(t[0])
    ok_e = (idx_e >= 0) & (idx_e < N)
    e_at[idx_e[ok_e]] = df_el["f_hz"].to_numpy(dtype=np.float64)[ok_e]

    rng = np.random.default_rng(seed)
    win_s = 86400
    tol_s = 15
    sigma_hz = 0.002
    durs_min = [2, 5, 10, 20]

    table = {}
    t0_bench = time.time()
    for dm in durs_min:
        D = dm * 60
        keys = [
            "ref_1s",
            "ref_15s_pt",
            "ref_15s_avg",
            "ref_elexon_real_pt",
            "ref_elexon_real_avg",
            "ref_elexon_real_lin1s",
        ]
        hits = {k: 0 for k in keys}
        errs = {k: [] for k in keys}
        count = 0
        while count < n_trials:
            s = int(rng.integers(0, N - D))
            w = s - int(rng.integers(0, win_s - D + 1))
            if w < 0 or w + win_s > N:
                continue
            r_1s = f[w : w + win_s]
            if np.isnan(r_1s).any():
                continue
            w0_ts = int(t[w])
            g0 = (-w0_ts) % 15
            n15 = (win_s - g0) // 15
            r_el_15 = e_at[w + g0 : w + g0 + 15 * n15 : 15]
            if np.isnan(r_el_15).any():
                continue

            q_1s = f[s : s + D] + rng.normal(0.0, sigma_hz, D)
            true_offset = s - w

            # 1. ref_1s
            sc_1s = ncc_1d(q_1s, r_1s)
            c_1s = int(np.argmax(sc_1s))

            # 2. ref_15s_pt (NESO decimated)
            r_neso_pt = r_1s[g0 : g0 + 15 * n15 : 15]
            c_15_pt = search_15s_multiphase(q_1s, r_neso_pt, w0_ts, "pt")

            # 3. ref_15s_avg (NESO 15s block mean)
            r_neso_avg = r_1s[g0 : g0 + 15 * n15].reshape(n15, 15).mean(axis=1)
            c_15_avg = search_15s_multiphase(q_1s, r_neso_avg, w0_ts, "avg")

            # 4. ref_elexon_real_pt (Real Elexon 15s vs point-sampled query)
            c_el_pt = search_15s_multiphase(q_1s, r_el_15, w0_ts, "pt")

            # 5. ref_elexon_real_avg (Real Elexon 15s vs 15s block-averaged query!)
            c_el_avg = search_15s_multiphase(q_1s, r_el_15, w0_ts, "avg")

            # 6. ref_elexon_real_lin1s (Real Elexon 15s linearly interpolated to 1s vs 1s query!)
            x_el = np.arange(g0, g0 + 15 * n15, 15, dtype=np.float64)
            x_full = np.arange(win_s, dtype=np.float64)
            r_el_lin1s = np.interp(x_full, x_el, r_el_15)
            sc_el_lin = ncc_1d(q_1s, r_el_lin1s)
            c_el_lin = int(np.argmax(sc_el_lin))

            preds = {
                "ref_1s": c_1s,
                "ref_15s_pt": c_15_pt,
                "ref_15s_avg": c_15_avg,
                "ref_elexon_real_pt": c_el_pt,
                "ref_elexon_real_avg": c_el_avg,
                "ref_elexon_real_lin1s": c_el_lin,
            }
            for k, pred_c in preds.items():
                err = abs(pred_c - true_offset)
                errs[k].append(err)
                if err <= tol_s:
                    hits[k] += 1
            count += 1

        table[f"D={dm}min"] = {
            "n": count,
            **{f"P_top1_within_15s_{k}": round(hits[k] / count, 4) for k in keys},
            **{f"median_abs_err_s_{k}": round(float(np.median(errs[k])), 2) for k in keys},
        }
        print(f"  [Feasibility D={dm}min, n={count}, elapsed={time.time()-t0_bench:.1f}s] {table[f'D={dm}min']}")

    return {
        "label": "SEMI-SYNTHETIC: real NESO 1 s (Aug+Sep 2026, outage masked) + white Gaussian noise (sigma=2 mHz); 24 h search window; independent W02 reproduction",
        "n_trials_per_cell": n_trials,
        "seed": seed,
        "sigma_hz": sigma_hz,
        "window_s": win_s,
        "tolerance_s": tol_s,
        "results": table,
    }


def make_c2_reproduction_and_transition_plot(dec_jan_feb: dict, feas: dict):
    plt.rcParams.update({"font.size": 10, "axes.grid": True, "grid.alpha": 0.3})
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.5, 5.2))

    # Left: Daily RMSE & exact-match transition across Dec 2025 -> Jan 2026 -> Feb 2026
    daily = dec_jan_feb["daily_series"]
    dates = [d["date"] for d in daily]
    rmses_0 = [d["rmse_at_0s_mhz"] for d in daily]
    rmses_best = [d["rmse_at_best_lag_mhz"] for d in daily]
    x = np.arange(len(dates))
    ax1.plot(x, rmses_0, "-", color="#1f77b4", lw=1.6, label="Daily RMSE @ $\\tau=0$ s (mHz)")
    ax1.plot(x, rmses_best, "--", color="#2ca02c", lw=1.4, label="Daily RMSE @ Best Daily Lag (mHz)")
    tick_pos = x[::7]
    ax1.set_xticks(tick_pos)
    ax1.set_xticklabels([dates[i] for i in tick_pos], rotation=40, ha="right", fontsize=8.5)
    ax1.set_ylabel("Daily RMSE: Elexon vs NESO (mHz)")
    ax1.set_title("(a) REAL-MEASURED: Daily NESO-vs-Elexon Transition (Dec 2025 – Feb 2026)")
    ax1.legend(loc="upper left", fontsize=8.5)

    # Right: Feasibility reproduction curve P(top-1 within +-15s) vs Clip Duration D
    d_mins = [2, 5, 10, 20]
    r_tab = feas["results"]
    p_1s = [r_tab[f"D={m}min"]["P_top1_within_15s_ref_1s"] for m in d_mins]
    p_15pt = [r_tab[f"D={m}min"]["P_top1_within_15s_ref_15s_pt"] for m in d_mins]
    p_15avg = [r_tab[f"D={m}min"]["P_top1_within_15s_ref_15s_avg"] for m in d_mins]
    p_el_pt = [r_tab[f"D={m}min"]["P_top1_within_15s_ref_elexon_real_pt"] for m in d_mins]
    p_el_avg = [r_tab[f"D={m}min"]["P_top1_within_15s_ref_elexon_real_avg"] for m in d_mins]
    p_el_lin = [r_tab[f"D={m}min"]["P_top1_within_15s_ref_elexon_real_lin1s"] for m in d_mins]

    ax2.plot(d_mins, p_1s, "k-o", lw=2, label="NESO 1 s Ref")
    ax2.plot(d_mins, p_15avg, "g--s", lw=1.8, label="NESO 15 s Block-Avg")
    ax2.plot(d_mins, p_15pt, "b:^", lw=1.8, label="NESO 15 s Point")
    ax2.plot(d_mins, p_el_pt, "r-o", lw=2, label="Real Elexon 15 s (Point Query — C2 method)")
    ax2.plot(d_mins, p_el_avg, "m-.d", lw=1.8, label="Real Elexon 15 s (Block-Avg Query — W02)")
    ax2.plot(d_mins, p_el_lin, "c--v", lw=1.8, label="Real Elexon 15 s (1 s Linear Interp — W02)")
    ax2.set_xticks(d_mins)
    ax2.set_xlabel("Clip Duration $D$ (minutes) in 24 h Search Window ($\\sigma=2$ mHz, $n=400$)")
    ax2.set_ylabel("$P(|\\hat{t}_0 - t_0| \\leq 15\\text{ s})$")
    ax2.set_ylim(-0.02, 1.05)
    ax2.set_title("(b) SEMI-SYNTHETIC: Top-1 Localization Recall vs Clip Duration")
    ax2.legend(loc="lower right", fontsize=8)

    fig.tight_layout()
    out_fig = PLOTS_DIR / "c2_reproduction_transition_and_feasibility.png"
    fig.savefig(out_fig, dpi=160)
    fig.savefig(FIG_DIR / "c2_reproduction_transition_and_feasibility.png", dpi=160)
    plt.close(fig)


def main():
    session = make_session()
    print("=== Step 1: Auditing full months Dec 2025, Jan 2026, Feb 2026 ===")
    dec_jan_feb = download_and_audit_dec_jan_feb(session)

    print("=== Step 2: Verifying flat-filled NESO outages & Elexon behaviour during outage ===")
    outages = verify_flat_filled_outages()
    print(json.dumps(outages, indent=2))

    print("=== Step 3: Running W02 independent reproduction of C2 feasibility table (n=400) ===")
    feas = reproduce_c2_feasibility_table(n_trials=400, seed=20261108)

    make_c2_reproduction_and_transition_plot(dec_jan_feb, feas)

    # Copy all W02 figures to work/W02/plots/ as required by Final Phase item 4
    for png in FIG_DIR.glob("*.png"):
        shutil.copy2(png, PLOTS_DIR / png.name)

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dec2025_jan2026_feb2026_full_audit": dec_jan_feb,
        "flat_filled_outages_verification": outages,
        "feasibility_reproduction_n400": feas,
    }
    out_path = WORK_DIR / "c2_reproduction_results.json"
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Saved {out_path}")


if __name__ == "__main__":
    main()
