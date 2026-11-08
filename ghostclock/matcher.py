"""
ghostclock/matcher.py (from work/W10/matcher.py) — Calibrated Forensic ENF Time-Series Matcher
Owner: W10 (Forensic Statistician & Independent Critical Authority)

Implements `match(trace, reference, search_start_utc, search_end_utc, config) -> dict`
strictly adhering to `integration/interfaces.md` §3:
  1. Resamples trace and reference to a common regular cadence (default 1.0 s).
  2. Preserves exact temporal indices of NaN / low-quality windows via quality weights
     w[k] in [0, 1] (never dropping interior NaN rows).
  3. Computes sliding Weighted Normalized Cross-Correlation (WNCC) and offset-adjusted
     Weighted RMSE (in mHz) across the entire search window in O(R log R) time using
     batch 1D real FFT convolutions on globally pre-centered deviations.
  4. Supports optional clock-rate / speed-drift search (+/-0.5%, i.e. +/-5000 ppm)
     while penalizing the effective number of trials M_eff for the extra hypotheses.
  5. Extracts top-K candidates via Non-Maximum Suppression (NMS) with parabolic
     sub-sample refinement and computes uniqueness margin vs the second-best peak.
  6. Evaluates split-half internal consistency (independent first-half vs second-half
     search agreement and local half correlations).
  7. Computes look-elsewhere calibrated p-values (`p_empirical`) and `score_threshold`
     combining Bartlett's autocorrelation-adjusted effective degrees of freedom (N_eff)
     with empirical time-reversed / circular-shift / phase-randomized reference nulls.
  8. Enforces deterministic decision gates via `work.W10.policy.evaluate_policy`.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Optional, Union

import numpy as np
import pandas as pd
from scipy import fft as sp_fft, signal, stats

# Script mode is supported via the try/except import below
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from .policy import PolicyThresholds, evaluate_policy
except ImportError:  # run as a script: python ghostclock/matcher.py
    from ghostclock.policy import PolicyThresholds, evaluate_policy


def _load_trace_input(
    trace: Union[str, Path, dict[str, Any], pd.DataFrame, np.ndarray],
    default_cadence_s: float = 1.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    """
    Normalize any supported `trace` input into `(t_s, f_hz, q, meta)`.
    Never reads wall-clock timestamps or filenames for dating.
    """
    meta: dict[str, Any] = {}
    if isinstance(trace, (str, Path)):
        p = Path(trace)
        if p.suffix == ".npz":
            with np.load(p, allow_pickle=False) as data:
                t = np.asarray(data["t"], dtype=np.float64)
                f = np.asarray(data["f"], dtype=np.float64)
                q = (
                    np.asarray(data["q"], dtype=np.float64)
                    if "q" in data
                    else np.where(np.isfinite(f), 1.0, 0.0)
                )
            json_sidecar = p.with_suffix(".json")
            if json_sidecar.exists():
                try:
                    meta = json.loads(json_sidecar.read_text(encoding="utf-8"))
                except Exception:
                    meta = {}
            return t, f, q, meta
        elif p.suffix in (".csv", ".parquet"):
            df = pd.read_parquet(p) if p.suffix == ".parquet" else pd.read_csv(p)
            return _load_trace_input(df, default_cadence_s=default_cadence_s)
        else:
            raise ValueError(f"Unsupported trace file extension: {p.suffix}")

    if isinstance(trace, pd.DataFrame):
        t_col = "t" if "t" in trace.columns else ("time_s" if "time_s" in trace.columns else None)
        f_col = "f" if "f" in trace.columns else ("f_hz" if "f_hz" in trace.columns else "enf")
        f = np.asarray(trace[f_col], dtype=np.float64)
        t = (
            np.asarray(trace[t_col], dtype=np.float64)
            if t_col is not None
            else np.arange(len(f), dtype=np.float64) * default_cadence_s
        )
        q = (
            np.asarray(trace["q"], dtype=np.float64)
            if "q" in trace.columns
            else np.where(np.isfinite(f), 1.0, 0.0)
        )
        return t, f, q, meta

    if isinstance(trace, np.ndarray):
        f = np.asarray(trace, dtype=np.float64).ravel()
        t = np.arange(len(f), dtype=np.float64) * default_cadence_s
        q = np.where(np.isfinite(f), 1.0, 0.0)
        return t, f, q, meta

    if isinstance(trace, dict) or hasattr(trace, "keys"):
        f_key = "f" if "f" in trace else ("f_hz" if "f_hz" in trace else "enf")
        f = np.asarray(trace[f_key], dtype=np.float64).ravel()
        t = (
            np.asarray(trace["t"], dtype=np.float64).ravel()
            if "t" in trace
            else np.arange(len(f), dtype=np.float64) * default_cadence_s
        )
        q = (
            np.asarray(trace["q"], dtype=np.float64).ravel()
            if "q" in trace
            else np.where(np.isfinite(f), 1.0, 0.0)
        )
        if "meta" in trace and isinstance(trace["meta"], dict):
            meta = dict(trace["meta"])
        return t, f, q, meta

    raise TypeError(f"Unsupported trace input type: {type(trace)}")


def _load_reference_input(
    reference: Union[str, Path, dict[str, Any], pd.DataFrame, np.ndarray],
    search_start_utc: Optional[int],
    default_cadence_s: float = 1.0,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """
    Normalize any supported `reference` input into `(ts_utc, f_hz, ref_meta)`.
    """
    ref_meta: dict[str, Any] = {}
    if isinstance(reference, (str, Path)):
        p = Path(reference)
        json_sidecar = p.with_suffix(".json")
        if json_sidecar.exists():
            try:
                ref_meta = json.loads(json_sidecar.read_text(encoding="utf-8"))
            except Exception:
                ref_meta = {}
        if p.suffix == ".parquet":
            df = pd.read_parquet(p)
        elif p.suffix == ".csv":
            df = pd.read_csv(p)
        elif p.suffix == ".npz":
            with np.load(p, allow_pickle=False) as data:
                f_hz = np.asarray(data["f_hz" if "f_hz" in data else "f"], dtype=np.float64)
                ts_utc = (
                    np.asarray(data["ts_utc" if "ts_utc" in data else "t"], dtype=np.float64)
                    if ("ts_utc" in data or "t" in data)
                    else np.arange(len(f_hz), dtype=np.float64) * default_cadence_s
                )
            return ts_utc, f_hz, ref_meta
        else:
            raise ValueError(f"Unsupported reference file extension: {p.suffix}")
        ts_out, f_out, _ = _load_reference_input(df, search_start_utc=search_start_utc, default_cadence_s=default_cadence_s)
        bad_intervals = ref_meta.get("bad_intervals", [])
        if isinstance(bad_intervals, list) and len(bad_intervals) > 0:
            f_out = f_out.copy()
            for iv in bad_intervals:
                if isinstance(iv, (list, tuple)) and len(iv) >= 2:
                    f_out[(ts_out >= float(iv[0])) & (ts_out <= float(iv[1]))] = np.nan
        return ts_out, f_out, ref_meta

    if isinstance(reference, pd.DataFrame):
        f_col = "f_hz" if "f_hz" in reference.columns else ("f" if "f" in reference.columns else "enf")
        f_hz = np.asarray(reference[f_col], dtype=np.float64).ravel()
        if "ts_utc" in reference.columns:
            ts_utc = np.asarray(reference["ts_utc"], dtype=np.float64).ravel()
        elif "t" in reference.columns:
            ts_utc = np.asarray(reference["t"], dtype=np.float64).ravel()
        else:
            start0 = float(search_start_utc if search_start_utc is not None else 0)
            ts_utc = start0 + np.arange(len(f_hz), dtype=np.float64) * default_cadence_s
        return ts_utc, f_hz, ref_meta

    if isinstance(reference, np.ndarray):
        f_hz = np.asarray(reference, dtype=np.float64).ravel()
        start0 = float(search_start_utc if search_start_utc is not None else 0)
        ts_utc = start0 + np.arange(len(f_hz), dtype=np.float64) * default_cadence_s
        return ts_utc, f_hz, ref_meta

    if isinstance(reference, dict) or hasattr(reference, "keys"):
        f_key = "f_hz" if "f_hz" in reference else ("f" if "f" in reference else "enf")
        f_hz = np.asarray(reference[f_key], dtype=np.float64).ravel()
        if "ts_utc" in reference:
            ts_utc = np.asarray(reference["ts_utc"], dtype=np.float64).ravel()
        elif "t" in reference:
            ts_utc = np.asarray(reference["t"], dtype=np.float64).ravel()
        else:
            start0 = float(search_start_utc if search_start_utc is not None else 0)
            ts_utc = start0 + np.arange(len(f_hz), dtype=np.float64) * default_cadence_s
        if "meta" in reference and isinstance(reference["meta"], dict):
            ref_meta = dict(reference["meta"])
        return ts_utc, f_hz, ref_meta

    raise TypeError(f"Unsupported reference input type: {type(reference)}")


def _mask_flat_runs(f_arr: np.ndarray, m_y: np.ndarray, min_flat_len: int = 15, eps: float = 1e-7) -> np.ndarray:
    """
    Detect and mask flat-filled sensor outages (runs of >= min_flat_len consecutive
    samples with |f[k] - f[k-1]| <= eps, such as the 2026-09-15 3.1h 49.895 Hz NESO outage).
    Sets m_y = 0.0 across the entire flat stretch so neither forward matching nor
    null sampling ever uses flat-filled outage intervals.
    """
    n = len(f_arr)
    if n < min_flat_len or min_flat_len < 2:
        return m_y
    same = (np.abs(np.diff(f_arr)) <= eps) & (m_y[:-1] > 0) & (m_y[1:] > 0)
    if not np.any(same):
        return m_y
    # Find run starts and ends in `same`
    padded = np.concatenate(([False], same, [False]))
    starts = np.where(padded[1:] & ~padded[:-1])[0]
    ends = np.where(~padded[1:] & padded[:-1])[0]
    run_lengths = ends - starts + 1  # number of identical samples in the run
    long_runs = np.where(run_lengths >= min_flat_len)[0]
    if len(long_runs) == 0:
        return m_y
    out_m = m_y.copy()
    for idx_r in long_runs:
        out_m[starts[idx_r] : ends[idx_r] + 1] = 0.0
    return out_m


def resample_reference_regular(
    ts_utc: np.ndarray,
    f_hz: np.ndarray,
    search_start_utc: Optional[int],
    search_end_utc: Optional[int],
    cadence_s: float = 1.0,
    max_interp_gap_s: float = 3.0,
    nominal_hz: float = 50.0,
    max_dev_hz: float = 1.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Resample/regularize the reference series onto a strict uniform grid
    `t_grid = start_utc + k * cadence_s` with validity mask `m_y` in {0.0, 1.0}.
    Gaps larger than `max_interp_gap_s` and flat-filled outages (>= 15 constant samples)
    are masked as 0.0 and never bridged or matched.
    """
    if len(ts_utc) == 0:
        return np.array([], dtype=np.float64), np.array([], dtype=np.float64), np.array([], dtype=np.float64)

    # Sort if needed
    if len(ts_utc) > 1 and np.any(np.diff(ts_utc) < 0):
        order = np.argsort(ts_utc)
        ts_utc = ts_utc[order]
        f_hz = f_hz[order]

    t_min = float(ts_utc[0]) if search_start_utc is None else max(float(ts_utc[0]), float(search_start_utc))
    t_max = float(ts_utc[-1]) if search_end_utc is None else min(float(ts_utc[-1]), float(search_end_utc))
    if t_max < t_min:
        return np.array([], dtype=np.float64), np.array([], dtype=np.float64), np.array([], dtype=np.float64)

    # Slice raw arrays to [t_min - cadence_s, t_max + cadence_s] for speed
    i0 = max(0, int(np.searchsorted(ts_utc, t_min - cadence_s, side="left")))
    i1 = min(len(ts_utc), int(np.searchsorted(ts_utc, t_max + cadence_s, side="right")))
    ts_sub = ts_utc[i0:i1]
    f_sub = f_hz[i0:i1].copy()

    # Invalidate out-of-range reference values
    valid_raw = np.isfinite(f_sub) & (np.abs(f_sub - nominal_hz) <= max_dev_hz)

    n_grid = int(math.floor((t_max - t_min) / cadence_s)) + 1
    t_grid = t_min + np.arange(n_grid, dtype=np.float64) * cadence_s

    # Fast path if already on exact uniform grid
    if (
        len(ts_sub) == n_grid
        and np.allclose(ts_sub, t_grid, atol=1e-3)
    ):
        m_y = _mask_flat_runs(f_sub, valid_raw.astype(np.float64))
        f_grid = np.where(m_y > 0, f_sub, nominal_hz)
        return t_grid, f_grid, m_y

    if np.sum(valid_raw) < 2:
        return t_grid, np.full(n_grid, nominal_hz, dtype=np.float64), np.zeros(n_grid, dtype=np.float64)

    ts_v = ts_sub[valid_raw]
    f_v = f_sub[valid_raw]

    f_grid = np.interp(t_grid, ts_v, f_v, left=np.nan, right=np.nan)

    # Check distance to nearest valid sample to avoid bridging gaps > max_interp_gap_s
    idx_right = np.clip(np.searchsorted(ts_v, t_grid, side="left"), 0, len(ts_v) - 1)
    idx_left = np.clip(idx_right - 1, 0, len(ts_v) - 1)
    dist_nearest = np.minimum(np.abs(t_grid - ts_v[idx_left]), np.abs(ts_v[idx_right] - t_grid))
    span_gap = np.abs(ts_v[idx_right] - ts_v[idx_left])

    m_y = (
        np.isfinite(f_grid)
        & (t_grid >= ts_v[0] - 1e-3)
        & (t_grid <= ts_v[-1] + 1e-3)
        & ((dist_nearest <= 0.55 * cadence_s) | (span_gap <= max_interp_gap_s))
    ).astype(np.float64)
    m_y = _mask_flat_runs(f_grid, m_y)
    f_grid = np.where(m_y > 0, f_grid, nominal_hz)
    return t_grid, f_grid, m_y


