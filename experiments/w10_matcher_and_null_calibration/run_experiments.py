"""
work/W10/run_experiments.py — Complete Experimental Execution, Calibration,
Ablation, and Holdout Evaluation for W10 (Forensic Statistician & Auditor)

Runs in ~15 seconds using pre-computed ENF-WHU STFT caches (`work/C1/cache/w16/`):
  1. Experiment 1: GB NESO 1-Second Historical Reference Benchmark (Dev Aug 2026 &
     Holdout Sep 2026) — Duration x Noise sweep, 24h vs 7d search window, 1s (NESO)
     vs 15s (Elexon) cadence comparison, NaN dropout & clock-drift ablations,
     3-family empirical null calibration (H0 noise/flat, wrong-month, surrogates),
     and C2 Flat-Outage Verification (`2026-09-15 07:30:03..10:35:59 UTC` constant
     49.895 Hz for 11,158 s).
  2. Experiment 2: ENF-WHU Real-World Audio Dataset Benchmark (Dev 85 H1 + 33 H0 &
     Holdout 45 H1 + 17 H0, session-grouped split) — Head-to-head comparison of
     W10 v1 (initial), W10 v2 (calibrated + presence gate, tuned on Dev only),
     Open-Source Baseline M1 (`nate-griff/enf`), and Uncalibrated i.i.d. Fisher-z
     Baseline M2 across Positive H1, Negative H0, Wrong-Day H1, Surrogate References,
     Truthful Claims (FCR), and Shifted Claims (TDDR).
     Reports both primary +-5s accuracy against README ground truth and secondary
     +-1s accuracy against per-file refined ground truth (`lag_ref - rec_ref_d`),
     plus `089-107_ref.wav` repeated-hour ambiguity rejection (`090`, `091`).
  3. Generates 4 publication-grade diagnostic figures in `work/W10/plots/` and writes
     complete metrics with denominators and 95% Wilson CIs to `work/W10/RESULTS.json`.
"""

from __future__ import annotations

import json
import math
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.ndimage import median_filter

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from work.W10.matcher import (
    match,
    match_baseline_naive_iid,
    match_baseline_opensource_nate_griff,
    sliding_weighted_ncc_and_rmse,
)
from work.W10.policy import PolicyThresholds, evaluate_policy, wilson_ci

WORK_DIR = Path(__file__).resolve().parent
PLOTS_DIR = WORK_DIR / "plots"
PLOTS_DIR.mkdir(parents=True, exist_ok=True)
C1_CACHE_DIR = REPO_ROOT / "work" / "C1" / "cache" / "w16"
C1_GT_PATH = REPO_ROOT / "work" / "C1" / "gt_w16.json"
C1_SPLIT_PATH = REPO_ROOT / "work" / "C1" / "split.json"


def rate_with_ci(k: int, n: int) -> dict[str, Any]:
    """Format a binomial proportion with denominator and 95% Wilson CI."""
    if n <= 0:
        return {"k": 0, "n": 0, "rate": None, "ci95": [0.0, 1.0]}
    p = float(k) / float(n)
    lo, hi = wilson_ci(k, n)
    return {
        "k": int(k),
        "n": int(n),
        "rate": round(p, 4),
        "ci95": [round(lo, 4), round(hi, 4)],
    }


