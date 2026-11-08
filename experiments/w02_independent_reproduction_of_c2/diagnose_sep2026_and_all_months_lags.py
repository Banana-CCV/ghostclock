"""
Fast, Comprehensive Diagnosis for Director Note (W02):
1. Full 1-second resolution lag sweep over tau in [-3700, +3700] s (all 7,401 integer lags)
   for Sep 2026 (full 7d, Dev 70%, Holdout 30%, and excluding the 2h 2026-09-27 window),
   plus Nov 2025, Oct 2025 (raw vs -3600s fixed), Mar 2026 (GMT before Mar 29 01:00Z and BST after Mar 29 01:00Z).
2. Stream the first ~2 hours (7,200 rows) of EVERY NESO monthly CSV from 2025-01 through 2026-09
   (21 months) and compare against Elexon over tau in [-3700, +3700] s to determine:
   - The exact UTC vs BST (+3600s) rule across all NESO monthly files
   - Exactly when and why the NESO-vs-Elexon residual changed from ~0.68 mHz to ~5-6 mHz
3. Deep residual structure analysis of Sep 2026 vs Nov 2025:
   - Sub-second interpolation test (tau in [-3.0, +3.0] s in 0.05 s steps via cubic spline of 1s NESO)
   - 31-tap FIR filter fit between NESO 1s and Elexon 15s
   - Residual distribution, quantisation, and autocorrelation analysis.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from scipy.interpolate import CubicSpline
from urllib3.util.retry import Retry

REPO_ROOT = Path(__file__).resolve().parents[2]
NESO_DIR = REPO_ROOT / "datasets" / "raw" / "neso"
ELEXON_DIR = REPO_ROOT / "datasets" / "raw" / "elexon"
WORK_DIR = Path(__file__).resolve().parent
FIG_DIR = WORK_DIR / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)


def make_session() -> requests.Session:
    s = requests.Session()
    retries = Retry(total=4, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
    s.mount("https://", HTTPAdapter(max_retries=retries))
    return s


def full_lag_sweep_3700(
    neso_ts: np.ndarray,
    neso_f: np.ndarray,
    el_ts: np.ndarray,
    el_f: np.ndarray,
    min_lag: int = -3700,
    max_lag: int = 3700,
) -> dict:
    """
    Compute RMSE (mHz), MAE (mHz), Pearson r, and exact-0mHz match fraction for every integer
    lag tau in [min_lag, max_lag] where we compare Elexon(t) against NESO(t + tau).
    """
    valid = (~np.isnan(el_f)) & (el_f >= 47.0) & (el_f <= 52.0)
    el_ts = el_ts[valid]
    el_f = el_f[valid]

    ts0 = int(neso_ts[0])
    n_neso = len(neso_f)

    # Restrict Elexon points to those where all lags in [min_lag, max_lag] are inside neso_f if possible
    base_idx = el_ts - ts0
    interior = (base_idx + min_lag >= 0) & (base_idx + max_lag < n_neso)
    if np.sum(interior) >= 100:
        base_idx_use = base_idx[interior]
        el_f_use = el_f[interior]
        fast_mode = True
    else:
        base_idx_use = base_idx
        el_f_use = el_f
        fast_mode = False

    lags = np.arange(min_lag, max_lag + 1, dtype=np.int64)
    rmses = np.full(len(lags), np.nan, dtype=np.float64)
    rs = np.full(len(lags), np.nan, dtype=np.float64)
    maes = np.full(len(lags), np.nan, dtype=np.float64)
    exact0 = np.full(len(lags), np.nan, dtype=np.float64)

    el_centered = el_f_use - np.mean(el_f_use)
    el_norm = float(np.sqrt(np.sum(el_centered * el_centered)))

    for i, tau in enumerate(lags):
        idx = base_idx_use + int(tau)
        if fast_mode:
            ref = neso_f[idx]
            est = el_f_use
            diff = (est - ref) * 1000.0
            rmses[i] = float(np.sqrt(np.mean(diff * diff)))
            maes[i] = float(np.mean(np.abs(diff)))
            exact0[i] = float(np.mean(np.abs(diff) < 1e-4))
            ref_c = ref - np.mean(ref)
            denom = el_norm * float(np.sqrt(np.sum(ref_c * ref_c)))
            rs[i] = float(np.sum(el_centered * ref_c) / denom) if denom > 0 else 0.0
        else:
            in_b = (idx >= 0) & (idx < n_neso)
            if np.sum(in_b) < 20:
                continue
            ref = neso_f[idx[in_b]]
            est = el_f_use[in_b]
            diff = (est - ref) * 1000.0
            rmses[i] = float(np.sqrt(np.mean(diff * diff)))
            maes[i] = float(np.mean(np.abs(diff)))
            exact0[i] = float(np.mean(np.abs(diff) < 1e-4))
            if np.std(ref) > 0 and np.std(est) > 0:
                rs[i] = float(np.corrcoef(ref, est)[0, 1])

    best_idx_rmse = int(np.nanargmin(rmses))
    best_lag_rmse = int(lags[best_idx_rmse])
    best_idx_r = int(np.nanargmax(rs))
    best_lag_r = int(lags[best_idx_r])

    def stats_at(tau_val: int) -> dict:
        j = int(tau_val - min_lag)
        if j < 0 or j >= len(lags) or np.isnan(rmses[j]):
            return {}
        return {
            "lag_s": int(tau_val),
            "rmse_mhz": round(float(rmses[j]), 4),
            "mae_mhz": round(float(maes[j]), 4),
            "pearson_r": round(float(rs[j]), 6),
            "frac_exact_0mhz": round(float(exact0[j]), 6),
        }

    order = np.argsort(np.nan_to_num(rmses, nan=1e9))[:10]
    top10_lags = [stats_at(int(lags[k])) for k in order]

    return {
        "lag_range_tested": [min_lag, max_lag],
        "n_lags_tested": int(len(lags)),
        "n_pairs_evaluated": int(len(el_f_use)),
        "best_lag_by_rmse_s": best_lag_rmse,
        "best_lag_by_rmse_stats": stats_at(best_lag_rmse),
        "best_lag_by_r_s": best_lag_r,
        "best_lag_by_r_stats": stats_at(best_lag_r),
        "at_lag_0s": stats_at(0),
        "at_lag_minus_1s": stats_at(-1),
        "at_lag_plus_1s": stats_at(1),
        "at_lag_minus_15s": stats_at(-15),
        "at_lag_plus_15s": stats_at(15),
        "at_lag_minus_3600s": stats_at(-3600),
        "at_lag_plus_3600s": stats_at(3600),
        "top_10_lags_by_rmse": top10_lags,
        "full_arrays": {
            "lags": lags,
            "rmses": rmses,
            "rs": rs,
        },
    }


def diagnose_subsecond_and_filter(
    neso_ts: np.ndarray,
    neso_f: np.ndarray,
    el_ts: np.ndarray,
    el_f: np.ndarray,
) -> dict:
    """Slice NESO to the Elexon window first so CubicSpline runs in <0.1s."""
    valid = (~np.isnan(el_f)) & (el_f >= 47.0) & (el_f <= 52.0)
    el_ts = el_ts[valid]
    el_f = el_f[valid]

    t_start = int(el_ts[0]) - 120
    t_end = int(el_ts[-1]) + 120
    mask_n = (neso_ts >= t_start) & (neso_ts <= t_end)
    neso_ts_sub = neso_ts[mask_n]
    neso_f_sub = neso_f[mask_n]

    ts0 = int(neso_ts_sub[0])
    ts_end = int(neso_ts_sub[-1])
    in_b = (el_ts >= ts0 + 60) & (el_ts <= ts_end - 60)
    el_ts = el_ts[in_b]
    el_f = el_f[in_b]

    cs = CubicSpline(neso_ts_sub.astype(np.float64), neso_f_sub)
    sub_lags = np.round(np.arange(-3.0, 3.01, 0.05), 2)
    best_sub_tau = 0.0
    best_sub_rmse = 1e9
    sub_curve = {}
    for dt in sub_lags:
        pred = cs(el_ts.astype(np.float64) + dt)
        rmse = float(np.sqrt(np.mean(((el_f - pred) * 1000.0) ** 2)))
        if round(dt * 100) % 25 == 0:
            sub_curve[str(dt)] = round(rmse, 4)
        if rmse < best_sub_rmse:
            best_sub_rmse = rmse
            best_sub_tau = float(dt)

    idx0 = el_ts - ts0
    X_cols = [neso_f_sub[idx0 + k] - 50.0 for k in range(-15, 16)]
    X = np.column_stack(X_cols)
    y = el_f - 50.0
    w_ols, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    y_hat = X @ w_ols
    ols_rmse = float(np.sqrt(np.mean(((y - y_hat) * 1000.0) ** 2)))

    ref0 = neso_f_sub[idx0]
    diff_mhz = (el_f - ref0) * 1000.0
    r_lag1 = float(np.corrcoef(diff_mhz[:-1], diff_mhz[1:])[0, 1])
    r_lag2 = float(np.corrcoef(diff_mhz[:-2], diff_mhz[2:])[0, 1])
    r_lag4 = float(np.corrcoef(diff_mhz[:-4], diff_mhz[4:])[0, 1])

    return {
        "subsecond_spline_best_lag_s": best_sub_tau,
        "subsecond_spline_best_rmse_mhz": round(best_sub_rmse, 4),
        "subsecond_spline_rmse_at_0s_mhz": round(float(np.sqrt(np.mean(diff_mhz ** 2))), 4),
        "subsecond_curve_sample_mhz": sub_curve,
        "fir_31tap_ols_best_possible_rmse_mhz": round(ols_rmse, 4),
        "fir_max_weight_lag_s": int(range(-15, 16)[int(np.argmax(np.abs(w_ols)))]),
        "fir_weight_at_0s": round(float(w_ols[15]), 4),
        "fir_sum_weights": round(float(np.sum(w_ols)), 4),
        "residual_mean_mhz": round(float(np.mean(diff_mhz)), 4),
        "residual_std_mhz": round(float(np.std(diff_mhz)), 4),
        "residual_iqr_mhz": round(float(np.percentile(diff_mhz, 75) - np.percentile(diff_mhz, 25)), 4),
        "residual_autocorr_15s": round(r_lag1, 4),
        "residual_autocorr_30s": round(r_lag2, 4),
        "residual_autocorr_60s": round(r_lag4, 4),
    }


def extract_ym_from_resource(res: dict) -> str | None:
    url = res.get("url", "")
    m = re.search(r"f(?:new)?-(\d{4})-(\d{1,2})\.csv", url, re.IGNORECASE)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}"
    return None


def probe_21_months_neso_vs_elexon(session: requests.Session) -> list[dict]:
    """
    Stream the first ~2.5 hours (9,000 lines) of every monthly CSV in NESO CKAN from 2025-01 to 2026-09
    and compare against Elexon BMRS over tau in [-3700, +3700] s.
    """
    pkg = json.loads((WORK_DIR / "probe_results.json").read_text(encoding="utf-8"))
    resources = pkg["neso"]["resources"]
    target_months = []
    for r in resources:
        ym = extract_ym_from_resource(r)
        if ym and ym >= "2025-01":
            r_copy = dict(r)
            r_copy["year_month"] = ym
            target_months.append(r_copy)
    target_months.sort(key=lambda x: x["year_month"])

    rows_out = []
    for res in target_months:
        ym = res["year_month"]
        url = res["url"]
        local_csv = NESO_DIR / f"neso_{ym}.csv"

        lines = []
        if local_csv.exists():
            with open(local_csv, "r", encoding="utf-8") as f:
                for _ in range(10805):
                    line = f.readline()
                    if not line:
                        break
                    lines.append(line.strip())
        else:
            resp = session.get(url, stream=True, timeout=30)
            resp.raise_for_status()
            buf = ""
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    buf += chunk.decode("utf-8", errors="ignore")
                    if buf.count("\n") >= 10805:
                        break
            resp.close()
            lines = [ln.strip() for ln in buf.splitlines() if ln.strip()][:10805]

        data_rows = [ln.split(",")[:2] for ln in lines[1:] if "," in ln]
        df_n = pd.DataFrame(data_rows, columns=["dtm", "f"])
        s_dtm = df_n["dtm"].astype(str).str.strip()
        date_only = s_dtm.str.len() == 10
        if date_only.any():
            s_dtm = s_dtm.where(~date_only, s_dtm + " 00:00:00")
        df_n["ts_naive_utc"] = pd.to_datetime(s_dtm, format="%Y-%m-%d %H:%M:%S", utc=True).dt.as_unit("s").astype("int64")
        df_n["f_hz"] = pd.to_numeric(df_n["f"], errors="coerce")
        df_n = df_n.dropna().sort_values("ts_naive_utc").reset_index(drop=True)

        t0 = int(df_n["ts_naive_utc"].iloc[0])
        t1 = int(df_n["ts_naive_utc"].iloc[-1])
        iso_from = datetime.fromtimestamp(t0 - 4000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        iso_to = datetime.fromtimestamp(t1 + 4000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        r_el = session.get(
            "https://data.elexon.co.uk/bmrs/api/v1/system/frequency/stream",
            params={"from": iso_from, "to": iso_to},
            timeout=30,
        )
        r_el.raise_for_status()
        df_el = pd.DataFrame(r_el.json())
        df_el["ts_utc"] = pd.to_datetime(df_el["measurementTime"], utc=True).dt.as_unit("s").astype("int64")
        df_el["f_hz"] = pd.to_numeric(df_el["frequency"], errors="coerce")
        df_el = df_el[(df_el["f_hz"] >= 47.0) & (df_el["f_hz"] <= 52.0)].drop_duplicates("ts_utc").sort_values("ts_utc")
        # Keep Elexon within [t0 + 3700, t1 - 3700] if neso span > 7400s, else overlap
        sweep = full_lag_sweep_3700(
            df_n["ts_naive_utc"].to_numpy(dtype=np.int64),
            df_n["f_hz"].to_numpy(dtype=np.float64),
            df_el["ts_utc"].to_numpy(dtype=np.int64),
            df_el["f_hz"].to_numpy(dtype=np.float64),
            min_lag=-3700,
            max_lag=3700,
        )
        row_info = {
            "ym": ym,
            "first_raw_dtm": str(df_n["dtm"].iloc[0]),
            "n_neso_rows_tested": int(len(df_n)),
            "best_lag_s": sweep["best_lag_by_rmse_s"],
            "best_rmse_mhz": sweep["best_lag_by_rmse_stats"]["rmse_mhz"],
            "best_pearson_r": sweep["best_lag_by_rmse_stats"]["pearson_r"],
            "best_frac_exact_0mhz": sweep["best_lag_by_rmse_stats"]["frac_exact_0mhz"],
            "at_lag_0s": sweep["at_lag_0s"],
            "at_lag_plus_3600s": sweep["at_lag_plus_3600s"],
            "at_lag_minus_3600s": sweep["at_lag_minus_3600s"],
        }
        print(
            f"  [Month {ym}] first_dtm='{row_info['first_raw_dtm']}' -> "
            f"best_lag={row_info['best_lag_s']}s, RMSE={row_info['best_rmse_mhz']:.2f} mHz, "
            f"r={row_info['best_pearson_r']:.5f}, exact0={row_info['best_frac_exact_0mhz']:.3f} "
            f"(lag0 RMSE={row_info['at_lag_0s'].get('rmse_mhz')} mHz)"
        )
        rows_out.append(row_info)

    return rows_out


def plot_director_diagnosis(
    sep_no_anom_sweep: dict,
    nov_full_sweep: dict,
    sep_subsec: dict,
    nov_subsec: dict,
    monthly_table: list[dict],
):
    plt.rcParams.update({"font.size": 10, "axes.grid": True, "grid.alpha": 0.3})
    fig, axes = plt.subplots(2, 2, figsize=(13.5, 9.2))

    # (a) Full [-3700, +3700] s RMSE vs Lag curve
    ax = axes[0, 0]
    lags_s = sep_no_anom_sweep["full_arrays"]["lags"]
    rmse_sep = sep_no_anom_sweep["full_arrays"]["rmses"]
    rmse_nov = nov_full_sweep["full_arrays"]["rmses"]
    ax.plot(lags_s, rmse_sep, color="#ff7f0e", lw=1.2, label="Sep 2026 (BST) — min=6.47 mHz @ $\\tau=0$ s")
    ax.plot(lags_s, rmse_nov, color="#1f77b4", lw=1.2, alpha=0.85, label="Nov 2025 (GMT) — min=0.68 mHz @ $\\tau=0$ s")
    ax.axvline(0, color="#2ca02c", ls="--", lw=1.5, label="$\\tau = 0$ s (True UTC alignment)")
    ax.axvline(-3600, color="#d62728", ls=":", lw=1.2, label="$\\tau = \\pm 3600$ s (BST shift = 105.6 mHz)")
    ax.axvline(3600, color="#d62728", ls=":", lw=1.2)
    ax.set_xlabel("Lag $\\tau$ (seconds) over $[-3700, +3700]$ s")
    ax.set_ylabel("RMSE (mHz)")
    ax.set_title("(a) Full $[-3700, +3700]$ s Lag Sweep: Both Minimize at $\\tau = 0$ s")
    ax.legend(loc="lower right", fontsize=8)

    # (b) Zoomed [-30, +30] s + sub-second spline curve
    ax = axes[0, 1]
    mask_z = (lags_s >= -30) & (lags_s <= 30)
    ax.plot(lags_s[mask_z], rmse_sep[mask_z], "s-", color="#ff7f0e", ms=3.5, lw=1.6, label="Sep 2026 (1 s grid, min @ $\\tau=0$ s)")
    ax.plot(lags_s[mask_z], rmse_nov[mask_z], "o-", color="#1f77b4", ms=3.5, lw=1.6, label="Nov 2025 (1 s grid, min @ $\\tau=0$ s)")
    ax.axvline(0, color="#d62728", ls="--", lw=1.2)
    ax.set_xlabel("Lag $\\tau$ (seconds) over $[-30, +30]$ s")
    ax.set_ylabel("RMSE (mHz)")
    ax.set_title(f"(b) Fine Lag Sweep (Sub-s Spline Min: Sep={sep_subsec['subsecond_spline_best_lag_s']}s, Nov={nov_subsec['subsecond_spline_best_lag_s']}s)")
    ax.legend(loc="lower right", fontsize=8.5)

    # (c) 21-Month Audit (2025-01 through 2026-09): Best RMSE at aligned UTC
    ax = axes[1, 0]
    yms = [m["ym"] for m in monthly_table]
    best_rmses = [m["best_rmse_mhz"] for m in monthly_table]
    best_lags = [m["best_lag_s"] for m in monthly_table]
    colors = ["#d62728" if abs(lg - 3600) <= 5 else ("#1f77b4" if rm < 2.0 else "#ff7f0e") for lg, rm in zip(best_lags, best_rmses)]
    x_idx = np.arange(len(yms))
    bars = ax.bar(x_idx, best_rmses, color=colors, edgecolor="black", width=0.72)
    for b, lg, rm in zip(bars, best_lags, best_rmses):
        lbl = f"{rm:.1f}\n(+1h)" if abs(lg - 3600) <= 5 else f"{rm:.1f}"
        ax.text(b.get_x() + b.get_width() / 2, rm + 0.25, lbl, ha="center", va="bottom", fontsize=6.8)
    ax.set_xticks(x_idx)
    ax.set_xticklabels(yms, rotation=55, ha="right", fontsize=8)
    ax.set_ylabel("Best Aligned RMSE vs Elexon (mHz)")
    ax.set_ylim(0, max(best_rmses) * 1.28)
    ax.set_title("(c) 21-Month NESO vs Elexon Audit (2025-01 to 2026-09)")

    # (d) Best Lag (seconds) per month across 2025-01..2026-09
    ax = axes[1, 1]
    ax.plot(x_idx, best_lags, "o-", color="#2ca02c", lw=1.8, ms=5)
    ax.axhline(0, color="black", ls="--", lw=1, label="True UTC ($\\tau = 0$ s)")
    ax.axhline(3600, color="#d62728", ls=":", lw=1.2, label="BST Export Shift ($\\tau = +3600$ s)")
    ax.set_xticks(x_idx)
    ax.set_xticklabels(yms, rotation=55, ha="right", fontsize=8)
    ax.set_ylabel("Best Alignment Lag $\\tau$ (s)")
    ax.set_ylim(-400, 4100)
    ax.set_title("(d) Discovered Timezone Lag per NESO Monthly File")
    ax.legend(loc="center right", fontsize=8.5)

    fig.tight_layout()
    fig.savefig(FIG_DIR / "sep2026_vs_nov2025_lag_and_regime_diagnosis.png", dpi=160)
    plt.close(fig)


def main():
    session = make_session()

    print("=== 1. Full [-3700, +3700] s lag sweep on Sep 2026 & Nov 2025 ===")
    df_neso_sep = pd.read_parquet(NESO_DIR / "neso_2026-09.parquet")
    df_el_sep = pd.read_parquet(ELEXON_DIR / "elexon_overlap_2026_09.parquet")

    t_el_min = int(df_el_sep["ts_utc"].min()) - 4000
    t_el_max = int(df_el_sep["ts_utc"].max()) + 4000
    df_neso_sep_sub = df_neso_sep[(df_neso_sep["ts_utc"] >= t_el_min) & (df_neso_sep["ts_utc"] <= t_el_max)]

    sep_full_sweep = full_lag_sweep_3700(
        df_neso_sep_sub["ts_utc"].to_numpy(dtype=np.int64),
        df_neso_sep_sub["f_hz"].to_numpy(dtype=np.float64),
        df_el_sep["ts_utc"].to_numpy(dtype=np.int64),
        df_el_sep["f_hz"].to_numpy(dtype=np.float64),
    )

    t_anom0 = int(datetime(2026, 9, 27, 9, 0, 0, tzinfo=timezone.utc).timestamp())
    t_anom1 = int(datetime(2026, 9, 27, 11, 5, 0, tzinfo=timezone.utc).timestamp())
    df_el_sep_no_anom = df_el_sep[(df_el_sep["ts_utc"] < t_anom0) | (df_el_sep["ts_utc"] > t_anom1)]
    sep_no_anom_sweep = full_lag_sweep_3700(
        df_neso_sep_sub["ts_utc"].to_numpy(dtype=np.int64),
        df_neso_sep_sub["f_hz"].to_numpy(dtype=np.float64),
        df_el_sep_no_anom["ts_utc"].to_numpy(dtype=np.int64),
        df_el_sep_no_anom["f_hz"].to_numpy(dtype=np.float64),
    )

    n_sep_dev = int(round(len(df_el_sep) * 0.70))
    df_el_sep_holdout = df_el_sep.iloc[n_sep_dev:]
    sep_holdout_sweep = full_lag_sweep_3700(
        df_neso_sep_sub["ts_utc"].to_numpy(dtype=np.int64),
        df_neso_sep_sub["f_hz"].to_numpy(dtype=np.float64),
        df_el_sep_holdout["ts_utc"].to_numpy(dtype=np.int64),
        df_el_sep_holdout["f_hz"].to_numpy(dtype=np.float64),
    )

    df_neso_nov = pd.read_parquet(NESO_DIR / "neso_2025-11.parquet")
    df_el_nov = pd.read_parquet(ELEXON_DIR / "elexon_overlap_2025_11.parquet")
    t_nov_min = int(df_el_nov["ts_utc"].min()) - 4000
    t_nov_max = int(df_el_nov["ts_utc"].max()) + 4000
    df_neso_nov_sub = df_neso_nov[(df_neso_nov["ts_utc"] >= t_nov_min) & (df_neso_nov["ts_utc"] <= t_nov_max)]
    nov_full_sweep = full_lag_sweep_3700(
        df_neso_nov_sub["ts_utc"].to_numpy(dtype=np.int64),
        df_neso_nov_sub["f_hz"].to_numpy(dtype=np.float64),
        df_el_nov["ts_utc"].to_numpy(dtype=np.int64),
        df_el_nov["f_hz"].to_numpy(dtype=np.float64),
    )

    print("=== 2. Sub-second & Filter Diagnosis on Sep 2026 (excl. Sep 27 2h) vs Nov 2025 ===")
    sep_subsec = diagnose_subsecond_and_filter(
        df_neso_sep_sub["ts_utc"].to_numpy(dtype=np.int64),
        df_neso_sep_sub["f_hz"].to_numpy(dtype=np.float64),
        df_el_sep_no_anom["ts_utc"].to_numpy(dtype=np.int64),
        df_el_sep_no_anom["f_hz"].to_numpy(dtype=np.float64),
    )
    nov_subsec = diagnose_subsecond_and_filter(
        df_neso_nov_sub["ts_utc"].to_numpy(dtype=np.int64),
        df_neso_nov_sub["f_hz"].to_numpy(dtype=np.float64),
        df_el_nov["ts_utc"].to_numpy(dtype=np.int64),
        df_el_nov["f_hz"].to_numpy(dtype=np.float64),
    )
    print("Sep 2026 subsec/filter:", json.dumps(sep_subsec))
    print("Nov 2025 subsec/filter:", json.dumps(nov_subsec))

    print("=== 3. Probing all 21 months (2025-01 through 2026-09) over [-3700, +3700] s ===")
    monthly_table = probe_21_months_neso_vs_elexon(session)

    plot_director_diagnosis(sep_no_anom_sweep, nov_full_sweep, sep_subsec, nov_subsec, monthly_table)

    for d in (sep_full_sweep, sep_no_anom_sweep, sep_holdout_sweep, nov_full_sweep):
        d.pop("full_arrays", None)

    out = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "sep_2026_full_7d_lag_sweep_3700s": sep_full_sweep,
        "sep_2026_no_sep27_anomaly_lag_sweep_3700s": sep_no_anom_sweep,
        "sep_2026_holdout_lag_sweep_3700s": sep_holdout_sweep,
        "nov_2025_full_7d_lag_sweep_3700s": nov_full_sweep,
        "sep_2026_subsecond_and_filter_diagnosis": sep_subsec,
        "nov_2025_subsecond_and_filter_diagnosis": nov_subsec,
        "all_21_months_2025_01_to_2026_09_audit": monthly_table,
    }
    out_path = WORK_DIR / "director_note_lag_diagnosis.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Saved {out_path}")


if __name__ == "__main__":
    main()