def resample_trace_regular(
    t_s: np.ndarray,
    f_hz: np.ndarray,
    q: np.ndarray,
    cadence_s: float = 1.0,
    clock_drift: float = 0.0,
    nominal_hz: float = 50.0,
    max_dev_hz: float = 0.6,
    q_min: float = 0.05,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Resample an extracted ENF trace onto a uniform relative time grid
    `t_rel = 0, cadence_s, 2*cadence_s, ...` while preserving exact temporal
    offsets of invalid/NaN windows (assigning them weight w_x = 0.0).

    When `clock_drift` (alpha in [-0.005, +0.005]) is non-zero, stretches the
    trace time axis by `(1 + clock_drift)`.
    """
    if len(t_s) == 0 or len(f_hz) == 0:
        return np.array([], dtype=np.float64), np.array([], dtype=np.float64), np.array([], dtype=np.float64)

    t_rel = (np.asarray(t_s, dtype=np.float64) - float(t_s[0])) * (1.0 + clock_drift)
    f_arr = np.asarray(f_hz, dtype=np.float64)
    q_arr = np.asarray(q, dtype=np.float64) if len(q) == len(f_arr) else np.where(np.isfinite(f_arr), 1.0, 0.0)

    valid_mask = (
        np.isfinite(f_arr)
        & np.isfinite(t_rel)
        & (np.abs(f_arr - nominal_hz) <= max_dev_hz)
        & (q_arr >= q_min)
    )
    w_raw = np.where(valid_mask, np.clip(q_arr, 0.0, 1.0), 0.0)

    dur = float(t_rel[-1])
    n_grid = int(math.floor(dur / cadence_s + 1e-6)) + 1
    if n_grid < 2:
        return np.array([], dtype=np.float64), np.array([], dtype=np.float64), np.array([], dtype=np.float64)

    t_grid = np.arange(n_grid, dtype=np.float64) * cadence_s

    # Fast path if trace is already on the target cadence and clock_drift == 0
    if (
        abs(clock_drift) < 1e-12
        and len(t_rel) == n_grid
        and np.allclose(t_rel, t_grid, atol=1e-3)
    ):
        f_clean = np.where(valid_mask, f_arr, nominal_hz)
        return t_grid, f_clean, w_raw

    # Interpolate weights and valid frequency values onto t_grid without bridging NaN holes
    w_grid = np.interp(t_grid, t_rel, w_raw, left=0.0, right=0.0)
    if np.sum(valid_mask) < 2:
        return t_grid, np.full(n_grid, nominal_hz, dtype=np.float64), np.zeros(n_grid, dtype=np.float64)

    t_v = t_rel[valid_mask]
    f_v = f_arr[valid_mask]
    f_grid = np.interp(t_grid, t_v, f_v, left=nominal_hz, right=nominal_hz)

    # Zero out weights where nearest valid sample is further than cadence_s
    idx_r = np.clip(np.searchsorted(t_v, t_grid, side="left"), 0, len(t_v) - 1)
    idx_l = np.clip(idx_r - 1, 0, len(t_v) - 1)
    dist_v = np.minimum(np.abs(t_grid - t_v[idx_l]), np.abs(t_v[idx_r] - t_grid))
    w_grid = np.where((dist_v <= 0.75 * cadence_s) & (w_grid >= q_min), w_grid, 0.0)
    f_grid = np.where(w_grid > 0, f_grid, nominal_hz)
    return t_grid, f_grid, w_grid


def sliding_weighted_ncc_and_rmse(
    f_x: np.ndarray,
    w_x: np.ndarray,
    f_y: np.ndarray,
    m_y: np.ndarray,
    min_overlap_frac: float = 0.70,
    min_ref_std_hz: float = 0.0004,
) -> dict[str, np.ndarray]:
    """
    Compute exact sliding Weighted Normalized Cross-Correlation (WNCC),
    Offset-Adjusted Weighted RMSE (in mHz), and relative frequency offset (in Hz)
    for all lags tau in [0, R - L] simultaneously via batch 1D real FFTs.

    Globally centers f_x and f_y before FFT convolution to guarantee full 64-bit
    floating-point precision on millihertz deviations around 50 Hz.
    """
    L = len(f_x)
    R = len(f_y)
    if R < L or L < 2:
        return {
            "score": np.array([], dtype=np.float64),
            "rmse_mhz": np.array([], dtype=np.float64),
            "offset_hz": np.array([], dtype=np.float64),
            "ref_std_mhz": np.array([], dtype=np.float64),
            "overlap_frac": np.array([], dtype=np.float64),
        }

    n_lags = R - L + 1
    w_sum_total = float(np.sum(w_x))
    if w_sum_total <= 1e-9:
        return {
            "score": np.full(n_lags, np.nan, dtype=np.float64),
            "rmse_mhz": np.full(n_lags, np.inf, dtype=np.float64),
            "offset_hz": np.zeros(n_lags, dtype=np.float64),
            "ref_std_mhz": np.zeros(n_lags, dtype=np.float64),
            "overlap_frac": np.zeros(n_lags, dtype=np.float64),
        }

    # Global weighted means for numerical stability
    x_bar = float(np.sum(w_x * f_x) / w_sum_total)
    m_sum_total = float(np.sum(m_y))
    y_bar = float(np.sum(m_y * f_y) / max(m_sum_total, 1.0))

    dx = np.where(w_x > 0, f_x - x_bar, 0.0)
    dy = np.where(m_y > 0, f_y - y_bar, 0.0)

    # Reversed query templates for cross-correlation via convolution
    w_rev = w_x[::-1]
    wx_rev = (w_x * dx)[::-1]
    wx2_rev = (w_x * dx * dx)[::-1]

    my = m_y
    my_y = m_y * dy
    my_y2 = m_y * dy * dy

    # Shared FFT size across convolutions
    n_conv = R + L - 1
    n_fft = sp_fft.next_fast_len(n_conv)

    F_my_y = sp_fft.rfft(my_y, n=n_fft)
    F_my_y2 = sp_fft.rfft(my_y2, n=n_fft)
    F_w_rev = sp_fft.rfft(w_rev, n=n_fft)
    F_wx_rev = sp_fft.rfft(wx_rev, n=n_fft)

    def _valid_slice(prod_spec: np.ndarray) -> np.ndarray:
        full = sp_fft.irfft(prod_spec, n=n_fft)
        return full[L - 1 : L - 1 + n_lags]

    # Fast path when reference has no missing samples (m_y == 1 everywhere)
    if np.all(m_y == 1.0):
        S_W = np.full(n_lags, w_sum_total, dtype=np.float64)
        S_WX = np.zeros(n_lags, dtype=np.float64)  # because sum(w_x * dx) == 0
        S_WX2 = np.full(n_lags, float(np.sum(w_x * dx * dx)), dtype=np.float64)
    else:
        F_my = sp_fft.rfft(my, n=n_fft)
        F_wx2_rev = sp_fft.rfft(wx2_rev, n=n_fft)
        S_W = _valid_slice(F_my * F_w_rev)
        S_WX = _valid_slice(F_my * F_wx_rev)
        S_WX2 = _valid_slice(F_my * F_wx2_rev)

    S_WY = _valid_slice(F_my_y * F_w_rev)
    S_WY2 = _valid_slice(F_my_y2 * F_w_rev)
    S_WXY = _valid_slice(F_my_y * F_wx_rev)

    overlap_frac = S_W / w_sum_total
    safe_SW = np.maximum(S_W, 1e-12)

    mu_x = S_WX / safe_SW
    mu_y = S_WY / safe_SW

    # Local centered weighted sums of squares and cross-products
    V_x = np.maximum(0.0, S_WX2 - S_W * mu_x * mu_x)
    V_y = np.maximum(0.0, S_WY2 - S_W * mu_y * mu_y)
    C_xy = S_WXY - S_W * mu_x * mu_y

    std_x = np.sqrt(V_x / safe_SW)
    std_y = np.sqrt(V_y / safe_SW)

    valid_lag = (
        (overlap_frac >= min_overlap_frac)
        & (std_x >= 1e-6)
        & (std_y >= min_ref_std_hz)
    )

    denom = np.sqrt(np.maximum(V_x * V_y, 1e-24))
    score = np.where(valid_lag, np.clip(C_xy / denom, -1.0, 1.0), np.nan)

    # Offset-adjusted weighted MSE: sum W_k ((x_k - mu_x) - (y_{tau+k} - mu_y))^2 / S_W
    sse_centered = np.maximum(0.0, V_x + V_y - 2.0 * C_xy)
    rmse_mhz = np.where(valid_lag, 1000.0 * np.sqrt(sse_centered / safe_SW), np.inf)

    # Relative frequency offset: mean(x) - mean(y) at lag tau
    offset_hz = (x_bar + mu_x) - (y_bar + mu_y)

    return {
        "score": score,
        "rmse_mhz": rmse_mhz,
        "offset_hz": offset_hz,
        "ref_std_mhz": std_y * 1000.0,
        "overlap_frac": overlap_frac,
    }


def _parabolic_subsample_refinement(scores: np.ndarray, idx: int, cadence_s: float) -> tuple[float, float]:
    """
    Fit a 3-point parabola around peak index `idx` to estimate sub-sample time
    offset (in seconds) and refined peak score.
    """
    if idx <= 0 or idx >= len(scores) - 1:
        return 0.0, float(scores[idx])
    y_l = float(scores[idx - 1])
    y_c = float(scores[idx])
    y_r = float(scores[idx + 1])
    if not (math.isfinite(y_l) and math.isfinite(y_c) and math.isfinite(y_r)):
        return 0.0, y_c
    denom = 2.0 * (y_l - 2.0 * y_c + y_r)
    if abs(denom) < 1e-12 or (y_l - 2.0 * y_c + y_r) >= 0.0:
        return 0.0, y_c
    delta_bins = float(np.clip((y_l - y_r) / denom, -0.5, 0.5))
    refined_score = float(np.clip(y_c - 0.25 * (y_l - y_r) * delta_bins, -1.0, 1.0))
    return delta_bins * cadence_s, refined_score


def extract_top_k_candidates_nms(
    scores: np.ndarray,
    rmse_mhz: np.ndarray,
    offset_hz: np.ndarray,
    t_ref_grid: np.ndarray,
    cadence_s: float,
    nms_radius_s: float,
    top_k: int = 5,
    extra_fields: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """
    Greedy Non-Maximum Suppression (NMS) over the sliding score array.
    Suppresses a neighborhood of +/- `nms_radius_s` around each selected peak so
    sidelobes of the same autocorrelation peak are never mistaken for competing peaks.
    """
    work_scores = np.where(np.isfinite(scores), scores, -np.inf).copy()
    nms_bins = max(1, int(round(nms_radius_s / max(cadence_s, 1e-6))))
    candidates: list[dict[str, Any]] = []

    for rank in range(top_k):
        if len(work_scores) == 0:
            break
        best_idx = int(np.argmax(work_scores))
        best_val = float(work_scores[best_idx])
        if not math.isfinite(best_val) or best_val <= -1e9:
            break

        sub_offset_s, refined_score = _parabolic_subsample_refinement(scores, best_idx, cadence_s)
        cand: dict[str, Any] = {
            "start_utc": int(round(float(t_ref_grid[best_idx]))),
            "score": float(scores[best_idx]),
            "rmse_mhz": float(rmse_mhz[best_idx]),
            "offset_hz": float(offset_hz[best_idx]),
            "lag_index": best_idx,
            "sub_sample_offset_s": float(sub_offset_s),
            "refined_score": float(refined_score),
            "rank": rank + 1,
        }
        if extra_fields:
            cand.update(extra_fields)
        candidates.append(cand)

        # Suppress neighborhood [best_idx - nms_bins, best_idx + nms_bins]
        lo = max(0, best_idx - nms_bins)
        hi = min(len(work_scores), best_idx + nms_bins + 1)
        work_scores[lo:hi] = -np.inf

    return candidates


def compute_within_window_acf(x: np.ndarray, w: np.ndarray, max_lag: int) -> np.ndarray:
    """
    Compute positive-semidefinite weighted within-window autocorrelation up to `max_lag`.
    """
    n = len(x)
    if n < 3 or np.sum(w) <= 1e-9:
        return np.zeros(max_lag + 1, dtype=np.float64)
    mu = float(np.sum(w * x) / np.sum(w))
    z = np.where(w > 0, (x - mu) * np.sqrt(w), 0.0)
    var_z = float(np.sum(z * z))
    if var_z <= 1e-18:
        return np.zeros(max_lag + 1, dtype=np.float64)
    n_fft = sp_fft.next_fast_len(2 * n - 1)
    fz = np.fft.rfft(z, n=n_fft)
    acov = np.fft.irfft(fz * np.conjugate(fz), n=n_fft)[: max_lag + 1]
    acf = acov / var_z
    acf[0] = 1.0
    return np.clip(acf, -1.0, 1.0)


def compute_calibrated_null(
    f_x: np.ndarray,
    w_x: np.ndarray,
    f_y: np.ndarray,
    m_y: np.ndarray,
    forward_scores: np.ndarray,
    best_lag_idx: int,
    best_score: float,
    cadence_s: float = 1.0,
    n_drift_trials: int = 1,
    alpha_target: float = 0.01,
    n_surrogates: int = 1,
    min_overlap_frac: float = 0.70,
    seed: int = 42,
) -> dict[str, Any]:
    """
    Derive a calibrated look-elsewhere p-value (`p_empirical`) and `score_threshold`
    by combining:
      1. Bartlett's effective degrees of freedom N_eff from the product of local
         query and reference autocorrelations:
           1 / N_eff = 1 / N_v + (2 / N_v^2) * sum_{k=1}^{L-1} (N_v - k) * max(0, rho_x(k) * rho_y(k))
      2. Empirical null correlation distribution obtained by matching `f_x` against:
         (a) Time-reversed reference `f_y[::-1]` (exact same local spectrum, variance,
             and autocorrelation as `f_y`, guaranteed causal mismatch),
         (b) Off-peak background lags outside +/- 2*L of the top peaks, and
         (c) Optional circular-shift / Fourier phase-randomized (AAFT) surrogates.
      3. Effective number of independent candidate peaks `M_eff` across the search
         window and clock-drift grid, accounting for peak decorrelation width.
    """
    L = len(f_x)
    R = len(f_y)
    n_valid = int(np.sum(w_x > 0))
    if n_valid < 4 or R < L or not math.isfinite(best_score):
        return {
            "method": "bartlett_student_t_plus_time_reversed_surrogate",
            "n": 0,
            "p_empirical": 1.0,
            "score_threshold": 1.0,
            "n_eff_bartlett": float(n_valid),
            "n_eff_empirical": float(n_valid),
            "n_eff_used": float(n_valid),
            "m_eff": 1.0,
            "p_local": 1.0,
            "max_time_reversed_null_score": 0.0,
        }

    # 1. Analytical Bartlett N_eff on local window
    max_k = min(L - 1, 300)
    acf_x = compute_within_window_acf(f_x, w_x, max_lag=max_k)

    # Estimate average local within-window ACF of reference over up to 25 slices of length L
    rng = np.random.default_rng(seed)
    n_ref_slices = min(25, max(1, R // max(L, 1)))
    slice_starts = np.linspace(0, R - L, n_ref_slices, dtype=int)
    acf_y_accum = np.zeros(max_k + 1, dtype=np.float64)
    valid_slices = 0
    for s in slice_starts:
        sub_y = f_y[s : s + L]
        sub_m = m_y[s : s + L]
        if np.mean(sub_m) >= min_overlap_frac:
            acf_y_accum += compute_within_window_acf(sub_y, sub_m, max_lag=max_k)
            valid_slices += 1
    acf_y = acf_y_accum / max(valid_slices, 1) if valid_slices > 0 else acf_x

    k_arr = np.arange(1, max_k + 1, dtype=np.float64)
    prod_acf = np.maximum(0.0, acf_x[1:] * acf_y[1:])
    var_r_bartlett = (1.0 / n_valid) + (2.0 / (n_valid * n_valid)) * float(
        np.sum((n_valid - k_arr) * prod_acf)
    )
    n_eff_bartlett = float(np.clip(1.0 / max(var_r_bartlett, 1.0 / n_valid), 2.5, float(n_valid)))

    # 2. Empirical null lags from time-reversed reference + off-peak forward lags
    rev_res = sliding_weighted_ncc_and_rmse(
        f_x, w_x, f_y[::-1], m_y[::-1], min_overlap_frac=min_overlap_frac
    )
    null_samples_list = [rev_res["score"][np.isfinite(rev_res["score"])]]

    # Add off-peak forward lags outside +/- 2*L of best_lag_idx
    if len(forward_scores) > 4 * L:
        mask_offpeak = np.ones(len(forward_scores), dtype=bool)
        lo_ex = max(0, best_lag_idx - 2 * L)
        hi_ex = min(len(forward_scores), best_lag_idx + 2 * L + 1)
        mask_offpeak[lo_ex:hi_ex] = False
        offpeak_vals = forward_scores[mask_offpeak & np.isfinite(forward_scores)]
        if len(offpeak_vals) > 0:
            null_samples_list.append(offpeak_vals)

    # Optional phase-randomized surrogate of reference (preserves exact power spectrum)
    if n_surrogates >= 2 and R >= 2 * L:
        y_centered = f_y - np.mean(f_y)
        spec_y = np.fft.rfft(y_centered)
        phases = rng.uniform(0, 2.0 * np.pi, size=len(spec_y))
        phases[0] = 0.0
        if R % 2 == 0:
            phases[-1] = 0.0
        surr_y = np.mean(f_y) + np.fft.irfft(np.abs(spec_y) * np.exp(1j * phases), n=R)
        surr_res = sliding_weighted_ncc_and_rmse(
            f_x, w_x, surr_y, m_y, min_overlap_frac=min_overlap_frac
        )
        surr_vals = surr_res["score"][np.isfinite(surr_res["score"])]
        if len(surr_vals) > 0:
            null_samples_list.append(surr_vals)

    null_all = np.concatenate(null_samples_list) if len(null_samples_list) > 0 else np.array([], dtype=np.float64)
    n_null_lags = int(len(null_all))

    if n_null_lags >= 20:
        z_null = np.arctanh(np.clip(null_all, -0.9999, 0.9999))
        z50, z95, z99 = np.percentile(z_null, [50.0, 95.0, 99.0])
        z_tail_95 = float((z95 - z50) / 1.6448536)
        z_tail_99 = float((z99 - z50) / 2.3263479)
        z_bulk_std = float(np.std(z_null))
        sigma_z_emp = max(0.5 * (z_tail_95 + z_tail_99), 0.85 * z_bulk_std, 1e-6)
        n_eff_emp = float(np.clip(3.0 + 1.0 / (sigma_z_emp * sigma_z_emp), 3.5, float(n_valid)))
    else:
        z50 = 0.0
        sigma_z_emp = 1.0 / math.sqrt(max(n_eff_bartlett - 3.0, 1.5))
        n_eff_emp = n_eff_bartlett

    sigma_z_bartlett = 1.0 / math.sqrt(max(n_eff_bartlett - 3.0, 1.5))
    # Conservative Fisher-z standard error combining empirical null and Bartlett theory
    sigma_z_used = max(sigma_z_emp, 0.85 * sigma_z_bartlett)
    n_eff_used = float(np.clip(3.0 + 1.0 / (sigma_z_used * sigma_z_used), 3.5, float(n_valid)))

    # 3. Effective number of independent candidate peaks M_eff measured from a slice of
    # the time-reversed sliding correlation sequence (O(1) fast slice)
    slice_len = min(len(rev_res["score"]), max(4096, 6 * L))
    rev_slice = rev_res["score"][:slice_len]
    rev_valid_mask = np.isfinite(rev_slice)
    if np.sum(rev_valid_mask) > L:
        acf_r = compute_within_window_acf(
            np.where(rev_valid_mask, rev_slice, 0.0),
            rev_valid_mask.astype(np.float64),
            max_lag=min(L, slice_len // 2),
        )
        zero_cross = np.where(acf_r[1:] <= 0.0)[0]
        stop_k = int(zero_cross[0]) + 1 if len(zero_cross) > 0 else len(acf_r)
        tau_decorr_bins = max(1.0, 1.0 + 2.0 * float(np.sum(np.maximum(0.0, acf_r[1:stop_k]))))
    else:
        tau_decorr_bins = max(1.0, float(L) / n_eff_used)

    n_valid_lags = int(np.sum(np.isfinite(forward_scores)))
    m_eff = max(1.0, (float(max(1, n_valid_lags)) / tau_decorr_bins) * float(max(1, n_drift_trials)))

    # 4. Variance-stabilized Fisher-z look-elsewhere calibration on (-1, 1)
    r_clamped = float(np.clip(best_score, -0.999999, 0.999999))
    if r_clamped <= 0.0:
        p_local = 0.5
        p_empirical = 1.0
    else:
        z_best = math.atanh(r_clamped)
        z_score = (z_best - max(0.0, float(z50))) / max(sigma_z_used, 1e-6)
        p_local = float(stats.norm.sf(z_score))
        if p_local <= 1e-12:
            p_empirical = float(min(1.0, m_eff * p_local))
        else:
            p_empirical = float(-math.expm1(m_eff * math.log1p(-min(p_local, 1.0 - 1e-16))))
        p_empirical = float(np.clip(p_empirical, 0.0, 1.0))

    # 5. Score threshold in r-space for target significance alpha_target
    q_local_thresh = (1.0 - alpha_target) ** (1.0 / m_eff)
    z_thresh = max(0.0, float(z50)) + sigma_z_used * float(
        stats.norm.ppf(min(q_local_thresh, 1.0 - 1e-15))
    )
    score_threshold = float(math.tanh(z_thresh))

    # Also record the maximum correlation observed on the time-reversed null reference
    rev_valid = rev_res["score"][np.isfinite(rev_res["score"])]
    max_rev_null = float(np.max(rev_valid)) if len(rev_valid) > 0 else float("nan")
    if math.isfinite(max_rev_null):
        if best_score <= max_rev_null:
            p_empirical = max(p_empirical, 0.50)
        score_threshold = float(max(score_threshold, min(0.92, max_rev_null + 0.02)))

    return {
        "method": "bartlett_student_t_plus_time_reversed_surrogate",
        "n": int(n_null_lags),
        "p_empirical": float(p_empirical),
        "score_threshold": float(score_threshold),
        "n_eff_bartlett": float(n_eff_bartlett),
        "n_eff_empirical": float(n_eff_emp),
        "n_eff_used": float(n_eff_used),
        "m_eff": float(m_eff),
        "p_local": float(p_local),
        "max_time_reversed_null_score": float(max_rev_null) if math.isfinite(max_rev_null) else None,
    }


def compute_split_half_diagnostics(
    f_x: np.ndarray,
    w_x: np.ndarray,
    f_y: np.ndarray,
    m_y: np.ndarray,
    t_ref_grid: np.ndarray,
    best_lag_idx: int,
    cadence_s: float = 1.0,
    tolerance_s: float = 15.0,
    min_overlap_frac: float = 0.60,
) -> dict[str, Any]:
    """
    Split the resampled query trace into first half and second half.
    1. Measure local weighted correlation of each half at the full-trace `best_lag_idx`.
    2. Run independent full-window searches for the first half and second half to
       test whether both halves independently locate the same reference offset.
    """
    L = len(f_x)
    half = L // 2
    if half < 6 or len(f_y) < L or best_lag_idx < 0:
        return {
            "split_half_agreement_s": float("inf"),
            "split_half_consistent": False,
            "split_half_r1_at_best": 0.0,
            "split_half_r2_at_best": 0.0,
            "split_half_t1_utc": None,
            "split_half_t2_adjusted_utc": None,
        }

    x1, w1 = f_x[:half], w_x[:half]
    x2, w2 = f_x[half:], w_x[half:]

    res1 = sliding_weighted_ncc_and_rmse(x1, w1, f_y, m_y, min_overlap_frac=min_overlap_frac)
    res2 = sliding_weighted_ncc_and_rmse(x2, w2, f_y, m_y, min_overlap_frac=min_overlap_frac)

    s1 = res1["score"]
    s2 = res2["score"]

    r1_at_best = float(s1[best_lag_idx]) if best_lag_idx < len(s1) and math.isfinite(s1[best_lag_idx]) else 0.0
    idx2_at_best = best_lag_idx + half
    r2_at_best = float(s2[idx2_at_best]) if idx2_at_best < len(s2) and math.isfinite(s2[idx2_at_best]) else 0.0

    valid1 = np.isfinite(s1)
    valid2 = np.isfinite(s2)
    if not (np.any(valid1) and np.any(valid2)):
        return {
            "split_half_agreement_s": float("inf"),
            "split_half_consistent": False,
            "split_half_r1_at_best": r1_at_best,
            "split_half_r2_at_best": r2_at_best,
            "split_half_t1_utc": None,
            "split_half_t2_adjusted_utc": None,
        }

    best1_idx = int(np.argmax(np.where(valid1, s1, -np.inf)))
    best2_idx = int(np.argmax(np.where(valid2, s2, -np.inf)))

    t1_utc = float(t_ref_grid[best1_idx])
    t2_adjusted_utc = float(t_ref_grid[best2_idx]) - float(half) * cadence_s
    diff_s = abs(t1_utc - t2_adjusted_utc)

    return {
        "split_half_agreement_s": float(diff_s),
        "split_half_consistent": bool(diff_s <= tolerance_s),
        "split_half_r1_at_best": float(r1_at_best),
        "split_half_r2_at_best": float(r2_at_best),
        "split_half_t1_utc": int(round(t1_utc)),
        "split_half_t2_adjusted_utc": int(round(t2_adjusted_utc)),
    }


def match(
    trace: Union[str, Path, dict[str, Any], pd.DataFrame, np.ndarray],
    reference: Union[str, Path, dict[str, Any], pd.DataFrame, np.ndarray],
    search_start_utc: Optional[int] = None,
    search_end_utc: Optional[int] = None,
    config: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Primary GhostClock ENF matcher (`integration/interfaces.md` §3).

    Performs a strictly blind search over `[search_start_utc, search_end_utc]`,
    computes look-elsewhere calibrated null statistics, uniqueness margins, and
    split-half consistency, and applies the deterministic decision policy.
    """
    cfg = dict(config or {})

    # Extract claimed_start_utc ONLY for the final policy step; delete from search scope!
    claimed_start_utc = cfg.pop("claimed_start_utc", None)
    claim_tolerance_s = cfg.pop("claim_tolerance_s", None)

    cadence_s = float(cfg.get("cadence_s", 1.0))
    nominal_hz = float(cfg.get("nominal_hz", 50.0))
    max_dev_hz = float(cfg.get("max_dev_hz", 0.60))
    q_min = float(cfg.get("q_min", 0.05))
    min_overlap_frac = float(cfg.get("min_overlap_frac", 0.70))
    top_k = int(cfg.get("top_k", 5))
    alpha_target = float(cfg.get("alpha_target", 0.01))
    n_surrogates = int(cfg.get("n_surrogates", 1))
    seed = int(cfg.get("seed", 42))

    # Clock-drift search parameters (+/- 0.5% max per prompt §1)
    clock_drift_search = bool(cfg.get("clock_drift_search", False))
    max_clock_drift = float(cfg.get("max_clock_drift", 0.005))
    n_drift_steps = int(cfg.get("n_drift_steps", 21)) if clock_drift_search else 1

    # Load and regularize inputs
    t_raw, f_raw, q_raw, trace_meta = _load_trace_input(trace, default_cadence_s=cadence_s)
    if "nominal_hz" in trace_meta and "nominal_hz" not in (config or {}):
        nominal_hz = float(trace_meta["nominal_hz"])

    ts_ref_raw, f_ref_raw, ref_meta = _load_reference_input(
        reference, search_start_utc=search_start_utc, default_cadence_s=cadence_s
    )
    if "cadence_s" in ref_meta and "cadence_s" not in (config or {}):
        cadence_s = float(ref_meta["cadence_s"])

    t_ref_grid, f_y, m_y = resample_reference_regular(
        ts_ref_raw,
        f_ref_raw,
        search_start_utc=search_start_utc,
        search_end_utc=search_end_utc,
        cadence_s=cadence_s,
        nominal_hz=nominal_hz,
        max_dev_hz=max(1.0, max_dev_hz * 2.0),
    )

    if clock_drift_search and n_drift_steps > 1:
        drift_grid = np.linspace(-max_clock_drift, max_clock_drift, n_drift_steps)
        # Ensure 0.0 is explicitly included
        if not np.any(np.isclose(drift_grid, 0.0)):
            drift_grid = np.sort(np.append(drift_grid, 0.0))
    else:
        drift_grid = np.array([0.0], dtype=np.float64)

    best_drift = 0.0
    best_drift_peak = -np.inf
    best_res: Optional[dict[str, np.ndarray]] = None
    best_tx: Optional[np.ndarray] = None
    best_fx: Optional[np.ndarray] = None
    best_wx: Optional[np.ndarray] = None

    for alpha in drift_grid:
        tx, fx, wx = resample_trace_regular(
            t_raw,
            f_raw,
            q_raw,
            cadence_s=cadence_s,
            clock_drift=float(alpha),
            nominal_hz=nominal_hz,
            max_dev_hz=max_dev_hz,
            q_min=q_min,
        )
        if len(fx) < 2 or len(f_y) < len(fx):
            continue
        res = sliding_weighted_ncc_and_rmse(
            fx, wx, f_y, m_y, min_overlap_frac=min_overlap_frac
        )
        finite_mask = np.isfinite(res["score"])
        peak_val = float(np.max(res["score"][finite_mask])) if np.any(finite_mask) else -np.inf
        if peak_val > best_drift_peak or best_res is None:
            best_drift_peak = peak_val
            best_drift = float(alpha)
            best_res = res
            best_tx, best_fx, best_wx = tx, fx, wx

    # Fallback if trace or reference was empty/shorter than clip
    if best_res is None or best_fx is None or best_wx is None or len(best_res["score"]) == 0:
        empty_result: dict[str, Any] = {
            "best": {
                "start_utc": int(search_start_utc or 0),
                "score": float("nan"),
                "rmse_mhz": float("inf"),
                "offset_hz": 0.0,
            },
            "candidates": [],
            "null": {
                "method": "bartlett_student_t_plus_time_reversed_surrogate",
                "n": 0,
                "p_empirical": 1.0,
                "score_threshold": 1.0,
            },
            "uniqueness": {
                "margin_vs_second": 0.0,
                "second_best_distance_s": 0,
            },
            "diagnostics": {
                "valid_duration_s": 0.0,
                "n_valid_samples": 0,
                "valid_fraction": 0.0,
                "trace_std_mhz": 0.0,
                "best_ref_std_mhz": 0.0,
                "cadence_s": cadence_s,
                "error": "Insufficient valid samples or reference shorter than query trace.",
            },
            "status": "INCONCLUSIVE",
            "status_reasons": [],
            "what_would_change_this": [],
        }
        return evaluate_policy(
            empty_result,
            claimed_start_utc=claimed_start_utc,
            tolerance_s=claim_tolerance_s,
            thresholds=cfg.get("policy_thresholds"),
        )

    scores = best_res["score"]
    rmse_mhz = best_res["rmse_mhz"]
    offset_hz = best_res["offset_hz"]
    ref_std_mhz = best_res["ref_std_mhz"]

    L = len(best_fx)
    duration_s = float(L - 1) * cadence_s
    valid_mask = best_wx > 0
    n_valid = int(np.sum(valid_mask))
    valid_frac = float(n_valid) / float(max(1, L))
    valid_dur_s = float(n_valid) * cadence_s

    if n_valid >= 2:
        w_norm = best_wx[valid_mask] / np.sum(best_wx[valid_mask])
        mu_trace = float(np.sum(w_norm * best_fx[valid_mask]))
        trace_std_mhz = float(1000.0 * np.sqrt(np.sum(w_norm * (best_fx[valid_mask] - mu_trace) ** 2)))
    else:
        mu_trace = float("nan")
        trace_std_mhz = 0.0

    # Non-Maximum Suppression radius: at least 30s or 25% of clip duration
    nms_radius_s = float(cfg.get("nms_radius_s", max(30.0, 0.25 * duration_s)))
    candidates = extract_top_k_candidates_nms(
        scores=scores,
        rmse_mhz=rmse_mhz,
        offset_hz=offset_hz,
        t_ref_grid=t_ref_grid,
        cadence_s=cadence_s,
        nms_radius_s=nms_radius_s,
        top_k=top_k,
        extra_fields={"clock_drift_ppm": float(best_drift * 1e6)},
    )

    if len(candidates) == 0:
        best_cand = {
            "start_utc": int(round(float(t_ref_grid[0]))),
            "score": float("nan"),
            "rmse_mhz": float("inf"),
            "offset_hz": 0.0,
        }
        best_lag_idx = 0
        margin_vs_second = 0.0
        second_dist_s = 0
    else:
        c0 = candidates[0]
        best_lag_idx = int(c0["lag_index"])
        best_cand = {
            "start_utc": int(c0["start_utc"]),
            "score": float(c0["score"]),
            "rmse_mhz": float(c0["rmse_mhz"]),
            "offset_hz": float(c0["offset_hz"]),
        }
        if len(candidates) >= 2:
            c1 = candidates[1]
            margin_vs_second = float(c0["score"] - c1["score"])
            second_dist_s = int(abs(int(c0["start_utc"]) - int(c1["start_utc"])))
        else:
            margin_vs_second = float(max(0.0, c0["score"]))
            second_dist_s = int(round(float(len(scores)) * cadence_s))

    # Calibrated look-elsewhere null
    null_full = compute_calibrated_null(
        f_x=best_fx,
        w_x=best_wx,
        f_y=f_y,
        m_y=m_y,
        forward_scores=scores,
        best_lag_idx=best_lag_idx,
        best_score=float(best_cand["score"]),
        cadence_s=cadence_s,
        n_drift_trials=len(drift_grid),
        alpha_target=alpha_target,
        n_surrogates=n_surrogates,
        min_overlap_frac=min_overlap_frac,
        seed=seed,
    )

    # Split-half consistency check
    split_diag = compute_split_half_diagnostics(
        f_x=best_fx,
        w_x=best_wx,
        f_y=f_y,
        m_y=m_y,
        t_ref_grid=t_ref_grid,
        best_lag_idx=best_lag_idx,
        cadence_s=cadence_s,
        min_overlap_frac=max(0.50, min_overlap_frac - 0.10),
    )

    best_ref_std_mhz = (
        float(ref_std_mhz[best_lag_idx])
        if 0 <= best_lag_idx < len(ref_std_mhz) and math.isfinite(ref_std_mhz[best_lag_idx])
        else 0.0
    )

    q_summary = trace_meta.get("quality_summary", {}) if isinstance(trace_meta, dict) else {}
    enf_presence_score = q_summary.get("enf_presence_score", trace_meta.get("enf_presence_score", None))
    extractor_snr_db = q_summary.get("snr_db", trace_meta.get("snr_db", None))

    result: dict[str, Any] = {
        "best": best_cand,
        "candidates": [
            {
                "start_utc": int(c["start_utc"]),
                "score": float(c["score"]),
                "rmse_mhz": float(c["rmse_mhz"]),
                "offset_hz": float(c["offset_hz"]),
                "sub_sample_offset_s": float(c["sub_sample_offset_s"]),
                "refined_score": float(c["refined_score"]),
                "clock_drift_ppm": float(c.get("clock_drift_ppm", 0.0)),
            }
            for c in candidates
        ],
        "null": {
            "method": str(null_full["method"]),
            "n": int(null_full["n"]),
            "p_empirical": float(null_full["p_empirical"]),
            "score_threshold": float(null_full["score_threshold"]),
        },
        "uniqueness": {
            "margin_vs_second": float(margin_vs_second),
            "second_best_distance_s": int(second_dist_s),
        },
        "diagnostics": {
            "cadence_s": float(cadence_s),
            "nominal_hz": float(nominal_hz),
            "trace_duration_s": float(duration_s),
            "valid_duration_s": float(valid_dur_s),
            "n_total_samples": int(L),
            "n_valid_samples": int(n_valid),
            "valid_fraction": float(valid_frac),
            "trace_mean_hz": float(mu_trace) if math.isfinite(mu_trace) else None,
            "trace_std_mhz": float(trace_std_mhz),
            "best_ref_std_mhz": float(best_ref_std_mhz),
            "search_window_start_utc": int(round(float(t_ref_grid[0]))),
            "search_window_end_utc": int(round(float(t_ref_grid[-1]))),
            "search_window_duration_s": float(t_ref_grid[-1] - t_ref_grid[0]),
            "n_candidate_lags": int(len(scores)),
            "nms_radius_s": float(nms_radius_s),
            "sub_sample_offset_s": float(candidates[0]["sub_sample_offset_s"]) if candidates else 0.0,
            "refined_start_utc": (
                float(best_cand["start_utc"]) + float(candidates[0]["sub_sample_offset_s"])
                if candidates
                else float(best_cand["start_utc"])
            ),
            "clock_drift_search_enabled": bool(clock_drift_search),
            "n_clock_drift_steps": int(len(drift_grid)),
            "best_clock_drift_ppm": float(best_drift * 1e6),
            "n_eff": float(null_full["n_eff_used"]),
            "n_eff_bartlett": float(null_full["n_eff_bartlett"]),
            "n_eff_empirical": float(null_full["n_eff_empirical"]),
            "m_eff": float(null_full["m_eff"]),
            "p_local": float(null_full["p_local"]),
            "max_time_reversed_null_score": null_full["max_time_reversed_null_score"],
            "enf_presence_score": float(enf_presence_score) if enf_presence_score is not None else None,
            "extractor_snr_db": float(extractor_snr_db) if extractor_snr_db is not None else None,
            **split_diag,
        },
        "status": "INCONCLUSIVE",
        "status_reasons": [],
        "what_would_change_this": [],
    }

    return evaluate_policy(
        result,
        claimed_start_utc=claimed_start_utc,
        tolerance_s=claim_tolerance_s,
        thresholds=cfg.get("policy_thresholds"),
    )


def match_baseline_opensource_nate_griff(
    trace: Union[str, Path, dict[str, Any], pd.DataFrame, np.ndarray],
    reference: Union[str, Path, dict[str, Any], pd.DataFrame, np.ndarray],
    search_start_utc: Optional[int] = None,
    search_end_utc: Optional[int] = None,
    cadence_s: float = 1.0,
    threshold_hz: float = 0.010,
) -> dict[str, Any]:
    """
    Faithful reproduction of the open-source baseline `nate-griff/enf` (`enf_compare.py`)
    audited in nate-griff/enf `enf_compare.py` (compared, not vendored):
      - Drops NaN rows via `dropna()` (which collapses gaps and shifts time indices!)
      - Computes unweighted FFT correlation (`r`) and uncentered fraction of points
        within `threshold_hz` (10 mHz)
      - Ranks candidates by `0.4 * corr + 0.6 * pct_within_threshold`
      - Uses a fixed `5.0 s` peak separation
      - Always outputs top-1 argmax (or applies an uncalibrated composite > 0.50 rule).
    """
    t_raw, f_raw, _, _ = _load_trace_input(trace, default_cadence_s=cadence_s)
    ts_ref_raw, f_ref_raw, _ = _load_reference_input(
        reference, search_start_utc=search_start_utc, default_cadence_s=cadence_s
    )
    t_ref_grid, f_y, _ = resample_reference_regular(
        ts_ref_raw, f_ref_raw, search_start_utc, search_end_utc, cadence_s=cadence_s
    )

    # Reproduce nate-griff's dropna() behavior on query
    valid = np.isfinite(f_raw)
    f_x = f_raw[valid]
    L = len(f_x)
    R = len(f_y)
    if L < 2 or R < L:
        return {
            "best": {"start_utc": int(search_start_utc or 0), "score": 0.0, "corr": 0.0},
            "status": "INCONCLUSIVE",
        }

    # Unweighted sliding correlation via FFT
    x_zm = f_x - np.mean(f_x)
    sx = float(np.linalg.norm(x_zm))
    n_lags = R - L + 1
    if sx <= 1e-12:
        corr = np.zeros(n_lags, dtype=np.float64)
    else:
        cross = signal.fftconvolve(f_y, x_zm[::-1], mode="valid")
        sum_y = signal.fftconvolve(f_y, np.ones(L), mode="valid")
        sum_y2 = signal.fftconvolve(f_y * f_y, np.ones(L), mode="valid")
        var_y = np.maximum(0.0, sum_y2 - (sum_y * sum_y) / L)
        corr = np.where(var_y > 1e-18, cross / (sx * np.sqrt(var_y)), 0.0)
        corr = np.clip(corr, -1.0, 1.0)

    # Top-200 by corr then evaluate uncentered 10 mHz threshold coverage
    top_indices = np.argsort(corr)[::-1][: min(200, n_lags)]
    best_comp = -np.inf
    best_idx = int(top_indices[0])
    best_corr = float(corr[best_idx])
    for idx in top_indices:
        seg_y = f_y[idx : idx + L]
        pct_within = float(np.mean(np.abs(seg_y - f_x) <= threshold_hz))
        comp = 0.4 * max(0.0, float(corr[idx])) + 0.6 * pct_within
        if comp > best_comp:
            best_comp = comp
            best_idx = int(idx)
            best_corr = float(corr[idx])

    # Uncalibrated decision rule: nate-griff has no abstention gate (always returns top-1),
    # or even if gated at corr >= 0.45 / composite >= 0.45:
    return {
        "best": {
            "start_utc": int(round(float(t_ref_grid[best_idx]))),
            "score": float(best_comp),
            "corr": float(best_corr),
        },
        "status_always_top1": "MATCH_SUPPORTED",
        "status_corr_045": "MATCH_SUPPORTED" if best_corr >= 0.45 else "INCONCLUSIVE",
    }


def match_baseline_naive_iid(
    trace: Union[str, Path, dict[str, Any], pd.DataFrame, np.ndarray],
    reference: Union[str, Path, dict[str, Any], pd.DataFrame, np.ndarray],
    search_start_utc: Optional[int] = None,
    search_end_utc: Optional[int] = None,
    cadence_s: float = 1.0,
    alpha: float = 0.01,
) -> dict[str, Any]:
    """
    Baseline M2 (eval/protocol.md §4): Uncalibrated i.i.d. Fisher-z matcher that
    uses nominal sample count N instead of Bartlett's autocorrelation-adjusted N_eff,
    and ignores look-elsewhere or split-half gates.
    """
    t_raw, f_raw, q_raw, _ = _load_trace_input(trace, default_cadence_s=cadence_s)
    ts_ref_raw, f_ref_raw, _ = _load_reference_input(
        reference, search_start_utc=search_start_utc, default_cadence_s=cadence_s
    )
    t_ref_grid, f_y, m_y = resample_reference_regular(
        ts_ref_raw, f_ref_raw, search_start_utc, search_end_utc, cadence_s=cadence_s
    )
    _, f_x, w_x = resample_trace_regular(t_raw, f_raw, q_raw, cadence_s=cadence_s)
    res = sliding_weighted_ncc_and_rmse(f_x, w_x, f_y, m_y)
    scores = res["score"]
    finite = np.isfinite(scores)
    if not np.any(finite):
        return {
            "best": {"start_utc": int(search_start_utc or 0), "score": float("nan")},
            "p_naive_iid": 1.0,
            "status": "INCONCLUSIVE",
        }
    best_idx = int(np.argmax(np.where(finite, scores, -np.inf)))
    best_r = float(scores[best_idx])
    n_nom = int(np.sum(w_x > 0))
    if n_nom <= 3 or best_r <= 0:
        p_iid = 1.0
    else:
        z_stat = math.atanh(min(best_r, 0.999999)) * math.sqrt(n_nom - 3.0)
        p_iid = float(stats.norm.sf(z_stat))
    return {
        "best": {
            "start_utc": int(round(float(t_ref_grid[best_idx]))),
            "score": best_r,
            "rmse_mhz": float(res["rmse_mhz"][best_idx]),
        },
        "p_naive_iid": p_iid,
        "status": "MATCH_SUPPORTED" if p_iid <= alpha else "INCONCLUSIVE",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run GhostClock W10 Calibrated Forensic ENF Matcher."
    )
    parser.add_argument("--trace", required=True, help="Path to query trace (.npz, .csv, .parquet)")
    parser.add_argument("--ref", required=True, help="Path to grid reference (.parquet, .csv, .npz)")
    parser.add_argument("--out", required=True, help="Output JSON path for match result")
    parser.add_argument("--start-utc", type=int, default=None, help="Search start UTC (epoch s)")
    parser.add_argument("--end-utc", type=int, default=None, help="Search end UTC (epoch s)")
    parser.add_argument("--cadence-s", type=float, default=1.0, help="Resampling cadence in seconds")
    parser.add_argument("--clock-drift", action="store_true", help="Enable +/-0.5%% clock-rate search")
    parser.add_argument(
        "--claimed-start-utc",
        type=int,
        default=None,
        help="Optional claimed start UTC (compared ONLY in policy step after blind search)",
    )
    args = parser.parse_args()

    cfg = {
        "cadence_s": args.cadence_s,
        "clock_drift_search": args.clock_drift,
        "claimed_start_utc": args.claimed_start_utc,
    }
    res = match(
        trace=args.trace,
        reference=args.ref,
        search_start_utc=args.start_utc,
        search_end_utc=args.end_utc,
        config=cfg,
    )
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(
        f"[W10 matcher] status={res['status']} | start_utc={res['best']['start_utc']} | "
        f"score={res['best']['score']:.4f} | rmse_mhz={res['best']['rmse_mhz']:.2f} | "
        f"p_emp={res['null']['p_empirical']:.4g} | margin={res['uniqueness']['margin_vs_second']:.4f}"
    )


if __name__ == "__main__":
    main()