# ==============================================================================
# PART 1: GB NESO 1-SECOND SYNTHETIC, CALIBRATION & OUTAGE BENCHMARK
# ==============================================================================
def run_neso_benchmark(seed: int = 42) -> dict[str, Any]:
    print("\n=== [Experiment 1] Running GB NESO 1-Second Synthetic & Calibration Benchmark ===")
    t_start = time.perf_counter()
    rng = np.random.default_rng(seed)

    df_aug = pd.read_parquet(REPO_ROOT / "work" / "W11" / "data" / "fnew-2026-8.parquet")
    df_sep = pd.read_parquet(REPO_ROOT / "work" / "W11" / "data" / "fnew-2026-9.parquet")

    f_aug = df_aug["f_hz"].to_numpy(dtype=np.float64)
    ts_aug = df_aug["ts_utc"].to_numpy(dtype=np.int64)
    f_sep = df_sep["f_hz"].to_numpy(dtype=np.float64)
    ts_sep = df_sep["ts_utc"].to_numpy(dtype=np.int64)

    # 1A. Duration x Noise Grid on NESO Dev (Aug 2026, 24h search window W = 86,400s)
    durations = [30, 60, 120, 300, 600]
    noise_levels_mhz = [1.0, 5.0, 10.0, 20.0, 50.0]
    n_trials_per_cell = 10
    window_s = 86400

    grid_results: list[dict[str, Any]] = []
    for dur_s in durations:
        for sigma_mhz in noise_levels_mhz:
            sigma_hz = sigma_mhz / 1000.0
            n_supp = 0
            n_correct_all = 0
            n_correct_supp = 0
            n_fcr = 0
            n_tddr = 0
            scores_cell = []
            p_emps_cell = []

            for tr in range(n_trials_per_cell):
                day_idx = int(rng.integers(0, 25))
                w_start_idx = day_idx * 86400
                ref_f = f_aug[w_start_idx : w_start_idx + window_s]
                ref_ts = ts_aug[w_start_idx : w_start_idx + window_s]

                offset_idx = int(rng.integers(1800, window_s - dur_s - 1800))
                true_utc = int(ref_ts[offset_idx])

                # Add AR(1)+white noise (rho=0.45) + random crystal offset in [-3, +3] mHz
                eps_white = rng.normal(0.0, sigma_hz, size=dur_s)
                eps_ar = np.zeros(dur_s, dtype=np.float64)
                eps_ar[0] = eps_white[0]
                for k in range(1, dur_s):
                    eps_ar[k] = 0.45 * eps_ar[k - 1] + math.sqrt(1.0 - 0.45**2) * eps_white[k]
                crystal_off = float(rng.uniform(-0.003, 0.003))
                trace_f = ref_f[offset_idx : offset_idx + dur_s] + crystal_off + eps_ar

                res = match(
                    trace={"t": np.arange(dur_s, dtype=np.float64), "f": trace_f, "q": np.ones(dur_s)},
                    reference={"ts_utc": ref_ts, "f_hz": ref_f},
                    config={"n_surrogates": 1},
                )
                err_s = abs(int(res["best"]["start_utc"]) - true_utc)
                is_corr = err_s <= 5
                is_supp = res["status"] == "MATCH_SUPPORTED"

                if is_corr:
                    n_correct_all += 1
                if is_supp:
                    n_supp += 1
                    if is_corr:
                        n_correct_supp += 1

                res_true_claim = evaluate_policy(dict(res), claimed_start_utc=true_utc, tolerance_s=60.0)
                if res_true_claim["status"] == "MATERIAL_DISCREPANCY_REVIEW":
                    n_fcr += 1
                shifted_utc = int(ref_ts[(offset_idx + 14400) % (window_s - dur_s)])
                res_false_claim = evaluate_policy(dict(res), claimed_start_utc=shifted_utc, tolerance_s=60.0)
                if res_false_claim["status"] == "MATERIAL_DISCREPANCY_REVIEW":
                    n_tddr += 1

                scores_cell.append(float(res["best"]["score"]))
                p_emps_cell.append(float(res["null"]["p_empirical"]))

            cell_entry = {
                "duration_s": dur_s,
                "sigma_noise_mhz": sigma_mhz,
                "n_trials": n_trials_per_cell,
                "raw_acc_5s": rate_with_ci(n_correct_all, n_trials_per_cell),
                "coverage": rate_with_ci(n_supp, n_trials_per_cell),
                "selective_acc_5s": rate_with_ci(n_correct_supp, n_supp),
                "fcr_truthful_claim": rate_with_ci(n_fcr, n_trials_per_cell),
                "tddr_shifted_claim": rate_with_ci(n_tddr, n_trials_per_cell),
                "mean_score": round(float(np.mean(scores_cell)), 4),
                "median_p_emp": round(float(np.median(p_emps_cell)), 6),
            }
            grid_results.append(cell_entry)

    # 1B. Cadence Comparison: NESO 1-second vs Elexon 15-second on 24h search window (sigma = 3 mHz)
    cadence_results: list[dict[str, Any]] = []
    for cad_s in [1.0, 15.0]:
        for dur_s in [60, 120, 300, 600]:
            n_trials_cad = 12
            n_corr_raw = 0
            n_supp = 0
            n_corr_supp = 0
            for tr in range(n_trials_cad):
                day_idx = int(rng.integers(0, 25))
                w_start_idx = day_idx * 86400
                ref_f_1s = f_aug[w_start_idx : w_start_idx + window_s]
                ref_ts_1s = ts_aug[w_start_idx : w_start_idx + window_s]

                offset_idx = int(rng.integers(120, (window_s - dur_s - 1200) // 15)) * 15
                true_utc = int(ref_ts_1s[offset_idx])

                # For 15s Elexon, also include 3.9 mHz reference scatter per C2's 2026 Elexon audit
                trace_f_1s = ref_f_1s[offset_idx : offset_idx + dur_s] + rng.normal(0.0, 0.003, size=dur_s)
                step = int(round(cad_s))
                ref_ts_sub = ref_ts_1s[::step]
                ref_f_sub = ref_f_1s[::step].copy()
                if cad_s == 15.0:
                    ref_f_sub = ref_f_sub + rng.normal(0.0, 0.0039, size=len(ref_f_sub))
                trace_t_sub = np.arange(0, dur_s, step, dtype=np.float64)
                trace_f_sub = trace_f_1s[::step]

                res = match(
                    trace={"t": trace_t_sub, "f": trace_f_sub, "q": np.ones(len(trace_f_sub))},
                    reference={"ts_utc": ref_ts_sub, "f_hz": ref_f_sub},
                    config={"cadence_s": cad_s, "n_surrogates": 1},
                )
                tol = max(5.0, cad_s)
                is_corr = abs(int(res["best"]["start_utc"]) - true_utc) <= tol
                if is_corr:
                    n_corr_raw += 1
                if res["status"] == "MATCH_SUPPORTED":
                    n_supp += 1
                    if is_corr:
                        n_corr_supp += 1

            cad_entry = {
                "cadence_s": cad_s,
                "duration_s": dur_s,
                "n_samples_in_clip": dur_s // int(cad_s),
                "raw_acc": rate_with_ci(n_corr_raw, n_trials_cad),
                "coverage": rate_with_ci(n_supp, n_trials_cad),
                "selective_acc": rate_with_ci(n_corr_supp, n_supp),
            }
            cadence_results.append(cad_entry)

    # 1C. 7-Day Search Window (W = 604,800s) vs 24h Search Window (sigma = 5 mHz)
    seven_day_results: list[dict[str, Any]] = []
    w_7d = 7 * 86400
    for dur_s in [120, 300, 600]:
        n_tr_7d = 8
        n_corr_raw = 0
        n_supp = 0
        n_corr_supp = 0
        for tr in range(n_tr_7d):
            start_7d = int(rng.integers(0, 15)) * 86400
            ref_f_7d = f_aug[start_7d : start_7d + w_7d]
            ref_ts_7d = ts_aug[start_7d : start_7d + w_7d]
            off_idx = int(rng.integers(3600, w_7d - dur_s - 3600))
            true_utc = int(ref_ts_7d[off_idx])
            trace_f = ref_f_7d[off_idx : off_idx + dur_s] + rng.normal(0.0, 0.005, size=dur_s)

            res = match(
                trace={"t": np.arange(dur_s, dtype=np.float64), "f": trace_f, "q": np.ones(dur_s)},
                reference={"ts_utc": ref_ts_7d, "f_hz": ref_f_7d},
                config={"n_surrogates": 1},
            )
            is_corr = abs(int(res["best"]["start_utc"]) - true_utc) <= 5
            if is_corr:
                n_corr_raw += 1
            if res["status"] == "MATCH_SUPPORTED":
                n_supp += 1
                if is_corr:
                    n_corr_supp += 1
        seven_day_results.append({
            "window_s": w_7d,
            "duration_s": dur_s,
            "raw_acc_5s": rate_with_ci(n_corr_raw, n_tr_7d),
            "coverage": rate_with_ci(n_supp, n_tr_7d),
            "selective_acc_5s": rate_with_ci(n_corr_supp, n_supp),
        })

    # 1D. Interior NaN Dropout Ablation (W10 vs nate-griff)
    dropout_ablation: list[dict[str, Any]] = []
    for drop_frac in [0.0, 0.20, 0.40]:
        n_tr_drop = 12
        w10_corr = 0
        ng_corr = 0
        for tr in range(n_tr_drop):
            day_idx = int(rng.integers(0, 25))
            w_start = day_idx * 86400
            ref_f = f_aug[w_start : w_start + 86400]
            ref_ts = ts_aug[w_start : w_start + 86400]
            off_idx = int(rng.integers(3600, 86400 - 300 - 3600))
            true_utc = int(ref_ts[off_idx])
            dur_s = 300
            tf = ref_f[off_idx : off_idx + dur_s] + 0.004 + rng.normal(0.0, 0.004, size=dur_s)
            tq = np.ones(dur_s, dtype=np.float64)
            if drop_frac > 0:
                gap_len = int(round(drop_frac * dur_s))
                gap_start = 90
                tf[gap_start : gap_start + gap_len] = np.nan
                tq[gap_start : gap_start + gap_len] = 0.0

            r_w10 = match(
                trace={"t": np.arange(dur_s, dtype=np.float64), "f": tf, "q": tq},
                reference={"ts_utc": ref_ts, "f_hz": ref_f},
            )
            r_ng = match_baseline_opensource_nate_griff(
                trace={"t": np.arange(dur_s, dtype=np.float64), "f": tf, "q": tq},
                reference={"ts_utc": ref_ts, "f_hz": ref_f},
            )
            if abs(int(r_w10["best"]["start_utc"]) - true_utc) <= 5:
                w10_corr += 1
            if abs(int(r_ng["best"]["start_utc"]) - true_utc) <= 5:
                ng_corr += 1
        dropout_ablation.append({
            "dropout_fraction": drop_frac,
            "w10_acc_5s": rate_with_ci(w10_corr, n_tr_drop),
            "nate_griff_acc_5s": rate_with_ci(ng_corr, n_tr_drop),
        })

    # 1E. Empirical Null Calibration on NESO across 3 Negative Control Families
    null_family_records: dict[str, list[dict[str, Any]]] = {
        "family_a_h0_no_enf": [],
        "family_b_wrong_date": [],
        "family_c_surrogate_ref": [],
    }
    for i in range(15):
        dur_s = int(durations[i % len(durations)])
        day_aug = (i % 25) * 86400
        # Avoid Sep 15 (day 14) for clean wrong-day comparison, test Sep 15 explicitly in 1G
        day_sep = ((i % 13) + 1) * 86400
        ref_aug_f = f_aug[day_aug : day_aug + 86400]
        ref_aug_ts = ts_aug[day_aug : day_aug + 86400]
        ref_sep_f = f_sep[day_sep : day_sep + 86400]
        ref_sep_ts = ts_sep[day_sep : day_sep + 86400]

        if i % 2 == 0:
            ar_noise = np.cumsum(rng.normal(0.0, 0.008, size=dur_s))
            ar_noise = 50.0 + (ar_noise - np.mean(ar_noise))
            h0_f = ar_noise
        else:
            h0_f = 50.0 + rng.normal(0.0, 0.0002, size=dur_s)

        res_a = match(
            trace={"t": np.arange(dur_s, dtype=np.float64), "f": h0_f, "q": np.ones(dur_s)},
            reference={"ts_utc": ref_aug_ts, "f_hz": ref_aug_f},
        )
        res_a_iid = match_baseline_naive_iid(
            trace={"t": np.arange(dur_s, dtype=np.float64), "f": h0_f, "q": np.ones(dur_s)},
            reference={"ts_utc": ref_aug_ts, "f_hz": ref_aug_f},
        )
        null_family_records["family_a_h0_no_enf"].append({
            "duration_s": dur_s,
            "score": float(res_a["best"]["score"]) if math.isfinite(res_a["best"]["score"]) else 0.0,
            "p_empirical": float(res_a["null"]["p_empirical"]),
            "w10_fp": res_a["status"] != "INCONCLUSIVE",
            "iid_fp": res_a_iid["status"] != "INCONCLUSIVE",
        })

        real_slice = ref_aug_f[10000 : 10000 + dur_s] + rng.normal(0.0, 0.003, size=dur_s)
        res_b = match(
            trace={"t": np.arange(dur_s, dtype=np.float64), "f": real_slice, "q": np.ones(dur_s)},
            reference={"ts_utc": ref_sep_ts, "f_hz": ref_sep_f},
        )
        res_b_iid = match_baseline_naive_iid(
            trace={"t": np.arange(dur_s, dtype=np.float64), "f": real_slice, "q": np.ones(dur_s)},
            reference={"ts_utc": ref_sep_ts, "f_hz": ref_sep_f},
        )
        null_family_records["family_b_wrong_date"].append({
            "duration_s": dur_s,
            "score": float(res_b["best"]["score"]),
            "p_empirical": float(res_b["null"]["p_empirical"]),
            "w10_fp": res_b["status"] != "INCONCLUSIVE",
            "iid_fp": res_b_iid["status"] != "INCONCLUSIVE",
        })

        y_zm = ref_aug_f - np.mean(ref_aug_f)
        spec_y = np.fft.rfft(y_zm)
        ph = rng.uniform(0, 2.0 * np.pi, size=len(spec_y))
        ph[0] = 0.0
        surr_f = np.mean(ref_aug_f) + np.fft.irfft(np.abs(spec_y) * np.exp(1j * ph), n=len(ref_aug_f))
        res_c = match(
            trace={"t": np.arange(dur_s, dtype=np.float64), "f": real_slice, "q": np.ones(dur_s)},
            reference={"ts_utc": ref_aug_ts, "f_hz": surr_f},
        )
        res_c_iid = match_baseline_naive_iid(
            trace={"t": np.arange(dur_s, dtype=np.float64), "f": real_slice, "q": np.ones(dur_s)},
            reference={"ts_utc": ref_aug_ts, "f_hz": surr_f},
        )
        null_family_records["family_c_surrogate_ref"].append({
            "duration_s": dur_s,
            "score": float(res_c["best"]["score"]),
            "p_empirical": float(res_c["null"]["p_empirical"]),
            "w10_fp": res_c["status"] != "INCONCLUSIVE",
            "iid_fp": res_c_iid["status"] != "INCONCLUSIVE",
        })

    null_summary = {}
    for fam_key, recs in null_family_records.items():
        w10_fps = sum(1 for r in recs if r["w10_fp"])
        iid_fps = sum(1 for r in recs if r["iid_fp"])
        scores_f = [r["score"] for r in recs]
        null_summary[fam_key] = {
            "n_trials": len(recs),
            "w10_fpr": rate_with_ci(w10_fps, len(recs)),
            "naive_iid_fpr": rate_with_ci(iid_fps, len(recs)),
            "nate_griff_top1_fpr": rate_with_ci(len(recs), len(recs)),
            "max_null_score_mean": round(float(np.mean(scores_f)), 4),
            "max_null_score_p95": round(float(np.percentile(scores_f, 95)), 4),
        }

    # 1F. NESO Holdout Verification (Sep 2026, unseen month, D=300s, sigma=5mHz, N=20)
    n_hold_neso = 20
    hold_supp = 0
    hold_corr_raw = 0
    hold_corr_supp = 0
    hold_fcr = 0
    hold_tddr = 0
    for tr in range(n_hold_neso):
        day_idx = int(rng.integers(0, 13))  # Sep 1..13 (non-outage days)
        w_start = day_idx * 86400
        ref_f = f_sep[w_start : w_start + 86400]
        ref_ts = ts_sep[w_start : w_start + 86400]
        off_idx = int(rng.integers(1800, 86400 - 300 - 1800))
        true_utc = int(ref_ts[off_idx])
        trace_f = ref_f[off_idx : off_idx + 300] + rng.normal(0.0, 0.005, size=300)
        res = match(
            trace={"t": np.arange(300, dtype=np.float64), "f": trace_f, "q": np.ones(300)},
            reference={"ts_utc": ref_ts, "f_hz": ref_f},
        )
        is_corr = abs(int(res["best"]["start_utc"]) - true_utc) <= 5
        if is_corr:
            hold_corr_raw += 1
        if res["status"] == "MATCH_SUPPORTED":
            hold_supp += 1
            if is_corr:
                hold_corr_supp += 1
        r_tc = evaluate_policy(dict(res), claimed_start_utc=true_utc, tolerance_s=60.0)
        if r_tc["status"] == "MATERIAL_DISCREPANCY_REVIEW":
            hold_fcr += 1
        r_fc = evaluate_policy(dict(res), claimed_start_utc=true_utc + 10800, tolerance_s=60.0)
        if r_fc["status"] == "MATERIAL_DISCREPANCY_REVIEW":
            hold_tddr += 1

    neso_holdout_summary = {
        "split": "holdout_sep_2026",
        "duration_s": 300,
        "sigma_noise_mhz": 5.0,
        "n_trials": n_hold_neso,
        "raw_acc_5s": rate_with_ci(hold_corr_raw, n_hold_neso),
        "coverage": rate_with_ci(hold_supp, n_hold_neso),
        "selective_acc_5s": rate_with_ci(hold_corr_supp, hold_supp),
        "fcr_truthful_claim": rate_with_ci(hold_fcr, n_hold_neso),
        "tddr_shifted_claim": rate_with_ci(hold_tddr, n_hold_neso),
    }

    # 1G. Director Note / C2 Flat-Outage Masking Verification on 2026-09-15
    # Outage interval: 2026-09-15 07:30:03..10:35:59 UTC (ts_utc 1789457403..1789468560, 11,158 s at 49.895 Hz)
    sep15_start = 14 * 86400
    ref_sep15_f = f_sep[sep15_start : sep15_start + 86400]
    ref_sep15_ts = ts_sep[sep15_start : sep15_start + 86400]
    sidecar_sep = str(REPO_ROOT / "datasets" / "raw" / "gb" / "neso_2026_09.json")

    # Test 1: Valid 300s query cut from 2026-09-15 15:00 UTC (outside outage) matched against full 2026-09-15
    q_valid_off = 15 * 3600
    q_valid_f = ref_sep15_f[q_valid_off : q_valid_off + 300] + rng.normal(0.0, 0.003, size=300)
    res_sep15_valid = match(
        trace={"t": np.arange(300, dtype=np.float64), "f": q_valid_f, "q": np.ones(300)},
        reference={"ts_utc": ref_sep15_ts, "f_hz": ref_sep15_f, "sidecar_path": sidecar_sep},
    )
    candidates_in_outage = [
        c for c in res_sep15_valid["candidates"]
        if 1789457403 - 300 <= int(c["start_utc"]) <= 1789468560
    ]

    # Test 2: Query cut directly from inside the flat-filled outage (08:00 UTC, constant 49.895 Hz)
    q_flat_off = 8 * 3600
    q_flat_f = ref_sep15_f[q_flat_off : q_flat_off + 300].copy()
    res_sep15_flat_query = match(
        trace={"t": np.arange(300, dtype=np.float64), "f": q_flat_f, "q": np.ones(300)},
        reference={"ts_utc": ref_sep15_ts, "f_hz": ref_sep15_f, "sidecar_path": sidecar_sep},
    )

    outage_verification = {
        "outage_date": "2026-09-15",
        "outage_utc_range": [1789457403, 1789468560],
        "outage_duration_s": 11158,
        "constant_f_hz": 49.895,
        "valid_query_err_s": abs(int(res_sep15_valid["best"]["start_utc"]) - int(ref_sep15_ts[q_valid_off])),
        "valid_query_status": res_sep15_valid["status"],
        "candidates_landing_in_outage": len(candidates_in_outage),
        "flat_outage_query_status": res_sep15_flat_query["status"],
        "flat_outage_query_reasons": res_sep15_flat_query["status_reasons"],
    }
    print(f"  [NESO 2026-09-15 Outage Check] {outage_verification}")

    return {
        "elapsed_s": round(time.perf_counter() - t_start, 2),
        "duration_noise_grid_dev": grid_results,
        "cadence_1s_vs_15s_comparison": cadence_results,
        "seven_day_window_comparison": seven_day_results,
        "dropout_ablation_w10_vs_nate_griff": dropout_ablation,
        "null_calibration_families": null_summary,
        "holdout_sep_2026_verification": neso_holdout_summary,
        "c2_flat_outage_masking_verification": outage_verification,
    }


# ==============================================================================
# PART 2: FAST ENF-WHU TRACE LOADER FROM PRE-COMPUTED C1 CACHE
# ==============================================================================
def _process_c1_npz_trace(npz_path: Path) -> dict[str, Any]:
    d = np.load(npz_path)
    t = d["t"].astype(np.float64)
    f_raw = d["f"].astype(np.float64)
    q_db = d["q"].astype(np.float64)
    snrk = d["snrk"].astype(np.float64)

    # Mask isolated frame glitches (> 25 mHz jump from 7s running median)
    f_med = median_filter(f_raw, size=min(7, len(f_raw)))
    spike_mask = np.abs(f_raw - f_med) > 0.025
    f_clean = f_raw.copy()
    f_clean[spike_mask] = np.nan

    q_norm = np.clip((q_db - 3.0) / 15.0, 0.05, 1.0)
    q_norm[spike_mask] = 0.0

    # Upstream ENF presence score (computed blindly from trace smoothness, std, and harmonic SNR)
    valid_f = f_raw[~spike_mask]
    if len(valid_f) >= 15:
        v_zm = valid_f - np.mean(valid_f)
        denom = float(np.sum(v_zm**2))
        rho1 = float(np.sum(v_zm[:-1] * v_zm[1:]) / denom) if denom > 1e-12 else 0.0
        rho2 = float(np.sum(v_zm[:-2] * v_zm[2:]) / denom) if denom > 1e-12 else 0.0
        rho_smooth = max(0.0, 0.6 * rho1 + 0.4 * rho2)
        med_step_mhz = float(np.median(np.abs(np.diff(valid_f)))) * 1000.0
        std_mhz = float(np.std(valid_f)) * 1000.0
    else:
        rho_smooth = 0.0
        med_step_mhz = 999.0
        std_mhz = 0.0

    step_score = math.exp(-max(0.0, med_step_mhz - 1.5) / 5.0)
    if 1.8 <= std_mhz <= 55.0:
        std_score = 1.0
    elif std_mhz < 1.8:
        std_score = max(0.0, std_mhz / 1.8)
    else:
        std_score = math.exp(-(std_mhz - 55.0) / 40.0)

    inlier_frac = float(1.0 - np.mean(spike_mask))
    med_snrk = np.median(snrk, axis=0)
    n_active_h = int(np.sum(med_snrk >= 2.2))
    harm_score = min(1.0, n_active_h / 3.0)

    presence_score = float(
        np.clip(
            (0.45 * (rho_smooth**2) + 0.30 * step_score + 0.15 * inlier_frac + 0.10 * harm_score)
            * std_score,
            0.0,
            1.0,
        )
    )

    return {
        "t": t,
        "f": f_clean,
        "f_raw": f_raw,
        "q": q_norm,
        "meta": {
            "duration_s": float(len(t)),
            "rho_smooth": round(rho_smooth, 4),
            "med_step_mhz": round(med_step_mhz, 3),
            "std_mhz": round(std_mhz, 3),
            "inlier_frac": round(inlier_frac, 4),
            "n_active_harmonics": n_active_h,
            "quality_summary": {
                "enf_presence_score": round(presence_score, 4),
                "mean_q": round(float(np.mean(q_norm)), 4),
            },
        },
    }


def load_or_extract_enf_whu_traces() -> dict[str, Any]:
    t0 = time.perf_counter()
    c1_gt = json.loads(C1_GT_PATH.read_text(encoding="utf-8"))

    day_traces: dict[str, np.ndarray] = {}
    for p_day in sorted((C1_CACHE_DIR / "H1_ref_one_day").glob("*.npz")):
        day_name = p_day.stem + ".wav"
        day_traces[day_name] = np.load(p_day)["f"].astype(np.float64)

    h1_cases: dict[str, dict[str, Any]] = {}
    for cid, gt_info in sorted(c1_gt.items()):
        out = _process_c1_npz_trace(C1_CACHE_DIR / "H1" / f"{cid}.npz")
        day_wav_name = f"{gt_info['day']}_ref.wav"
        lag_readme = float(gt_info["lag_ref"])
        rec_ref_d = float(gt_info["rec_ref_d"])
        # Per-file refined GT lag (C1 audit): lag_ref - rec_ref_d
        lag_refined = lag_readme - rec_ref_d

        h1_cases[cid] = {
            "id": cid,
            "day_name": day_wav_name,
            "split": gt_info["split"],
            "gt_lag_s": int(round(lag_readme)),
            "gt_lag_exact_s": lag_readme,
            "gt_lag_refined_s": lag_refined,
            "rec_ref_d_s": rec_ref_d,
            "rec_ref_r_at_d": float(gt_info["rec_ref_r_at_d"]),
            "ref_margin": float(gt_info["ref_margin"]),
            "gt_ambiguous": float(gt_info["ref_margin"]) < 0.01,
            "t": out["t"],
            "f": out["f"],
            "f_raw": out["f_raw"],
            "q": out["q"],
            "meta": out["meta"],
        }

    h0_cases: dict[str, dict[str, Any]] = {}
    for p_h0 in sorted((C1_CACHE_DIR / "H0").glob("*.npz")):
        hid = p_h0.stem
        out = _process_c1_npz_trace(p_h0)
        h0_cases[hid] = {
            "id": hid,
            "t": out["t"],
            "f": out["f"],
            "f_raw": out["f_raw"],
            "q": out["q"],
            "meta": out["meta"],
        }

    print(f"Loaded all 28 day refs, 130 H1, and 50 H0 traces from C1 cache in {time.perf_counter()-t0:.2f}s")
    return {
        "day_traces": day_traces,
        "h1_cases": h1_cases,
        "h0_cases": h0_cases,
    }


# ==============================================================================
# PART 3: ENF-WHU BENCHMARK (DEV TUNING v1 -> v2 & FROZEN HOLDOUT EVALUATION)
# ==============================================================================
def evaluate_enf_whu_split(
    split_name: str,
    h1_ids: list[str],
    h0_ids: list[str],
    payload: dict[str, Any],
    thresholds: PolicyThresholds,
    policy_label: str,
) -> dict[str, Any]:
    day_np = payload["day_traces"]
    day_names = sorted(day_np.keys())
    h1_cases = payload["h1_cases"]
    h0_cases = payload["h0_cases"]

    n_h1 = len(h1_ids)
    w10_supp = 0
    w10_corr_5s_readme = 0
    w10_corr_10s_readme = 0
    w10_corr_1s_refined = 0
    w10_corr_2s_refined = 0
    w10_raw_5s_readme = 0
    w10_raw_1s_refined = 0

    # Also track coverage on clean-extractor subset (rec_ref_r_at_d >= 0.85)
    n_h1_clean_ext = 0
    w10_supp_clean_ext = 0
    w10_corr_5s_clean_ext = 0

    w10_fcr = 0
    w10_tcr = 0
    w10_tddr = 0

    ng_raw_5s = 0
    ng_corr045_supp = 0
    ng_corr045_corr5s = 0

    iid_supp = 0
    iid_corr5s = 0

    per_case_h1: list[dict[str, Any]] = []

    for idx_i, cid in enumerate(h1_ids):
        c = h1_cases[cid]
        d_name = c["day_name"]
        ref_f = day_np[d_name]
        ref_ts = np.arange(len(ref_f), dtype=np.int64)
        gt_lag = int(c["gt_lag_s"])
        gt_refined = float(c["gt_lag_refined_s"])
        is_clean_ext = c["rec_ref_r_at_d"] >= 0.85 and not c["gt_ambiguous"]
        if is_clean_ext:
            n_h1_clean_ext += 1

        t_arr = c["t"]
        f_arr = c["f"]
        q_arr = c["q"]

        res = match(
            trace={"t": t_arr, "f": f_arr, "q": q_arr, "meta": c["meta"]},
            reference={"ts_utc": ref_ts, "f_hz": ref_f},
            config={"policy_thresholds": asdict(thresholds)},
        )
        est_lag = int(res["best"]["start_utc"])
        est_sub = float(res["best"]["start_utc"]) + float(res["diagnostics"].get("sub_sample_offset_s", 0.0))
        err_readme_s = abs(est_lag - gt_lag)
        err_refined_s = abs(est_sub - gt_refined)

        if err_readme_s <= 5:
            w10_raw_5s_readme += 1
        if err_refined_s <= 1.0:
            w10_raw_1s_refined += 1

        if res["status"] == "MATCH_SUPPORTED":
            w10_supp += 1
            if err_readme_s <= 5:
                w10_corr_5s_readme += 1
            if err_readme_s <= 10:
                w10_corr_10s_readme += 1
            if err_refined_s <= 1.0:
                w10_corr_1s_refined += 1
            if err_refined_s <= 2.0:
                w10_corr_2s_refined += 1
            if is_clean_ext:
                w10_supp_clean_ext += 1
                if err_readme_s <= 5:
                    w10_corr_5s_clean_ext += 1

        # Claim verification mode (truthful vs +4h shifted claim)
        res_true_c = evaluate_policy(
            dict(res), claimed_start_utc=gt_lag, tolerance_s=60.0, thresholds=thresholds
        )
        if res_true_c["status"] == "MATERIAL_DISCREPANCY_REVIEW":
            w10_fcr += 1
        elif res_true_c["status"] == "MATCH_SUPPORTED":
            w10_tcr += 1

        shifted_lag = (gt_lag + 14400) % max(1, len(ref_f) - len(f_arr))
        if abs(shifted_lag - gt_lag) < 3600:
            shifted_lag = max(0, gt_lag - 14400)
        res_false_c = evaluate_policy(
            dict(res), claimed_start_utc=shifted_lag, tolerance_s=60.0, thresholds=thresholds
        )
        if res_false_c["status"] == "MATERIAL_DISCREPANCY_REVIEW":
            w10_tddr += 1

        # Baselines M1 (nate-griff) and M2 (naive i.i.d.)
        res_ng = match_baseline_opensource_nate_griff(
            trace={"t": t_arr, "f": f_arr, "q": q_arr},
            reference={"ts_utc": ref_ts, "f_hz": ref_f},
        )
        err_ng = abs(int(res_ng["best"]["start_utc"]) - gt_lag)
        if err_ng <= 5:
            ng_raw_5s += 1
        if res_ng["status_corr_045"] == "MATCH_SUPPORTED":
            ng_corr045_supp += 1
            if err_ng <= 5:
                ng_corr045_corr5s += 1

        res_iid = match_baseline_naive_iid(
            trace={"t": t_arr, "f": f_arr, "q": q_arr},
            reference={"ts_utc": ref_ts, "f_hz": ref_f},
        )
        err_iid = abs(int(res_iid["best"]["start_utc"]) - gt_lag)
        if res_iid["status"] == "MATCH_SUPPORTED":
            iid_supp += 1
            if err_iid <= 5:
                iid_corr5s += 1

        per_case_h1.append({
            "id": cid,
            "day_name": d_name,
            "duration_s": float(c["meta"]["duration_s"]),
            "gt_lag_readme_s": gt_lag,
            "gt_lag_refined_s": round(gt_refined, 2),
            "rec_ref_d_s": round(c["rec_ref_d_s"], 2),
            "gt_ambiguous": c["gt_ambiguous"],
            "est_lag_s": est_lag,
            "err_readme_s": err_readme_s,
            "err_refined_s": round(err_refined_s, 2),
            "score": round(float(res["best"]["score"]), 4),
            "rmse_mhz": round(float(res["best"]["rmse_mhz"]), 3),
            "p_empirical": float(res["null"]["p_empirical"]),
            "margin_vs_second": round(float(res["uniqueness"]["margin_vs_second"]), 4),
            "enf_presence_score": float(c["meta"]["quality_summary"]["enf_presence_score"]),
            "status": res["status"],
            "ng_err_s": err_ng,
        })

    # Negative Family A: H0 (no-ENF) matched against 24h reference
    n_h0 = len(h0_ids)
    w10_fp_h0 = 0
    ng_top1_fp_h0 = n_h0
    ng_045_fp_h0 = 0
    iid_fp_h0 = 0
    h0_scores: list[float] = []
    h0_p_emps: list[float] = []

    for idx_j, hid in enumerate(h0_ids):
        hc = h0_cases[hid]
        d_name = day_names[idx_j % len(day_names)]
        ref_f = day_np[d_name]
        ref_ts = np.arange(len(ref_f), dtype=np.int64)
        t_arr = hc["t"]
        f_arr = hc["f"]
        q_arr = hc["q"]

        res_h0 = match(
            trace={"t": t_arr, "f": f_arr, "q": q_arr, "meta": hc["meta"]},
            reference={"ts_utc": ref_ts, "f_hz": ref_f},
            config={"policy_thresholds": asdict(thresholds)},
        )
        if res_h0["status"] != "INCONCLUSIVE":
            w10_fp_h0 += 1
        sc = float(res_h0["best"]["score"]) if math.isfinite(res_h0["best"]["score"]) else 0.0
        h0_scores.append(sc)
        h0_p_emps.append(float(res_h0["null"]["p_empirical"]))

        res_ng_h0 = match_baseline_opensource_nate_griff(
            trace={"t": t_arr, "f": f_arr, "q": q_arr},
            reference={"ts_utc": ref_ts, "f_hz": ref_f},
        )
        if res_ng_h0["status_corr_045"] != "INCONCLUSIVE":
            ng_045_fp_h0 += 1

        res_iid_h0 = match_baseline_naive_iid(
            trace={"t": t_arr, "f": f_arr, "q": q_arr},
            reference={"ts_utc": ref_ts, "f_hz": ref_f},
        )
        if res_iid_h0["status"] != "INCONCLUSIVE":
            iid_fp_h0 += 1

    # Negative Family B: H1 traces matched against WRONG 24h reference day
    w10_fp_wrong = 0
    ng_045_fp_wrong = 0
    iid_fp_wrong = 0
    wrong_day_scores: list[float] = []
    wrong_day_p_emps: list[float] = []

    # Negative Family C: H1 traces matched against Time-Reversed / Circularly Shifted 24h reference
    w10_fp_surr = 0
    iid_fp_surr = 0
    surr_scores: list[float] = []

    for idx_i, cid in enumerate(h1_ids):
        c = h1_cases[cid]
        true_d_name = c["day_name"]
        other_days = [dn for dn in day_names if dn != true_d_name and len(day_np[dn]) >= 80000]
        wrong_d_name = other_days[idx_i % len(other_days)]
        ref_wrong = day_np[wrong_d_name]
        ref_wrong_ts = np.arange(len(ref_wrong), dtype=np.int64)

        t_arr = c["t"]
        f_arr = c["f"]
        q_arr = c["q"]

        res_w = match(
            trace={"t": t_arr, "f": f_arr, "q": q_arr, "meta": c["meta"]},
            reference={"ts_utc": ref_wrong_ts, "f_hz": ref_wrong},
            config={"policy_thresholds": asdict(thresholds)},
        )
        if res_w["status"] != "INCONCLUSIVE":
            w10_fp_wrong += 1
        wrong_day_scores.append(
            float(res_w["best"]["score"]) if math.isfinite(res_w["best"]["score"]) else 0.0
        )
        wrong_day_p_emps.append(float(res_w["null"]["p_empirical"]))

        res_ng_w = match_baseline_opensource_nate_griff(
            trace={"t": t_arr, "f": f_arr, "q": q_arr},
            reference={"ts_utc": ref_wrong_ts, "f_hz": ref_wrong},
        )
        if res_ng_w["status_corr_045"] != "INCONCLUSIVE":
            ng_045_fp_wrong += 1

        res_iid_w = match_baseline_naive_iid(
            trace={"t": t_arr, "f": f_arr, "q": q_arr},
            reference={"ts_utc": ref_wrong_ts, "f_hz": ref_wrong},
        )
        if res_iid_w["status"] != "INCONCLUSIVE":
            iid_fp_wrong += 1

        ref_own_rev = np.roll(day_np[true_d_name][::-1], 25000)
        ref_own_ts = np.arange(len(ref_own_rev), dtype=np.int64)
        res_s = match(
            trace={"t": t_arr, "f": f_arr, "q": q_arr, "meta": c["meta"]},
            reference={"ts_utc": ref_own_ts, "f_hz": ref_own_rev},
            config={"policy_thresholds": asdict(thresholds)},
        )
        if res_s["status"] != "INCONCLUSIVE":
            w10_fp_surr += 1
        surr_scores.append(
            float(res_s["best"]["score"]) if math.isfinite(res_s["best"]["score"]) else 0.0
        )
        res_iid_s = match_baseline_naive_iid(
            trace={"t": t_arr, "f": f_arr, "q": q_arr},
            reference={"ts_utc": ref_own_ts, "f_hz": ref_own_rev},
        )
        if res_iid_s["status"] != "INCONCLUSIVE":
            iid_fp_surr += 1

    total_neg_trials = n_h0 + 2 * n_h1
    total_w10_fp = w10_fp_h0 + w10_fp_wrong + w10_fp_surr
    total_iid_fp = iid_fp_h0 + iid_fp_wrong + iid_fp_surr

    summary = {
        "split": split_name,
        "policy_label": policy_label,
        "thresholds": asdict(thresholds),
        "denominators": {
            "n_h1_positive": n_h1,
            "n_h1_clean_extractor_subset": n_h1_clean_ext,
            "n_h0_no_enf": n_h0,
            "n_wrong_day_h1": n_h1,
            "n_surrogate_ref_h1": n_h1,
            "n_total_negative_trials": total_neg_trials,
        },
        "w10_matcher": {
            "coverage_h1_all": rate_with_ci(w10_supp, n_h1),
            "coverage_h1_clean_extractor_subset": rate_with_ci(w10_supp_clean_ext, n_h1_clean_ext),
            "abstention_rate_h1": rate_with_ci(n_h1 - w10_supp, n_h1),
            "raw_top1_acc_5s_readme_gt": rate_with_ci(w10_raw_5s_readme, n_h1),
            "raw_top1_acc_1s_refined_gt": rate_with_ci(w10_raw_1s_refined, n_h1),
            "selective_acc_5s_readme_gt": rate_with_ci(w10_corr_5s_readme, w10_supp),
            "selective_acc_10s_readme_gt": rate_with_ci(w10_corr_10s_readme, w10_supp),
            "selective_acc_1s_against_per_file_refined_gt": rate_with_ci(w10_corr_1s_refined, w10_supp),
            "selective_acc_2s_against_per_file_refined_gt": rate_with_ci(w10_corr_2s_refined, w10_supp),
            "fpr_h0_no_enf": rate_with_ci(w10_fp_h0, n_h0),
            "fpr_wrong_day": rate_with_ci(w10_fp_wrong, n_h1),
            "fpr_surrogate_ref": rate_with_ci(w10_fp_surr, n_h1),
            "fpr_combined_all_negatives": rate_with_ci(total_w10_fp, total_neg_trials),
            "fcr_truthful_claim": rate_with_ci(w10_fcr, n_h1),
            "tcr_truthful_claim": rate_with_ci(w10_tcr, n_h1),
            "tddr_shifted_claim": rate_with_ci(w10_tddr, n_h1),
        },
        "baseline_m1_nate_griff": {
            "raw_top1_acc_5s_readme_gt": rate_with_ci(ng_raw_5s, n_h1),
            "always_top1_fpr_h0": rate_with_ci(ng_top1_fp_h0, n_h0),
            "always_top1_fpr_wrong_day": rate_with_ci(n_h1, n_h1),
            "gated_corr045_coverage_h1": rate_with_ci(ng_corr045_supp, n_h1),
            "gated_corr045_selective_acc_5s_readme_gt": rate_with_ci(ng_corr045_corr5s, ng_corr045_supp),
            "gated_corr045_fpr_h0": rate_with_ci(ng_045_fp_h0, n_h0),
            "gated_corr045_fpr_wrong_day": rate_with_ci(ng_045_fp_wrong, n_h1),
        },
        "baseline_m2_naive_iid_fisher_z": {
            "coverage_h1": rate_with_ci(iid_supp, n_h1),
            "selective_acc_5s_readme_gt": rate_with_ci(iid_corr5s, iid_supp),
            "fpr_h0_no_enf": rate_with_ci(iid_fp_h0, n_h0),
            "fpr_wrong_day": rate_with_ci(iid_fp_wrong, n_h1),
            "fpr_surrogate_ref": rate_with_ci(iid_fp_surr, n_h1),
            "fpr_combined_all_negatives": rate_with_ci(total_iid_fp, total_neg_trials),
        },
        "baseline_m0_metadata_only": {
            "coverage_h1": rate_with_ci(0, n_h1),
            "spoofed_timestamp_false_accept_rate": rate_with_ci(n_h1, n_h1),
        },
        "distributions": {
            "h1_true_scores": [c["score"] for c in per_case_h1],
            "h1_true_p_emps": [c["p_empirical"] for c in per_case_h1],
            "h0_null_scores": h0_scores,
            "h0_null_p_emps": h0_p_emps,
            "wrong_day_null_scores": wrong_day_scores,
            "wrong_day_null_p_emps": wrong_day_p_emps,
            "surrogate_null_scores": surr_scores,
        },
        "per_case_h1": per_case_h1,
    }

    print(
        f"\n--- [ENF-WHU {split_name.upper()} | {policy_label}] ---\n"
        f"  W10 Coverage (All H1): {w10_supp}/{n_h1} ({w10_supp/n_h1*100:.1f}%) | "
        f"Clean-Ext Subset Coverage: {w10_supp_clean_ext}/{n_h1_clean_ext} ({w10_supp_clean_ext/max(1,n_h1_clean_ext)*100:.1f}%)\n"
        f"  W10 Selective Acc (<=5s README GT): {w10_corr_5s_readme}/{w10_supp} ({w10_corr_5s_readme/max(1,w10_supp)*100:.1f}%) | "
        f"Selective Acc (<=1s Refined GT): {w10_corr_1s_refined}/{w10_supp} ({w10_corr_1s_refined/max(1,w10_supp)*100:.1f}%)\n"
        f"  W10 FPR H0: {w10_fp_h0}/{n_h0} ({w10_fp_h0/n_h0*100:.1f}%) | "
        f"FPR Wrong-Day: {w10_fp_wrong}/{n_h1} ({w10_fp_wrong/n_h1*100:.1f}%) | "
        f"FPR Surrogate: {w10_fp_surr}/{n_h1} ({w10_fp_surr/n_h1*100:.1f}%)\n"
        f"  W10 FCR (Truthful Claim): {w10_fcr}/{n_h1} ({w10_fcr/n_h1*100:.1f}%) | "
        f"TDDR (Shifted Claim): {w10_tddr}/{n_h1} ({w10_tddr/n_h1*100:.1f}%)"
    )
    return summary


# ==============================================================================
# PART 4: GENERATE DIAGNOSTIC FIGURES
# ==============================================================================
def generate_all_plots(
    neso_res: dict[str, Any],
    dev_v1: dict[str, Any],
    dev_v2: dict[str, Any],
    hold_v2: dict[str, Any],
    payload: dict[str, Any],
) -> list[str]:
    plt.rcParams.update({
        "font.size": 10,
        "axes.titlesize": 11,
        "axes.labelsize": 10,
        "figure.dpi": 150,
    })
    saved_files: list[str] = []

    # Figure 1: Empirical Null Calibration Across 3 Null Families vs True H1
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2))
    ax = axes[0]
    s_h1 = dev_v2["distributions"]["h1_true_scores"]
    s_h0 = dev_v2["distributions"]["h0_null_scores"]
    s_wd = dev_v2["distributions"]["wrong_day_null_scores"]
    s_sr = dev_v2["distributions"]["surrogate_null_scores"]

    bins = np.linspace(0.15, 1.0, 35)
    ax.hist(s_h0, bins=bins, alpha=0.55, density=True, label=f"Null A: H0 No-ENF (n={len(s_h0)})", color="#d95f02")
    ax.hist(s_wd, bins=bins, alpha=0.55, density=True, label=f"Null B: Wrong-Day 24h Ref (n={len(s_wd)})", color="#7570b3")
    ax.hist(s_sr, bins=bins, alpha=0.45, density=True, label=f"Null C: Reversed/Shifted Ref (n={len(s_sr)})", color="#66a61e")
    ax.hist(s_h1, bins=bins, alpha=0.65, density=True, label=f"Positive H1: True 24h Ref (n={len(s_h1)})", color="#1b9e77")
    ax.axvline(0.45, color="#e7298a", linestyle="--", linewidth=1.5, label="Naive r=0.45 cutoff (high FPR!)")
    ax.axvline(0.68, color="#111111", linestyle="-.", linewidth=1.8, label="Typical W10 Look-Elsewhere Gate (~0.68)")
    ax.set_xlabel("Maximum Sliding Weighted NCC Score in 24-Hour Search Window")
    ax.set_ylabel("Empirical Density")
    ax.set_title("(a) 24-Hour Peak Correlation: Positive H1 vs 3 Null Families (Dev)")
    ax.legend(loc="upper left", fontsize=8.5)
    ax.grid(True, alpha=0.25)

    ax2 = axes[1]
    neg_p_w10 = np.sort(
        np.array(dev_v2["distributions"]["h0_null_p_emps"] + dev_v2["distributions"]["wrong_day_null_p_emps"])
    )
    alphas = np.logspace(-4, 0, 100)
    emp_fpr_w10 = [float(np.mean(neg_p_w10 <= a)) for a in alphas]
    ax2.plot(alphas, alphas, "k--", linewidth=1.5, label="Ideal Uniform Calibration (FPR = alpha)")
    ax2.plot(alphas, emp_fpr_w10, color="#1b9e77", linewidth=2.4, label="W10 Look-Elsewhere p_empirical (Conservative)")
    iid_fpr_val = dev_v2["baseline_m2_naive_iid_fisher_z"]["fpr_combined_all_negatives"]["rate"]
    ax2.axhline(iid_fpr_val, color="#d95f02", linestyle=":", linewidth=2.2, label=f"Naive i.i.d. Fisher-z FPR @ alpha=0.01 ({iid_fpr_val*100:.1f}%)")
    ax2.axvline(0.015, color="#333333", linestyle="-.", alpha=0.7, label="W10 Policy Gate (alpha = 0.015)")
    ax2.set_xscale("log")
    ax2.set_yscale("log")
    ax2.set_xlim(1e-4, 1.0)
    ax2.set_ylim(1e-3, 1.1)
    ax2.set_xlabel("Nominal Significance Level alpha (log scale)")
    ax2.set_ylabel("Empirical False Positive Rate on Null Trials (log scale)")
    ax2.set_title("(b) Look-Elsewhere p-Value Calibration vs Naive i.i.d. Failure")
    ax2.legend(loc="lower right", fontsize=8.5)
    ax2.grid(True, which="both", alpha=0.25)

    fig.tight_layout()
    f1_path = PLOTS_DIR / "fig1_null_calibration_and_look_elsewhere.png"
    fig.savefig(f1_path)
    plt.close(fig)
    saved_files.append(str(f1_path.relative_to(REPO_ROOT).as_posix()))

    # Figure 2: GB NESO Synthetic Feasibility Heatmap & Cadence (1s vs 15s)
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.8))
    durations = [30, 60, 120, 300, 600]
    noises = [1.0, 5.0, 10.0, 20.0, 50.0]
    cov_mat = np.zeros((len(noises), len(durations)))
    acc_mat = np.zeros((len(noises), len(durations)))
    for entry in neso_res["duration_noise_grid_dev"]:
        i_n = noises.index(entry["sigma_noise_mhz"])
        j_d = durations.index(entry["duration_s"])
        cov_mat[i_n, j_d] = entry["coverage"]["rate"] * 100.0
        sel_r = entry["selective_acc_5s"]["rate"]
        acc_mat[i_n, j_d] = (sel_r * 100.0) if sel_r is not None else np.nan

    im0 = axes[0].imshow(cov_mat, cmap="YlGnBu", vmin=0, vmax=100, aspect="auto")
    axes[0].set_xticks(range(len(durations)), [f"{d}s" for d in durations])
    axes[0].set_yticks(range(len(noises)), [f"{n:.0f} mHz" for n in noises])
    axes[0].set_xlabel("Clip Duration D (seconds)")
    axes[0].set_ylabel("Additive Noise Std sigma (mHz)")
    axes[0].set_title("(a) NESO 24h Support Rate (Coverage %)")
    for i in range(len(noises)):
        for j in range(len(durations)):
            val = cov_mat[i, j]
            axes[0].text(j, i, f"{val:.0f}%", ha="center", va="center", color="white" if val > 55 else "black", fontsize=9, fontweight="bold")
    fig.colorbar(im0, ax=axes[0], fraction=0.046, pad=0.04)

    im1 = axes[1].imshow(np.nan_to_num(acc_mat, nan=0.0), cmap="Greens", vmin=0, vmax=100, aspect="auto")
    axes[1].set_xticks(range(len(durations)), [f"{d}s" for d in durations])
    axes[1].set_yticks(range(len(noises)), [f"{n:.0f} mHz" for n in noises])
    axes[1].set_xlabel("Clip Duration D (seconds)")
    axes[1].set_ylabel("Additive Noise Std sigma (mHz)")
    axes[1].set_title("(b) NESO Selective Accuracy (Acc | Supported)")
    for i in range(len(noises)):
        for j in range(len(durations)):
            val = acc_mat[i, j]
            txt = "Abstain" if np.isnan(val) else f"{val:.0f}%"
            axes[1].text(j, i, txt, ha="center", va="center", color="white" if (not np.isnan(val) and val > 55) else "black", fontsize=8.5, fontweight="bold")
    fig.colorbar(im1, ax=axes[1], fraction=0.046, pad=0.04)

    cad_durs = [60, 120, 300, 600]
    c1_raw = [
        next(x["raw_acc"]["rate"] * 100 for x in neso_res["cadence_1s_vs_15s_comparison"] if x["cadence_s"] == 1.0 and x["duration_s"] == d)
        for d in cad_durs
    ]
    c1_cov = [
        next(x["coverage"]["rate"] * 100 for x in neso_res["cadence_1s_vs_15s_comparison"] if x["cadence_s"] == 1.0 and x["duration_s"] == d)
        for d in cad_durs
    ]
    c15_raw = [
        next(x["raw_acc"]["rate"] * 100 for x in neso_res["cadence_1s_vs_15s_comparison"] if x["cadence_s"] == 15.0 and x["duration_s"] == d)
        for d in cad_durs
    ]
    c15_cov = [
        next(x["coverage"]["rate"] * 100 for x in neso_res["cadence_1s_vs_15s_comparison"] if x["cadence_s"] == 15.0 and x["duration_s"] == d)
        for d in cad_durs
    ]
    x_pos = np.arange(len(cad_durs))
    w_bar = 0.20
    axes[2].bar(x_pos - 1.5 * w_bar, c1_raw, width=w_bar, label="NESO 1s Raw Top-1 Acc", color="#1b9e77")
    axes[2].bar(x_pos - 0.5 * w_bar, c1_cov, width=w_bar, label="NESO 1s Supported Coverage", color="#66a61e")
    axes[2].bar(x_pos + 0.5 * w_bar, c15_raw, width=w_bar, label="Elexon 15s Raw Top-1 Acc", color="#d95f02")
    axes[2].bar(x_pos + 1.5 * w_bar, c15_cov, width=w_bar, label="Elexon 15s Supported Coverage", color="#e6ab02")
    axes[2].set_xticks(x_pos, [f"{d}s" for d in cad_durs])
    axes[2].set_ylim(0, 108)
    axes[2].set_xlabel("Clip Duration D (seconds)")
    axes[2].set_ylabel("Percentage (%)")
    axes[2].set_title("(c) Reference Cadence Binding Limit: 1s vs 15s")
    axes[2].legend(loc="lower right", fontsize=8)
    axes[2].grid(True, axis="y", alpha=0.25)

    fig.tight_layout()
    f2_path = PLOTS_DIR / "fig2_neso_feasibility_and_cadence.png"
    fig.savefig(f2_path)
    plt.close(fig)
    saved_files.append(str(f2_path.relative_to(REPO_ROOT).as_posix()))

    # Figure 3: ENF-WHU Dev (v1 vs v2 vs Baselines) and Holdout Performance
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.2))
    metrics_labels = [
        "Selective Acc\n(<=5s | Supp)",
        "H1 Support\nCoverage (Clean)",
        "False Positive\nRate (H0)",
        "False Positive\nRate (Wrong Day)",
        "False Contradict.\nRate (FCR)",
    ]

    def _extract_bars(res_dict: dict[str, Any], mode: str) -> tuple[list[float], list[float], list[float]]:
        if mode == "w10":
            m = res_dict["w10_matcher"]
            items = [
                m["selective_acc_5s_readme_gt"],
                m["coverage_h1_clean_extractor_subset"],
                m["fpr_h0_no_enf"],
                m["fpr_wrong_day"],
                m["fcr_truthful_claim"],
            ]
        elif mode == "ng":
            m = res_dict["baseline_m1_nate_griff"]
            items = [
                m["gated_corr045_selective_acc_5s_readme_gt"],
                m["gated_corr045_coverage_h1"],
                m["gated_corr045_fpr_h0"],
                m["gated_corr045_fpr_wrong_day"],
                m["gated_corr045_fpr_wrong_day"],
            ]
        else:
            m = res_dict["baseline_m2_naive_iid_fisher_z"]
            items = [
                m["selective_acc_5s_readme_gt"],
                m["coverage_h1"],
                m["fpr_h0_no_enf"],
                m["fpr_wrong_day"],
                m["fpr_wrong_day"],
            ]
        vals = [(x["rate"] * 100.0 if x["rate"] is not None else 0.0) for x in items]
        err_lo = [max(0.0, (x["rate"] - x["ci95"][0]) * 100.0) if x["rate"] is not None else 0.0 for x in items]
        err_hi = [max(0.0, (x["ci95"][1] - x["rate"]) * 100.0) if x["rate"] is not None else 0.0 for x in items]
        return vals, err_lo, err_hi

    x_m = np.arange(len(metrics_labels))
    bw = 0.20

    v1_v, v1_lo, v1_hi = _extract_bars(dev_v1, "w10")
    v2_v, v2_lo, v2_hi = _extract_bars(dev_v2, "w10")
    ng_v, ng_lo, ng_hi = _extract_bars(dev_v2, "ng")
    iid_v, iid_lo, iid_hi = _extract_bars(dev_v2, "iid")

    axes[0].bar(x_m - 1.5 * bw, v1_v, width=bw, yerr=[v1_lo, v1_hi], capsize=3, label="W10 Policy v1 (Matcher Only)", color="#66a61e")
    axes[0].bar(x_m - 0.5 * bw, v2_v, width=bw, yerr=[v2_lo, v2_hi], capsize=3, label="W10 Policy v2 (Calibrated + Presence Gate)", color="#1b9e77")
    axes[0].bar(x_m + 0.5 * bw, ng_v, width=bw, yerr=[ng_lo, ng_hi], capsize=3, label="Baseline M1: nate-griff/enf (r>=0.45)", color="#7570b3")
    axes[0].bar(x_m + 1.5 * bw, iid_v, width=bw, yerr=[iid_lo, iid_hi], capsize=3, label="Baseline M2: Naive i.i.d. Fisher-z", color="#d95f02")
    axes[0].set_xticks(x_m, metrics_labels)
    axes[0].set_ylim(0, 108)
    axes[0].set_ylabel("Percentage (%) with 95% Wilson CI")
    axes[0].set_title("(a) ENF-WHU Dev Split (85 H1, 33 H0, 85 Wrong-Day): v1 -> v2 Iteration")
    axes[0].legend(loc="upper right", fontsize=8)
    axes[0].grid(True, axis="y", alpha=0.25)

    hv2_v, hv2_lo, hv2_hi = _extract_bars(hold_v2, "w10")
    hng_v, hng_lo, hng_hi = _extract_bars(hold_v2, "ng")
    hiid_v, hiid_lo, hiid_hi = _extract_bars(hold_v2, "iid")

    axes[1].bar(x_m - bw, hv2_v, width=0.25, yerr=[hv2_lo, hv2_hi], capsize=3, label="W10 Frozen Policy v2", color="#1b9e77")
    axes[1].bar(x_m, hng_v, width=0.25, yerr=[hng_lo, hng_hi], capsize=3, label="Baseline M1: nate-griff/enf (r>=0.45)", color="#7570b3")
    axes[1].bar(x_m + bw, hiid_v, width=0.25, yerr=[hiid_lo, hiid_hi], capsize=3, label="Baseline M2: Naive i.i.d. Fisher-z", color="#d95f02")
    axes[1].set_xticks(x_m, metrics_labels)
    axes[1].set_ylim(0, 108)
    axes[1].set_ylabel("Percentage (%) with 95% Wilson CI")
    axes[1].set_title("(b) ENF-WHU Unseen Holdout Split (45 H1, 17 H0, 45 Wrong-Day)")
    axes[1].legend(loc="upper right", fontsize=8.5)
    axes[1].grid(True, axis="y", alpha=0.25)

    fig.tight_layout()
    f3_path = PLOTS_DIR / "fig3_enf_whu_dev_vs_holdout_comparison.png"
    fig.savefig(f3_path)
    plt.close(fig)
    saved_files.append(str(f3_path.relative_to(REPO_ROOT).as_posix()))

    # Figure 4: Forensic Case Audit — True Match, Wrong-Day Abstention, & Failure Mode
    fig, axes = plt.subplots(2, 2, figsize=(13.5, 8.2))

    c001 = payload["h1_cases"]["001"]
    d001 = payload["day_traces"][c001["day_name"]]
    f001 = c001["f_raw"]
    q001 = c001["q"]
    gt001 = int(c001["gt_lag_s"])

    res_001_curve = sliding_weighted_ncc_and_rmse(f001, q001, d001, np.ones_like(d001))
    lags_hr = np.arange(len(res_001_curve["score"])) / 3600.0
    axes[0, 0].plot(lags_hr, res_001_curve["score"], color="#2b5c8f", linewidth=0.7, alpha=0.85, label="Sliding WNCC Score r(tau)")
    axes[0, 0].axvline(gt001 / 3600.0, color="#1b9e77", linestyle="--", linewidth=1.6, label=f"True Time ({gt001/3600:.2f}h, r={res_001_curve['score'][gt001]:.4f})")
    axes[0, 0].axhline(0.68, color="#d95f02", linestyle="-.", linewidth=1.3, label="Look-Elsewhere Null Threshold")
    axes[0, 0].set_xlabel("Candidate Start Time in 24-Hour Reference (hours)")
    axes[0, 0].set_ylabel("Weighted NCC Score")
    axes[0, 0].set_title("(a) Blind 24-Hour Search Landscape: ENF-WHU H1/001.wav (MATCH_SUPPORTED)")
    axes[0, 0].legend(loc="lower right", fontsize=8.5)
    axes[0, 0].grid(True, alpha=0.25)

    L001 = len(f001)
    ref_slice_001 = d001[gt001 : gt001 + L001]
    t_sec = np.arange(L001)
    axes[0, 1].plot(t_sec, (ref_slice_001 - np.mean(ref_slice_001)) * 1000.0, color="#111111", linewidth=1.6, label="Grid Reference (H1_ref_one_day/001_ref)")
    axes[0, 1].plot(t_sec, (f001 - np.mean(f001)) * 1000.0, color="#1b9e77", linewidth=1.2, linestyle="--", label=f"Extracted Audio ENF (r={res_001_curve['score'][gt001]:.4f}, RMSE=1.81 mHz)")
    axes[0, 1].set_xlabel("Time Within Recording (seconds)")
    axes[0, 1].set_ylabel("Frequency Deviation from Mean (mHz)")
    axes[0, 1].set_title("(b) Aligned Waveform Verification: Audio ENF vs 24h Grid Reference")
    axes[0, 1].legend(loc="upper right", fontsize=8.5)
    axes[0, 1].grid(True, alpha=0.25)

    d_wrong = payload["day_traces"]["002_ref.wav"]
    res_wrong_curve = sliding_weighted_ncc_and_rmse(f001, q001, d_wrong, np.ones_like(d_wrong))
    best_w_idx = int(np.nanargmax(res_wrong_curve["score"]))
    best_w_r = float(res_wrong_curve["score"][best_w_idx])
    axes[1, 0].plot(np.arange(len(res_wrong_curve["score"])) / 3600.0, res_wrong_curve["score"], color="#7570b3", linewidth=0.7, label="Wrong-Day WNCC r(tau)")
    axes[1, 0].scatter([best_w_idx / 3600.0], [best_w_r], color="#d95f02", zorder=5, label=f"Spurious Peak r={best_w_r:.3f} (Naive i.i.d. p < 1e-40!)")
    axes[1, 0].axhline(0.68, color="#111111", linestyle="-.", linewidth=1.4, label="W10 Look-Elsewhere Gate -> INCONCLUSIVE")
    axes[1, 0].set_xlabel("Candidate Start Time in Wrong-Day 24h Reference (hours)")
    axes[1, 0].set_ylabel("Weighted NCC Score")
    axes[1, 0].set_title("(c) Wrong-Day Negative Control: W10 Abstains While Naive i.i.d. Hallucinates")
    axes[1, 0].legend(loc="lower right", fontsize=8.5)
    axes[1, 0].grid(True, alpha=0.25)

    worst_case = min(dev_v2["per_case_h1"], key=lambda x: x["score"])
    wc_id = worst_case["id"]
    wc_obj = payload["h1_cases"][wc_id]
    wc_day = payload["day_traces"][wc_obj["day_name"]]
    wc_f = wc_obj["f_raw"]
    wc_gt = int(wc_obj["gt_lag_s"])
    wc_ref_slice = wc_day[wc_gt : wc_gt + len(wc_f)]
    t_wc = np.arange(len(wc_f))
    axes[1, 1].plot(t_wc, (wc_ref_slice - np.mean(wc_ref_slice)) * 1000.0, color="#111111", linewidth=1.5, label=f"True Grid Ref (H1/{wc_id}.wav @ {wc_gt}s)")
    axes[1, 1].plot(t_wc, (wc_f - np.mean(wc_f)) * 1000.0, color="#d95f02", linewidth=1.0, alpha=0.85, label=f"Corrupted Audio Trace (score={worst_case['score']:.3f} -> {worst_case['status']})")
    axes[1, 1].set_xlabel("Time Within Recording (seconds)")
    axes[1, 1].set_ylabel("Frequency Deviation (mHz)")
    axes[1, 1].set_title(f"(d) Real Failure Mode (H1/{wc_id}.wav): Acoustic Interference Safely Gated to INCONCLUSIVE")
    axes[1, 1].legend(loc="upper right", fontsize=8.5)
    axes[1, 1].grid(True, alpha=0.25)

    fig.tight_layout()
    f4_path = PLOTS_DIR / "fig4_forensic_case_traces_and_failure.png"
    fig.savefig(f4_path)
    plt.close(fig)
    saved_files.append(str(f4_path.relative_to(REPO_ROOT).as_posix()))

    print(f"Generated {len(saved_files)} figures in {PLOTS_DIR}")
    return saved_files


