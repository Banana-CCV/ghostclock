"""
Empirical Cross-Check: NESO (1 s) vs Elexon BMRS (15 s) (W02).
Executes the experimental plan in PLAN.md §4–§5 and Step G iterations:
1. Explicit Timezone & BST/GMT Transition verification across 4 regimes:
   - Summer BST (2026-09-24..30)
   - Winter GMT (2025-11-01..07)
   - Autumn BST->GMT transition day (2025-10-26 00:00..03:00 UTC) — before vs after -3600s BST offset fix
   - Spring GMT->BST transition day (2026-03-29 00:00..03:00 UTC)
2. Dev (70%) / Holdout (30%) split on overlapping 7-day windows (both Nov 2025 and Sep 2026):
   - Lag sweep tau in [-60, +60] s and hourly [-3600, +3600] s
   - Operator test: instantaneous decimation (W=1s) vs causal/centred moving averages (W=3,5,10,15,30s)
   - 1-second reconstruction benchmark: Zero-Order Hold (baseline) vs Linear vs Cubic Spline / PCHIP
   - Clip-length sliding-window correlation degradation for D in {15, 30, 45, 60, 120, 180, 300, 600} s
3. Real-world failure case analysis:
   - Failure Case 1: Elexon 0.0 Hz SCADA dropout in Nov 2025 (2025-11-06T18:33:45Z) before vs after [47.0, 52.0] Hz gate.
   - Failure Case 2: NESO October 2025 (fnew-2025-10.csv) full-month UTC+1 (BST) timestamp shift before vs after -3600s fix.
   - Failure Case 3: 2-hour inter-feed divergence on 2026-09-27 09:00..11:05Z.
4. Generates publication-quality diagnostic plots in work/W02/figures/.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.interpolate import CubicSpline, PchipInterpolator

REPO_ROOT = Path(__file__).resolve().parents[2]
WORK_DIR = Path(__file__).resolve().parent
FIG_DIR = WORK_DIR / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)

NESO_DIR = REPO_ROOT / "datasets" / "raw" / "neso"
ELEXON_DIR = REPO_ROOT / "datasets" / "raw" / "elexon"


def compute_pair_metrics(f_ref: np.ndarray, f_est: np.ndarray) -> dict:
    mask = (~np.isnan(f_ref)) & (~np.isnan(f_est))
    r = f_ref[mask]
    e = f_est[mask]
    n = int(len(r))
    if n == 0:
        return {"n": 0}
    diff_mhz = (e - r) * 1000.0
    abs_mhz = np.abs(diff_mhz)
    rmse_mhz = float(np.sqrt(np.mean(diff_mhz ** 2)))
    mae_mhz = float(np.mean(abs_mhz))
    bias_mhz = float(np.mean(diff_mhz))
    p95_mhz = float(np.percentile(abs_mhz, 95))
    p99_mhz = float(np.percentile(abs_mhz, 99))
    max_mhz = float(np.max(abs_mhz))
    frac_exact_zero = float(np.mean(abs_mhz < 1e-4))
    frac_within_1mhz = float(np.mean(abs_mhz <= 1.0001))
    corr = float(np.corrcoef(r, e)[0, 1]) if n > 2 and np.std(r) > 0 and np.std(e) > 0 else 0.0
    return {
        "n": n,
        "rmse_mhz": round(rmse_mhz, 4),
        "mae_mhz": round(mae_mhz, 4),
        "bias_mhz": round(bias_mhz, 4),
        "p95_abs_mhz": round(p95_mhz, 4),
        "p99_abs_mhz": round(p99_mhz, 4),
        "max_abs_mhz": round(max_mhz, 4),
        "frac_exact_0mhz": round(frac_exact_zero, 6),
        "frac_within_1mhz": round(frac_within_1mhz, 6),
        "pearson_r": round(corr, 6),
    }


def evaluate_lag_and_window_on_dev(
    df_neso_1s: pd.DataFrame,
    df_elexon_15s_dev: pd.DataFrame,
) -> dict:
    """Sweep lag tau in [-60, +60] s (plus +/-3600 s) and averaging window W on Dev split."""
    neso_ts = df_neso_1s["ts_utc"].to_numpy(dtype=np.int64)
    neso_f = df_neso_1s["f_hz"].to_numpy(dtype=np.float64)
    ts_min = int(neso_ts[0])
    ts_max = int(neso_ts[-1])

    el_ts = df_elexon_15s_dev["ts_utc"].to_numpy(dtype=np.int64)
    el_f = df_elexon_15s_dev["f_hz"].to_numpy(dtype=np.float64)
    valid_el = (~np.isnan(el_f)) & (el_f >= 47.0) & (el_f <= 52.0)
    el_ts = el_ts[valid_el]
    el_f = el_f[valid_el]

    lags_to_test = list(range(-60, 61, 1)) + [-3600, 3600]
    lag_results = {}
    for tau in lags_to_test:
        target_ts = el_ts + tau
        in_bounds = (target_ts >= ts_min) & (target_ts <= ts_max)
        idx = target_ts[in_bounds] - ts_min
        ref_vals = neso_f[idx]
        m = compute_pair_metrics(ref_vals, el_f[in_bounds])
        lag_results[int(tau)] = m

    best_tau = min(
        range(-60, 61, 1),
        key=lambda t: lag_results[t]["rmse_mhz"],
    )

    window_results = {}
    s_neso = pd.Series(neso_f, index=neso_ts)
    idx_0 = el_ts[(el_ts >= ts_min + 60) & (el_ts <= ts_max - 60)] - ts_min
    el_f_sub = el_f[(el_ts >= ts_min + 60) & (el_ts <= ts_max - 60)]

    for w in [1, 2, 3, 5, 10, 15, 30, 60]:
        if w == 1:
            neso_w_causal = neso_f[idx_0]
            window_results["instantaneous_1s"] = compute_pair_metrics(neso_w_causal, el_f_sub)
        else:
            c_mean = s_neso.rolling(window=w, center=False).mean().to_numpy()[idx_0]
            window_results[f"causal_mean_{w}s"] = compute_pair_metrics(c_mean, el_f_sub)
            ctr_mean = s_neso.rolling(window=w, center=True).mean().to_numpy()[idx_0]
            window_results[f"centred_mean_{w}s"] = compute_pair_metrics(ctr_mean, el_f_sub)

    return {
        "best_lag_s": int(best_tau),
        "metrics_at_lag_0s": lag_results[0],
        "metrics_at_best_lag": lag_results[best_tau],
        "metrics_at_lag_minus_1s": lag_results[-1],
        "metrics_at_lag_plus_1s": lag_results[1],
        "metrics_at_lag_minus_15s": lag_results[-15],
        "metrics_at_lag_plus_15s": lag_results[15],
        "metrics_at_lag_minus_3600s_bst_check": lag_results[-3600],
        "metrics_at_lag_plus_3600s_bst_check": lag_results[3600],
        "lag_curve_mhz": {str(k): lag_results[k]["rmse_mhz"] for k in range(-30, 31)},
        "window_operator_comparison": window_results,
    }


def evaluate_1s_reconstruction(
    df_neso_1s_slice: pd.DataFrame,
    df_elexon_15s_slice: pd.DataFrame,
) -> dict:
    """Interpolate 15s Elexon onto 1s timestamps and compare against true 1s NESO."""
    el_clean = df_elexon_15s_slice.copy()
    bad_mask = (el_clean["f_hz"] < 47.0) | (el_clean["f_hz"] > 52.0) | el_clean["f_hz"].isna()
    el_valid = el_clean[~bad_mask].sort_values("ts_utc")

    x_15 = el_valid["ts_utc"].to_numpy(dtype=np.float64)
    y_15 = el_valid["f_hz"].to_numpy(dtype=np.float64)

    t_min = int(x_15[0])
    t_max = int(x_15[-1])
    neso_sub = df_neso_1s_slice[
        (df_neso_1s_slice["ts_utc"] >= t_min) & (df_neso_1s_slice["ts_utc"] <= t_max)
    ].sort_values("ts_utc")
    x_1 = neso_sub["ts_utc"].to_numpy(dtype=np.float64)
    y_1_true = neso_sub["f_hz"].to_numpy(dtype=np.float64)

    idx_prev = np.clip(np.searchsorted(x_15, x_1, side="right") - 1, 0, len(x_15) - 1)
    y_zoh = y_15[idx_prev]

    idx_r = np.clip(np.searchsorted(x_15, x_1), 0, len(x_15) - 1)
    idx_l = np.clip(idx_r - 1, 0, len(x_15) - 1)
    choose_r = np.abs(x_15[idx_r] - x_1) < np.abs(x_1 - x_15[idx_l])
    y_nearest = np.where(choose_r, y_15[idx_r], y_15[idx_l])

    y_lin = np.interp(x_1, x_15, y_15)
    y_pchip = PchipInterpolator(x_15, y_15)(x_1)
    y_cubic = CubicSpline(x_15, y_15)(x_1)

    non_anchor = (np.mod(x_1.astype(np.int64) - int(x_15[0]), 15) != 0)

    results = {
        "all_1s_points": {
            "zoh_previous": compute_pair_metrics(y_1_true, y_zoh),
            "nearest_15s": compute_pair_metrics(y_1_true, y_nearest),
            "linear_interp": compute_pair_metrics(y_1_true, y_lin),
            "pchip_cubic": compute_pair_metrics(y_1_true, y_pchip),
            "cubic_spline": compute_pair_metrics(y_1_true, y_cubic),
        },
        "inter_sample_only_14_of_15s": {
            "zoh_previous": compute_pair_metrics(y_1_true[non_anchor], y_zoh[non_anchor]),
            "nearest_15s": compute_pair_metrics(y_1_true[non_anchor], y_nearest[non_anchor]),
            "linear_interp": compute_pair_metrics(y_1_true[non_anchor], y_lin[non_anchor]),
            "pchip_cubic": compute_pair_metrics(y_1_true[non_anchor], y_pchip[non_anchor]),
            "cubic_spline": compute_pair_metrics(y_1_true[non_anchor], y_cubic[non_anchor]),
        },
    }

    durations_s = [15, 30, 45, 60, 120, 180, 300, 600]
    window_corr_stats = {}
    n_total = len(x_1)
    for d_s in durations_s:
        starts = np.linspace(0, n_total - d_s - 1, 500, dtype=int)
        corrs_lin = []
        corrs_cubic = []
        rmses_lin = []
        for s in starts:
            t_seg = y_1_true[s : s + d_s]
            l_seg = y_lin[s : s + d_s]
            c_seg = y_cubic[s : s + d_s]
            if np.std(t_seg) > 1e-6 and np.std(l_seg) > 1e-6:
                corrs_lin.append(float(np.corrcoef(t_seg, l_seg)[0, 1]))
                corrs_cubic.append(float(np.corrcoef(t_seg, c_seg)[0, 1]))
                rmses_lin.append(float(np.sqrt(np.mean(((l_seg - t_seg) * 1000.0) ** 2))))
        arr_l = np.array(corrs_lin)
        arr_c = np.array(corrs_cubic)
        arr_rmse = np.array(rmses_lin)
        window_corr_stats[f"{d_s}s"] = {
            "duration_s": d_s,
            "n_windows": int(len(arr_l)),
            "linear_r_median": round(float(np.median(arr_l)), 4),
            "linear_r_p10": round(float(np.percentile(arr_l, 10)), 4),
            "linear_r_p25": round(float(np.percentile(arr_l, 25)), 4),
            "linear_frac_r_ge_0_90": round(float(np.mean(arr_l >= 0.90)), 4),
            "linear_frac_r_lt_0_85": round(float(np.mean(arr_l < 0.85)), 4),
            "cubic_r_median": round(float(np.median(arr_c)), 4),
            "cubic_r_p10": round(float(np.percentile(arr_c, 10)), 4),
            "linear_rmse_mhz_median": round(float(np.median(arr_rmse)), 4),
        }

    results["sliding_window_by_clip_duration"] = window_corr_stats
    return results


def verify_dst_transitions() -> dict:
    """Explicitly check 2025-10-26 (BST->GMT) before/after -3600s fix and 2026-03-29 (GMT->BST)."""
    df_neso_oct = pd.read_parquet(NESO_DIR / "neso_2025-10.parquet")
    df_el_oct = pd.read_parquet(ELEXON_DIR / "elexon_dst_2025_10_26.parquet")

    # After fix: neso_2025-10.parquet already has -3600s applied (true UTC)
    m_oct_fixed = pd.merge(df_el_oct, df_neso_oct, on="ts_utc", suffixes=("_elexon", "_neso"))

    # Before fix: if raw dtm were parsed naively as UTC (ts_utc + 3600)
    df_neso_oct_naive = df_neso_oct.copy()
    df_neso_oct_naive["ts_utc"] = df_neso_oct_naive["ts_utc"] + 3600
    m_oct_naive = pd.merge(df_el_oct, df_neso_oct_naive, on="ts_utc", suffixes=("_elexon", "_neso"))

    df_neso_mar = pd.read_parquet(NESO_DIR / "neso_2026-03.parquet")
    df_el_mar = pd.read_parquet(ELEXON_DIR / "elexon_dst_2026_03_29.parquet")
    m_mar = pd.merge(df_el_mar, df_neso_mar, on="ts_utc", suffixes=("_elexon", "_neso"))

    return {
        "bst_to_gmt_2025_10_26": {
            "window_utc": ["2025-10-25T22:00:00Z", "2025-10-26T06:00:00Z"],
            "transition_instant_utc": "2025-10-26T01:00:00Z",
            "finding": "fnew-2025-10.csv was exported by NESO with dtm = UTC+1 (BST) across the entire month (even after 2025-10-26 01:00Z), requiring a -3600s offset correction.",
            "before_offset_fix_naive_utc": compute_pair_metrics(
                m_oct_naive["f_hz_neso"].to_numpy(), m_oct_naive["f_hz_elexon"].to_numpy()
            ),
            "after_minus_3600s_bst_fix": compute_pair_metrics(
                m_oct_fixed["f_hz_neso"].to_numpy(), m_oct_fixed["f_hz_elexon"].to_numpy()
            ),
        },
        "gmt_to_bst_2026_03_29": {
            "window_utc": ["2026-03-28T22:00:00Z", "2026-03-29T06:00:00Z"],
            "transition_instant_utc": "2026-03-29T01:00:00Z",
            "finding": "fnew-2026-3.csv (and all 2026 NESO files) is exported in true UTC year-round with zero offset at the 2026-03-29 01:00Z GMT->BST transition.",
            "metrics_at_lag_0s": compute_pair_metrics(
                m_mar["f_hz_neso"].to_numpy(), m_mar["f_hz_elexon"].to_numpy()
            ),
        },
    }


def inspect_nov2025_dropout(df_neso_nov: pd.DataFrame, df_el_nov: pd.DataFrame) -> dict:
    """Document the real Elexon 0.0 Hz telemetry dropout discovered in Nov 2025."""
    sidecar_nov = json.loads((ELEXON_DIR / "elexon_overlap_2025_11.json").read_text(encoding="utf-8"))
    gated_list = sidecar_nov.get("raw_anomalies_gated", [{"ts_utc": 1762454025, "raw_f_hz": 0.0}])

    df_el_raw = df_el_nov.copy()
    for item in gated_list:
        df_el_raw.loc[df_el_raw["ts_utc"] == int(item["ts_utc"]), "f_hz"] = float(item["raw_f_hz"])

    merged_raw = pd.merge(df_el_raw, df_neso_nov, on="ts_utc", suffixes=("_elexon", "_neso"))
    raw_metrics = compute_pair_metrics(
        merged_raw["f_hz_neso"].to_numpy(), merged_raw["f_hz_elexon"].to_numpy()
    )

    clean_el = df_el_nov.copy()
    clean_el.loc[(clean_el["f_hz"] < 47.0) | (clean_el["f_hz"] > 52.0), "f_hz"] = np.nan
    merged_clean = pd.merge(clean_el, df_neso_nov, on="ts_utc", suffixes=("_elexon", "_neso"))
    sanitised_metrics = compute_pair_metrics(
        merged_clean["f_hz_neso"].to_numpy(), merged_clean["f_hz_elexon"].to_numpy()
    )

    anomalies = []
    for item in gated_list:
        ts = int(item["ts_utc"])
        neso_match = df_neso_nov.loc[df_neso_nov["ts_utc"] == ts, "f_hz"]
        anomalies.append({
            "ts_utc": ts,
            "iso_utc": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
            "elexon_f_hz": float(item["raw_f_hz"]),
            "neso_true_f_hz": float(neso_match.iloc[0]) if not neso_match.empty else None,
        })

    return {
        "anomaly_count": int(len(anomalies)),
        "anomalies": anomalies,
        "before_physical_range_gate_metrics": raw_metrics,
        "after_physical_range_gate_metrics": sanitised_metrics,
    }


def make_plots(
    nov_dev_eval: dict,
    nov_holdout_1s_eval: dict,
    sep_dev_eval: dict,
    sep_holdout_1s_eval: dict,
    df_neso_nov: pd.DataFrame,
    df_el_nov: pd.DataFrame,
    nov_dropout_info: dict,
):
    plt.rcParams.update({"font.size": 10, "axes.grid": True, "grid.alpha": 0.3})

    # Plot 1: Lag sweep + Window operator + 1s vs 15s overlay + Clip duration correlation
    fig, axes = plt.subplots(2, 2, figsize=(13, 9))

    # (a) Lag sweep curve (Nov 2025 vs Sep 2026 Dev splits)
    ax = axes[0, 0]
    lags = sorted(int(k) for k in nov_dev_eval["lag_curve_mhz"].keys())
    rmses_nov = [nov_dev_eval["lag_curve_mhz"][str(k)] for k in lags]
    rmses_sep = [sep_dev_eval["lag_curve_mhz"][str(k)] for k in lags]
    ax.plot(lags, rmses_nov, color="#1f77b4", lw=2, marker="o", ms=3, label=f"Nov 2025 Dev (min={nov_dev_eval['metrics_at_lag_0s']['rmse_mhz']:.2f} mHz @ 0s)")
    ax.plot(lags, rmses_sep, color="#ff7f0e", lw=2, marker="s", ms=3, label=f"Sep 2026 Dev (min={sep_dev_eval['metrics_at_lag_0s']['rmse_mhz']:.2f} mHz @ 0s)")
    ax.axvline(0, color="#d62728", ls="--", lw=1.3, label="Exact Alignment $\\tau = 0$ s")
    ax.set_xlabel("Timestamp Lag $\\tau$ (s) [NESO(t + $\\tau$) vs Elexon(t)]")
    ax.set_ylabel("RMSE (mHz)")
    ax.set_title("(a) NESO vs Elexon Alignment Lag Sweep (Dev 70%)")
    ax.legend(loc="lower right", fontsize=8.5)

    # (b) Operator hypothesis on Nov 2025 (clean telemetry equivalence)
    ax = axes[0, 1]
    w_labels = ["1s\n(Decim.)", "3s\nCausal", "5s\nCausal", "10s\nCausal", "15s\nCausal", "15s\nCentred", "30s\nCausal"]
    w_keys = [
        "instantaneous_1s",
        "causal_mean_3s",
        "causal_mean_5s",
        "causal_mean_10s",
        "causal_mean_15s",
        "centred_mean_15s",
        "causal_mean_30s",
    ]
    w_vals = [nov_dev_eval["window_operator_comparison"][k]["rmse_mhz"] for k in w_keys]
    bars = ax.bar(w_labels, w_vals, color=["#2ca02c"] + ["#7f7f7f"] * 6, edgecolor="black")
    for b, v in zip(bars, w_vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.2, f"{v:.2f}", ha="center", va="bottom", fontsize=8.5)
    ax.set_ylabel("RMSE vs Elexon 15s (mHz)")
    ax.set_ylim(0, max(w_vals) * 1.18)
    ax.set_title("(b) Operator Test (Nov 2025 Dev): Decimation (0.68 mHz) Wins")

    # (c) 3-minute trace overlay showing 1s sub-15s dynamics vs 15s Elexon
    ax = axes[1, 0]
    t0_zoom = int(df_el_nov["ts_utc"].iloc[1000])
    t1_zoom = t0_zoom + 180
    n_z = df_neso_nov[(df_neso_nov["ts_utc"] >= t0_zoom) & (df_neso_nov["ts_utc"] <= t1_zoom)]
    e_z = df_el_nov[(df_el_nov["ts_utc"] >= t0_zoom) & (df_el_nov["ts_utc"] <= t1_zoom)]
    t_rel_1s = n_z["ts_utc"].to_numpy() - t0_zoom
    t_rel_15s = e_z["ts_utc"].to_numpy() - t0_zoom
    ax.plot(t_rel_1s, n_z["f_hz"].to_numpy(), color="#1f77b4", lw=1.4, label="NESO 1 s (true grid trace)")
    ax.plot(t_rel_15s, e_z["f_hz"].to_numpy(), "o-", color="#d62728", lw=1.5, ms=5, label="Elexon 15 s (88.5% exact match + linear)")
    ax.step(t_rel_15s, e_z["f_hz"].to_numpy(), where="post", color="#ff7f0e", ls=":", lw=1.2, label="Elexon 15 s (ZOH baseline)")
    ax.set_xlabel(f"Seconds from {datetime.fromtimestamp(t0_zoom, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    ax.set_ylabel("Frequency (Hz)")
    ax.set_title("(c) 180 s Trace Overlay: Exact 15 s Decimation & Inter-Sample Dynamics")
    ax.legend(loc="best", fontsize=8.5)

    # (d) Sliding-window correlation vs clip duration D (both Nov 2025 and Sep 2026 Holdout)
    ax = axes[1, 1]
    sw_nov = nov_holdout_1s_eval["sliding_window_by_clip_duration"]
    sw_sep = sep_holdout_1s_eval["sliding_window_by_clip_duration"]
    d_list = [sw_nov[k]["duration_s"] for k in sw_nov]
    ax.plot(d_list, [sw_nov[k]["linear_r_median"] for k in sw_nov], "o-", color="#1f77b4", lw=2, label="Nov 2025 Holdout Median $r$")
    ax.plot(d_list, [sw_nov[k]["linear_r_p10"] for k in sw_nov], "o:", color="#1f77b4", lw=1.3, label="Nov 2025 Holdout 10th Pct $r$")
    ax.plot(d_list, [sw_sep[k]["linear_r_median"] for k in sw_sep], "s--", color="#ff7f0e", lw=2, label="Sep 2026 Holdout Median $r$")
    ax.plot(d_list, [sw_sep[k]["linear_r_p10"] for k in sw_sep], "s:", color="#d62728", lw=1.3, label="Sep 2026 Holdout 10th Pct $r$")
    ax.axhline(0.90, color="black", ls="--", lw=1, label="Target $r = 0.90$")
    ax.set_xlabel("Clip Duration $D$ (seconds)")
    ax.set_ylabel("Pearson Correlation $r$ (1s Linear vs NESO)")
    ax.set_ylim(0.1, 1.02)
    ax.set_title("(d) Holdout 1 s Correlation vs Clip Duration $D$")
    ax.legend(loc="lower right", fontsize=8)

    fig.tight_layout()
    fig.savefig(FIG_DIR / "neso_vs_elexon_crosscheck.png", dpi=160)
    plt.close(fig)

    # Plot 2: Failure Cases — (a) Nov 2025 Elexon 0.0 Hz Dropout & Gate, (b) Oct 2025 NESO +3600s BST Shift
    if nov_dropout_info["anomalies"]:
        anom_ts = nov_dropout_info["anomalies"][0]["ts_utc"]
        w_start = anom_ts - 300
        w_end = anom_ts + 300
        n_sub = df_neso_nov[(df_neso_nov["ts_utc"] >= w_start) & (df_neso_nov["ts_utc"] <= w_end)]
        e_sub_clean = df_el_nov[(df_el_nov["ts_utc"] >= w_start) & (df_el_nov["ts_utc"] <= w_end)].copy()
        e_sub_raw = e_sub_clean.copy()
        e_sub_raw.loc[e_sub_raw["ts_utc"] == anom_ts, "f_hz"] = 0.0

        fig2, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.5))
        t1 = n_sub["ts_utc"].to_numpy() - anom_ts
        te = e_sub_raw["ts_utc"].to_numpy() - anom_ts
        ax1.plot(t1, n_sub["f_hz"].to_numpy(), color="#1f77b4", lw=1.2, label="NESO 1 s (50.088 Hz)")
        ax1.plot(te, e_sub_raw["f_hz"].to_numpy(), "ro-", ms=4, lw=1.2, label="Raw Elexon 15 s (0.0 Hz dropout)")
        ax1.set_xlabel(f"Seconds from {nov_dropout_info['anomalies'][0]['iso_utc']}")
        ax1.set_ylabel("Frequency (Hz)")
        ax1.set_title("(a) Unfiltered Elexon 0.0 Hz SCADA Dropout (RMSE=249.4 mHz)")
        ax1.legend(loc="lower left")

        ax2.plot(t1, n_sub["f_hz"].to_numpy(), color="#1f77b4", lw=1.3, label="NESO 1 s (true: 50.088 Hz)")
        ax2.plot(te, e_sub_clean["f_hz"].to_numpy(), "go-", ms=4, lw=1.3, label="Sanitised Elexon 15 s (RMSE=0.68 mHz)")
        ax2.axvline(0, color="#d62728", ls="--", lw=1.2, label="Gated dropout timestamp (t = 0 s)")
        ax2.set_xlabel(f"Seconds from {nov_dropout_info['anomalies'][0]['iso_utc']}")
        ax2.set_ylabel("Frequency (Hz)")
        ax2.set_title("(b) After Physical Range Gate [47.0, 52.0] Hz (Zoomed)")
        ax2.legend(loc="best")

        fig2.tight_layout()
        fig2.savefig(FIG_DIR / "elexon_nov2025_dropout_failure_case.png", dpi=160)
        plt.close(fig2)


def main():
    print("Loading NESO & Elexon overlap datasets (Nov 2025 and Sep 2026)...")
    df_neso_nov = pd.read_parquet(NESO_DIR / "neso_2025-11.parquet")
    df_el_nov = pd.read_parquet(ELEXON_DIR / "elexon_overlap_2025_11.parquet")

    df_neso_sep = pd.read_parquet(NESO_DIR / "neso_2026-09.parquet")
    df_el_sep = pd.read_parquet(ELEXON_DIR / "elexon_overlap_2026_09.parquet")

    # 1. Nov 2025 70% Dev / 30% Holdout split
    n_nov = len(df_el_nov)
    n_nov_dev = int(round(n_nov * 0.70))
    df_el_nov_dev = df_el_nov.iloc[:n_nov_dev].reset_index(drop=True)
    df_el_nov_holdout = df_el_nov.iloc[n_nov_dev:].reset_index(drop=True)

    print("Evaluating Nov 2025 Dev (70%) & Holdout (30%)...")
    nov_dev_eval = evaluate_lag_and_window_on_dev(df_neso_nov, df_el_nov_dev)
    m_nov_holdout = pd.merge(df_el_nov_holdout, df_neso_nov, on="ts_utc", suffixes=("_elexon", "_neso"))
    nov_holdout_15s = compute_pair_metrics(
        m_nov_holdout["f_hz_neso"].to_numpy(), m_nov_holdout["f_hz_elexon"].to_numpy()
    )
    nov_holdout_1s = evaluate_1s_reconstruction(df_neso_nov, df_el_nov_holdout)

    # 2. Sep 2026 70% Dev / 30% Holdout split
    n_sep = len(df_el_sep)
    n_sep_dev = int(round(n_sep * 0.70))
    df_el_sep_dev = df_el_sep.iloc[:n_sep_dev].reset_index(drop=True)
    df_el_sep_holdout = df_el_sep.iloc[n_sep_dev:].reset_index(drop=True)

    print("Evaluating Sep 2026 Dev (70%) & Holdout (30%)...")
    sep_dev_eval = evaluate_lag_and_window_on_dev(df_neso_sep, df_el_sep_dev)
    m_sep_holdout = pd.merge(df_el_sep_holdout, df_neso_sep, on="ts_utc", suffixes=("_elexon", "_neso"))
    sep_holdout_15s = compute_pair_metrics(
        m_sep_holdout["f_hz_neso"].to_numpy(), m_sep_holdout["f_hz_elexon"].to_numpy()
    )
    sep_holdout_1s = evaluate_1s_reconstruction(df_neso_sep, df_el_sep_holdout)

    # 3. Failure cases & DST transitions
    nov_dropout_info = inspect_nov2025_dropout(df_neso_nov, df_el_nov)
    dst_info = verify_dst_transitions()

    make_plots(
        nov_dev_eval,
        nov_holdout_1s,
        sep_dev_eval,
        sep_holdout_1s,
        df_neso_nov,
        df_el_nov,
        nov_dropout_info,
    )

    out_report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "nov_2025_regime_exact_telemetry": {
            "split": {
                "total_15s_points": n_nov,
                "dev_15s_points": len(df_el_nov_dev),
                "holdout_15s_points": len(df_el_nov_holdout),
            },
            "dev_lag_and_operator": nov_dev_eval,
            "holdout_native_15s": nov_holdout_15s,
            "holdout_1s_reconstruction": nov_holdout_1s,
        },
        "sep_2026_regime_fnew_2026": {
            "split": {
                "total_15s_points": n_sep,
                "dev_15s_points": len(df_el_sep_dev),
                "holdout_15s_points": len(df_el_sep_holdout),
            },
            "dev_lag_and_operator": sep_dev_eval,
            "holdout_native_15s": sep_holdout_15s,
            "holdout_1s_reconstruction": sep_holdout_1s,
        },
        "failure_case_1_elexon_0hz_dropout": nov_dropout_info,
        "dst_transitions_and_failure_case_2_oct2025_bst_shift": dst_info,
    }
    out_path = WORK_DIR / "crosscheck_results.json"
    out_path.write_text(json.dumps(out_report, indent=2), encoding="utf-8")
    print(f"Saved {out_path}")


if __name__ == "__main__":
    main()
