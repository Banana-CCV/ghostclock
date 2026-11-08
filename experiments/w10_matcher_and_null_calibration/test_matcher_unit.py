"""
work/W10/test_matcher_unit.py — Unit & Smoke Verification for W10 Matcher & Policy
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from work.W10.matcher import (
    match,
    match_baseline_naive_iid,
    match_baseline_opensource_nate_griff,
)
from work.W10.policy import evaluate_policy


def run_unit_tests() -> None:
    neso_dev_path = REPO_ROOT / "work" / "W11" / "data" / "fnew-2026-8.parquet"
    df_neso = pd.read_parquet(neso_dev_path)
    print(f"Loaded NESO Aug 2026 dev reference: {len(df_neso)} samples")

    # Slice a 24-hour window (86,400 s) from Day 5 of Aug 2026
    day5_start = int(df_neso["ts_utc"].iloc[0]) + 4 * 86400
    day5_end = day5_start + 86400 - 1
    ref_day5 = df_neso[(df_neso["ts_utc"] >= day5_start) & (df_neso["ts_utc"] <= day5_end)].reset_index(drop=True)

    # 1. Test clean + noisy 300s synthetic trace with +3.5 mHz crystal offset and 25% NaN holes
    rng = np.random.default_rng(101)
    true_offset_s = 34567
    true_start_utc = day5_start + true_offset_s
    dur_s = 300
    t_trace = np.arange(dur_s, dtype=np.float64)
    f_true = ref_day5["f_hz"].to_numpy(dtype=np.float64)[true_offset_s : true_offset_s + dur_s]

    # Add +3.5 mHz DC offset and 5 mHz Gaussian noise
    f_noisy = f_true + 0.0035 + rng.normal(0.0, 0.005, size=dur_s)
    q_trace = np.ones(dur_s, dtype=np.float64)

    # Inject a 40-second contiguous NaN gap in the middle (indices 120..160)
    f_noisy[120:160] = np.nan
    q_trace[120:160] = 0.0

    t0 = time.perf_counter()
    res = match(
        trace={"t": t_trace, "f": f_noisy, "q": q_trace},
        reference=ref_day5,
        search_start_utc=day5_start,
        search_end_utc=day5_end,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    err_s = res["best"]["start_utc"] - true_start_utc
    print(
        f"[Test 1: 300s + 5mHz noise + 40s NaN gap + 3.5mHz offset] "
        f"time={elapsed_ms:.1f}ms | status={res['status']} | err_s={err_s} | "
        f"score={res['best']['score']:.4f} | rmse_mhz={res['best']['rmse_mhz']:.2f} | "
        f"offset_hz={res['best']['offset_hz']*1000:.2f}mHz | p_emp={res['null']['p_empirical']:.4g}"
    )
    assert abs(err_s) <= 2, f"Expected |err_s| <= 2, got {err_s}"
    assert res["status"] == "MATCH_SUPPORTED", f"Expected MATCH_SUPPORTED, got {res['status']}"

    # Compare nate-griff on the exact same trace with 40s interior NaN gap!
    res_ng = match_baseline_opensource_nate_griff(
        trace={"t": t_trace, "f": f_noisy, "q": q_trace},
        reference=ref_day5,
        search_start_utc=day5_start,
        search_end_utc=day5_end,
    )
    err_ng = res_ng["best"]["start_utc"] - true_start_utc
    print(
        f"[Test 1b: nate-griff on same trace with 40s NaN gap] "
        f"err_s={err_ng}s | corr={res_ng['best']['corr']:.4f} | comp_score={res_ng['best']['score']:.4f}"
    )

    # 2. Test Clock-Drift Search (+0.20% speed drift = +2000 ppm over 300s -> 0.6s shift)
    # Over 600s, +0.30% drift shifts alignment by 1.8s!
    dur_drift = 600
    true_drift = 0.003  # +0.3% clock rate error
    t_orig = np.arange(dur_drift, dtype=np.float64)
    # True grid times sampled by a drifted clock: t_grid = t_orig / (1 + true_drift)
    f_ref_all = ref_day5["f_hz"].to_numpy(dtype=np.float64)
    t_grid_rel = np.arange(len(f_ref_all), dtype=np.float64)
    f_drifted = np.interp(
        true_offset_s + t_orig * (1.0 - true_drift),
        t_grid_rel,
        f_ref_all,
    ) + rng.normal(0.0, 0.003, size=dur_drift)

    res_no_drift = match(
        trace={"t": t_orig, "f": f_drifted, "q": np.ones(dur_drift)},
        reference=ref_day5,
        search_start_utc=day5_start,
        search_end_utc=day5_end,
        config={"clock_drift_search": False},
    )
    res_with_drift = match(
        trace={"t": t_orig, "f": f_drifted, "q": np.ones(dur_drift)},
        reference=ref_day5,
        search_start_utc=day5_start,
        search_end_utc=day5_end,
        config={"clock_drift_search": True, "max_clock_drift": 0.005, "n_drift_steps": 21},
    )
    print(
        f"[Test 2: +0.30% Clock Drift (600s)] "
        f"no_drift: score={res_no_drift['best']['score']:.4f}, err={res_no_drift['best']['start_utc'] - true_start_utc}s | "
        f"with_drift: score={res_with_drift['best']['score']:.4f}, err={res_with_drift['best']['start_utc'] - true_start_utc}s, "
        f"est_drift={res_with_drift['diagnostics']['best_clock_drift_ppm']:.0f}ppm"
    )
    assert res_with_drift["best"]["score"] > res_no_drift["best"]["score"]
    assert abs(res_with_drift["best"]["start_utc"] - true_start_utc) <= 2

    # 3. Test Flat 50.000 Hz Tone (H0 / synthetic generator) -> MUST be INCONCLUSIVE
    f_flat = np.full(300, 50.0, dtype=np.float64) + rng.normal(0.0, 0.0001, size=300)
    res_flat = match(
        trace={"t": np.arange(300, dtype=np.float64), "f": f_flat, "q": np.ones(300)},
        reference=ref_day5,
        search_start_utc=day5_start,
        search_end_utc=day5_end,
    )
    print(f"[Test 3: Flat 50 Hz tone] status={res_flat['status']} | reasons={res_flat['status_reasons'][0]}")
    assert res_flat["status"] == "INCONCLUSIVE"

    # 4. Test Wrong-Day Negative Control (Day 5 trace matched against Day 12 reference)
    day12_start = int(df_neso["ts_utc"].iloc[0]) + 11 * 86400
    day12_end = day12_start + 86400 - 1
    ref_day12 = df_neso[(df_neso["ts_utc"] >= day12_start) & (df_neso["ts_utc"] <= day12_end)].reset_index(drop=True)
    res_wrong_day = match(
        trace={"t": t_trace, "f": f_noisy, "q": q_trace},
        reference=ref_day12,
        search_start_utc=day12_start,
        search_end_utc=day12_end,
    )
    res_wrong_iid = match_baseline_naive_iid(
        trace={"t": t_trace, "f": f_noisy, "q": q_trace},
        reference=ref_day12,
        search_start_utc=day12_start,
        search_end_utc=day12_end,
    )
    print(
        f"[Test 4: Wrong-Day Negative Control] "
        f"W10 status={res_wrong_day['status']} (score={res_wrong_day['best']['score']:.4f}, p_emp={res_wrong_day['null']['p_empirical']:.4g}) | "
        f"Naive i.i.d. status={res_wrong_iid['status']} (p_iid={res_wrong_iid['p_naive_iid']:.4g})"
    )
    assert res_wrong_day["status"] == "INCONCLUSIVE"

    # 5. Test Claim Verification Mode (Truthful vs Discrepant Claim)
    res_claim_true = evaluate_policy(
        dict(res), claimed_start_utc=true_start_utc, tolerance_s=60.0
    )
    res_claim_false = evaluate_policy(
        dict(res), claimed_start_utc=true_start_utc + 7200, tolerance_s=60.0
    )
    print(
        f"[Test 5: Claim Policy] truthful_claim -> {res_claim_true['status']} | "
        f"shifted_+2h_claim -> {res_claim_false['status']}"
    )
    assert res_claim_true["status"] == "MATCH_SUPPORTED"
    assert res_claim_false["status"] == "MATERIAL_DISCREPANCY_REVIEW"
    print("ALL UNIT TESTS PASSED!")


if __name__ == "__main__":
    run_unit_tests()