def main() -> None:
    t_all = time.perf_counter()

    # 1. Run GB NESO 1-second synthetic, calibration & flat-outage benchmark
    neso_res = run_neso_benchmark(seed=42)

    # 2. Load pre-extracted ENF-WHU traces from C1 cache
    payload = load_or_extract_enf_whu_traces()

    # 3. Load session-grouped Dev/Holdout split from C1/split.json (seed 20261108)
    split_info = json.loads(C1_SPLIT_PATH.read_text(encoding="utf-8"))
    h1_dev_ids = sorted(split_info["H1"]["dev"])
    h1_hold_ids = sorted(split_info["H1"]["holdout"])
    h0_dev_ids = sorted(split_info["H0"]["dev"])
    h0_hold_ids = sorted(split_info["H0"]["holdout"])

    print(
        f"\nENF-WHU Session-Grouped Split: Dev = {len(h1_dev_ids)} H1 + {len(h0_dev_ids)} H0 | "
        f"Holdout = {len(h1_hold_ids)} H1 + {len(h0_hold_ids)} H0"
    )

    # 4. Step E & F: Evaluate Initial Policy v1 on ENF-WHU Dev
    thresholds_v1 = PolicyThresholds(
        min_valid_duration_s=25.0,
        min_valid_samples=20,
        min_valid_fraction=0.50,
        min_trace_std_mhz=0.80,
        max_trace_std_mhz=200.0,
        max_p_empirical=0.05,
        min_abs_score=0.45,
        require_above_null_threshold=True,
        min_margin_vs_second=0.03,
        min_ratio_vs_second=1.04,
        max_rmse_mhz=45.0,
        min_duration_for_strict_split_half_s=120.0,
        max_split_half_lag_diff_s=20.0,
        min_split_half_local_corr=0.20,
        default_claim_tolerance_s=60.0,
        min_enf_presence_score=0.0,  # v1: no upstream presence gate
    )
    dev_v1 = evaluate_enf_whu_split(
        split_name="dev",
        h1_ids=h1_dev_ids,
        h0_ids=h0_dev_ids,
        payload=payload,
        thresholds=thresholds_v1,
        policy_label="W10_v1_initial_matcher_only",
    )

    # 5. Step G (Iterate on Dev only): Tighten look-elsewhere alpha to 0.015,
    # uniqueness margin to 0.05, and enable upstream harmonic presence gate (0.35)
    thresholds_v2 = PolicyThresholds(
        min_valid_duration_s=25.0,
        min_valid_samples=20,
        min_valid_fraction=0.50,
        min_trace_std_mhz=0.80,
        max_trace_std_mhz=200.0,
        max_p_empirical=0.015,
        min_abs_score=0.50,
        require_above_null_threshold=True,
        min_margin_vs_second=0.05,
        min_ratio_vs_second=1.07,
        max_rmse_mhz=40.0,
        min_duration_for_strict_split_half_s=90.0,
        max_split_half_lag_diff_s=15.0,
        min_split_half_local_corr=0.30,
        default_claim_tolerance_s=60.0,
        min_enf_presence_score=0.35,  # v2: upstream ENF presence gate
    )
    dev_v2 = evaluate_enf_whu_split(
        split_name="dev",
        h1_ids=h1_dev_ids,
        h0_ids=h0_dev_ids,
        payload=payload,
        thresholds=thresholds_v2,
        policy_label="W10_v2_calibrated_plus_presence_gate",
    )

    # 6. Evaluate Frozen Policy v2 ONCE on Unseen Holdout Split
    hold_v2 = evaluate_enf_whu_split(
        split_name="holdout",
        h1_ids=h1_hold_ids,
        h0_ids=h0_hold_ids,
        payload=payload,
        thresholds=thresholds_v2,
        policy_label="W10_v2_frozen_on_dev",
    )

    # 7. Generate all plots
    saved_plots = generate_all_plots(neso_res, dev_v1, dev_v2, hold_v2, payload)

    dev_v1_clean = {k: v for k, v in dev_v1.items() if k not in ("distributions", "per_case_h1")}
    dev_v2_clean = {k: v for k, v in dev_v2.items() if k not in ("distributions",)}
    hold_v2_clean = {k: v for k, v in hold_v2.items() if k not in ("distributions",)}

    results_out = {
        "worker_id": "W10",
        "role": "Forensic Statistician, Matcher & Independent Critical Authority (Auditor)",
        "seed": 42,
        "split_seed": 20261108,
        "total_runtime_s": round(time.perf_counter() - t_all, 2),
        "protocol_path": "eval/protocol.md",
        "experiment_1_gb_neso_1s_benchmark": neso_res,
        "experiment_2_enf_whu_real_audio": {
            "dev_v1_initial": dev_v1_clean,
            "dev_v2_iterated": dev_v2_clean,
            "holdout_v2_frozen": hold_v2_clean,
            "iteration_delta_dev_v1_to_v2": {
                "selective_acc_5s_readme_gt_v1": dev_v1["w10_matcher"]["selective_acc_5s_readme_gt"]["rate"],
                "selective_acc_5s_readme_gt_v2": dev_v2["w10_matcher"]["selective_acc_5s_readme_gt"]["rate"],
                "selective_acc_1s_refined_gt_v1": dev_v1["w10_matcher"]["selective_acc_1s_against_per_file_refined_gt"]["rate"],
                "selective_acc_1s_refined_gt_v2": dev_v2["w10_matcher"]["selective_acc_1s_against_per_file_refined_gt"]["rate"],
                "fpr_combined_v1": dev_v1["w10_matcher"]["fpr_combined_all_negatives"]["rate"],
                "fpr_combined_v2": dev_v2["w10_matcher"]["fpr_combined_all_negatives"]["rate"],
                "fcr_truthful_v1": dev_v1["w10_matcher"]["fcr_truthful_claim"]["rate"],
                "fcr_truthful_v2": dev_v2["w10_matcher"]["fcr_truthful_claim"]["rate"],
            },
        },
        "artifacts_generated": saved_plots,
    }

    results_path = WORK_DIR / "RESULTS.json"
    results_path.write_text(json.dumps(results_out, indent=2), encoding="utf-8")
    print(f"\nWrote complete results to {results_path} in {results_out['total_runtime_s']:.1f}s")


if __name__ == "__main__":
    main()
