#!/usr/bin/env python3
"""
GhostClock Worker W12: Live Reference Station & Near-Real-Time Feeds
====================================================================
Continuously captures Electrical Network Frequency (ENF) from the laptop's audio
input (microphone near a mains-hum source, or line-in) via `sounddevice` (or
`ffmpeg -f dshow` fallback) or from a recorded audio file (`--mode replay`),
extracts fundamental-equivalent grid frequency at 1 s cadence using a robust
multi-harmonic estimator, writes rolling Parquet + JSON sidecar in the frozen
reference format (`integration/interfaces.md` §2, `source="LOCAL_STATION"`),
records the system clock's NTP offset, cross-checks against Elexon BMRS 15 s
telemetry, and updates a live diagnostic plot and health report.

Usage examples (from repo root):
  # 1. Operator preflight check (NTP offset, audio devices, 4s live harmonic SNR test)
  python work/W12/reference_station.py --mode preflight --out work/W12/live_run

  # 2. Run live reference station for N seconds (0 = indefinitely until Ctrl+C)
  python work/W12/reference_station.py --mode live --duration-s 30 --out work/W12/live_run

  # 3. Replay a recorded WAV file through the station pipeline into frozen Parquet
  python work/W12/reference_station.py --mode replay --in datasets/raw/enf-whu/repo/ENF-WHU-Dataset/H1/001.wav --start-utc 1762000000 --out work/W12/replay_001
"""
from __future__ import annotations

import argparse
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple, Union

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import fft as sp_fft
from scipy import signal
import sounddevice as sd
import soundfile as sf
import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
WORK_DIR = Path(__file__).resolve().parent

NTP_SERVERS = ("time.cloudflare.com", "time.windows.com", "pool.ntp.org")
ELEXON_STREAM_URL = "https://data.elexon.co.uk/bmrs/api/v1/system/frequency/stream"
NETZFREQUENZ_ACT_URL = "https://www.netzfrequenz.info/json/act.json"
HEADERS = {"User-Agent": "GhostClock-W12-ReferenceStation/1.0 (UCL-AgentVerse-2026)"}


# ---------------------------------------------------------------------------
# 1. NTP Offset Measurement & File Utilities
# ---------------------------------------------------------------------------

def query_single_ntp(server: str, timeout: float = 1.5) -> Dict[str, Any]:
    """Query a single SNTP server over UDP port 123 and return offset_s and rtt_s."""
    ntp_delta = 2208988800  # 1970-01-01 - 1900-01-01
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        packet = b"\x1b" + 47 * b"\0"
        t1 = time.time()
        sock.sendto(packet, (server, 123))
        data, _ = sock.recvfrom(1024)
        t4 = time.time()
        sock.close()
        if len(data) >= 48:
            unpacked = struct.unpack("!12I", data[:48])
            t2 = unpacked[8] + float(unpacked[9]) / 2**32 - ntp_delta
            t3 = unpacked[10] + float(unpacked[11]) / 2**32 - ntp_delta
            offset_s = ((t2 - t1) + (t3 - t4)) / 2.0
            rtt_s = (t4 - t1) - (t3 - t2)
            return {
                "server": server,
                "status": "OK",
                "offset_s": round(float(offset_s), 6),
                "rtt_s": round(float(rtt_s), 6),
            }
        return {"server": server, "status": "ERR", "error": "Short NTP reply"}
    except Exception as exc:
        return {"server": server, "status": "ERR", "error": str(exc)}


def measure_ntp_offset(servers: Tuple[str, ...] = NTP_SERVERS) -> Dict[str, Any]:
    """Probe multiple NTP servers in parallel and return median clock offset (true_utc - sys_clock)."""
    with ThreadPoolExecutor(max_workers=len(servers)) as ex:
        results = list(ex.map(query_single_ntp, servers))
    valid = [r for r in results if r.get("status") == "OK"]
    if valid:
        offsets = [r["offset_s"] for r in valid]
        rtts = [r["rtt_s"] for r in valid]
        best_srv = min(valid, key=lambda r: r["rtt_s"])["server"]
        return {
            "measurable": True,
            "offset_s": round(float(np.median(offsets)), 6),
            "rtt_s": round(float(np.min(rtts)), 6),
            "best_server": best_srv,
            "probes": results,
            "probed_at_utc": datetime.now(timezone.utc).isoformat(),
        }
    return {
        "measurable": False,
        "offset_s": 0.0,
        "rtt_s": None,
        "best_server": None,
        "probes": results,
        "probed_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# 2. Multi-Harmonic Real-Time & Vectorized ENF Estimator
# ---------------------------------------------------------------------------

def downsample_to_proc(x: np.ndarray, fs_in: float, fs_proc: float = 1000.0) -> Tuple[np.ndarray, float]:
    """Anti-alias low-pass filter and polyphase resample to fs_proc (default 1000 Hz)."""
    x_zm = np.asarray(x, dtype=np.float64) - float(np.mean(x))
    if abs(fs_in - fs_proc) < 1e-6 or fs_in < fs_proc:
        return x_zm, float(fs_in)
    fs_in_i = int(round(fs_in))
    fs_out_i = int(round(fs_proc))
    g = math.gcd(fs_in_i, fs_out_i)
    up = fs_out_i // g
    down = fs_in_i // g
    x_ds = signal.resample_poly(x_zm, up, down, window=("kaiser", 8.0))
    return x_ds.astype(np.float64), float(fs_out_i)


def extract_stream_array(
    audio: np.ndarray,
    fs_in: float,
    start_utc: float,
    ntp_offset_s: float = 0.0,
    nominal_hz: float = 50.0,
    window_s: float = 8.0,
    hop_s: float = 1.0,
    fs_proc: float = 1000.0,
    harmonics: Tuple[int, ...] = (1, 2, 3, 4, 5, 6),
    estimator_mode: str = "v2_robust_center_aligned",
    min_snr_db: float = 6.0,
    consensus_tol_hz: float = 0.035,
    max_rocof_hz_per_s: float = 0.050,
) -> Dict[str, Any]:
    """
    Run the causal sliding-window station estimator over an audio waveform.

    Modes:
      - `v0_single_50hz_endts`: tracks only h=1 (50 Hz), timestamps at window end t_end.
      - `v1_multiharmonic_endts`: tracks h in {1..6} with CRLB h^2*SNR weighting and
        inter-harmonic consensus outlier rejection, timestamps at window end t_end.
      - `v2_robust_center_aligned` (default): tracks h in {1..6} with CRLB weighting +
        consensus outlier rejection, timestamps at physical window centre
        t_center = t_end - window_s/2 + ntp_offset_s, and applies causal RoCoF gate.
    """
    x, fs = downsample_to_proc(audio, fs_in, fs_proc=fs_proc)
    win_len = int(round(window_s * fs))
    hop_len = int(round(hop_s * fs))

    if len(x) < win_len:
        pad_len = win_len - len(x)
        x = np.pad(x, (pad_len // 2, pad_len - pad_len // 2), mode="reflect" if len(x) > 1 else "constant")

    n_frames = (len(x) - win_len) // hop_len + 1
    strides = (x.strides[0] * hop_len, x.strides[0])
    frames = np.lib.stride_tricks.as_strided(x, shape=(n_frames, win_len), strides=strides)

    win = signal.windows.hann(win_len, sym=False).astype(np.float64)
    nfft = max(65536, 1 << int(math.ceil(math.log2(win_len * 8))))
    freqs = sp_fft.rfftfreq(nfft, d=1.0 / fs)
    df_bin = float(freqs[1] - freqs[0])

    # Frame DC removal + tapering + batched rfft
    frames_tap = (frames - np.mean(frames, axis=1, keepdims=True)) * win[None, :]
    spec_mag = np.abs(sp_fft.rfft(frames_tap, n=nfft, axis=1))
    spec_pow = spec_mag ** 2

    active_harmonics = (1,) if estimator_mode == "v0_single_50hz_endts" else tuple(harmonics)
    H = len(active_harmonics)
    f_fund_h = np.full((n_frames, H), np.nan, dtype=np.float64)
    snr_db_h = np.full((n_frames, H), -20.0, dtype=np.float64)
    weights_h = np.zeros((n_frames, H), dtype=np.float64)

    for j, h in enumerate(active_harmonics):
        f_center = h * nominal_hz
        if f_center >= 0.48 * fs:
            continue
        # Search band: +/- 0.45 Hz in fundamental-equivalent units (scaled by h)
        half_search = max(0.45 * h, 0.5)
        sig_mask = (freqs >= f_center - half_search) & (freqs <= f_center + half_search)
        noise_mask = (
            ((freqs >= f_center - 8.0) & (freqs < f_center - max(1.8, half_search + 0.3)))
            | ((freqs > f_center + max(1.8, half_search + 0.3)) & (freqs <= f_center + 8.0))
        )
        sig_indices = np.where(sig_mask)[0]
        if len(sig_indices) < 3:
            continue

        sub_pow = spec_pow[:, sig_indices]
        local_idx = np.argmax(sub_pow, axis=1)
        peak_bins = sig_indices[local_idx]
        p_sig = sub_pow[np.arange(n_frames), local_idx]

        # Sub-bin Gaussian log-magnitude interpolation
        k_l = np.maximum(0, peak_bins - 1)
        k_c = peak_bins
        k_r = np.minimum(spec_mag.shape[1] - 1, peak_bins + 1)
        row_idx = np.arange(n_frames)
        la = np.log(spec_mag[row_idx, k_l] + 1e-18)
        lb = np.log(spec_mag[row_idx, k_c] + 1e-18)
        lc = np.log(spec_mag[row_idx, k_r] + 1e-18)
        denom = la - 2.0 * lb + lc
        delta = np.where(denom < -1e-18, 0.5 * (la - lc) / (denom - 1e-18), 0.0)
        delta = np.clip(delta, -0.5, 0.5)

        f_est_harmonic = (peak_bins + delta) * df_bin
        f_fund_h[:, j] = f_est_harmonic / float(h)

        # Flanking noise floor median
        if np.any(noise_mask):
            p_noise = np.median(spec_pow[:, noise_mask], axis=1)
        else:
            p_noise = np.full(n_frames, 1e-20)
        snr_lin = (p_sig + 1e-30) / (p_noise + 1e-30)
        snr_db = 10.0 * np.log10(snr_lin)
        snr_db_h[:, j] = snr_db

        # CRLB weighting: w_h ~ h^2 * max(0, SNR_lin - gamma)
        gamma_lin = 10.0 ** (3.0 / 10.0)  # 3 dB floor per harmonic
        w_raw = (float(h) ** 2) * np.maximum(0.0, snr_lin - gamma_lin)
        weights_h[:, j] = w_raw

    # Combine harmonics per frame with consensus outlier filtering
    f_out = np.full(n_frames, np.nan, dtype=np.float64)
    q_out = np.zeros(n_frames, dtype=np.float64)
    best_snr_db = np.max(snr_db_h, axis=1)

    for i in range(n_frames):
        w = weights_h[i].copy()
        fh = f_fund_h[i]
        valid_mask = np.isfinite(fh) & (w > 0.0)
        if not np.any(valid_mask):
            if estimator_mode == "v0_single_50hz_endts" and np.isfinite(fh[0]):
                f_out[i] = fh[0]
                q_out[i] = float(np.clip((snr_db_h[i, 0] - 0.0) / 20.0, 0.0, 1.0))
            continue

        if estimator_mode != "v0_single_50hz_endts" and np.sum(valid_mask) >= 2:
            # Weighted median across valid harmonics for consensus outlier rejection
            idx_v = np.where(valid_mask)[0]
            order = np.argsort(fh[idx_v])
            fh_sorted = fh[idx_v][order]
            w_sorted = w[idx_v][order]
            cdf = np.cumsum(w_sorted) / np.sum(w_sorted)
            f_med = float(fh_sorted[np.searchsorted(cdf, 0.5)])
            inliers = valid_mask & (np.abs(fh - f_med) <= consensus_tol_hz)
            if np.any(inliers):
                valid_mask = inliers

        f_comb = float(np.sum(w[valid_mask] * fh[valid_mask]) / np.sum(w[valid_mask]))
        # Effective combined SNR (top harmonics)
        top_snr_db = float(10.0 * np.log10(np.sum(10.0 ** (snr_db_h[i, valid_mask] / 10.0))))
        q_val = float(np.clip((top_snr_db - min_snr_db) / 18.0, 0.0, 1.0))

        if estimator_mode == "v2_robust_center_aligned" and top_snr_db < min_snr_db:
            f_out[i] = np.nan
            q_out[i] = 0.0
        else:
            f_out[i] = f_comb
            q_out[i] = max(0.05, q_val)

    # Physical range gate [47.0, 52.0] Hz
    bad_range = np.isfinite(f_out) & ((f_out < 47.0) | (f_out > 52.0))
    f_out[bad_range] = np.nan
    q_out[bad_range] = 0.0

    # Causal RoCoF slew-rate outlier filter for v2_robust_center_aligned
    if estimator_mode == "v2_robust_center_aligned" and n_frames >= 3:
        prev_valid_f = np.nan
        prev_valid_idx = -1
        for i in range(n_frames):
            if not np.isfinite(f_out[i]):
                continue
            if np.isfinite(prev_valid_f):
                dt_steps = max(1, i - prev_valid_idx) * hop_s
                max_jump = max_rocof_hz_per_s * min(dt_steps, 4.0)
                if abs(f_out[i] - prev_valid_f) > max_jump:
                    # Causal damped step toward outlier unless next frame confirms it
                    if i + 1 < n_frames and np.isfinite(f_out[i + 1]) and abs(f_out[i + 1] - f_out[i]) < max_rocof_hz_per_s:
                        pass
                    else:
                        f_out[i] = prev_valid_f + np.sign(f_out[i] - prev_valid_f) * (0.25 * max_jump)
                        q_out[i] *= 0.5
            prev_valid_f = f_out[i]
            prev_valid_idx = i

    # Compute timestamps
    # Window i covers [i*hop_s, i*hop_s + window_s] relative to recording start
    t_end_rel = np.arange(n_frames, dtype=np.float64) * hop_s + window_s
    t_center_rel = np.arange(n_frames, dtype=np.float64) * hop_s + 0.5 * window_s

    if estimator_mode == "v2_robust_center_aligned":
        ts_float = start_utc + ntp_offset_s + t_center_rel
        t_rel = t_center_rel
    else:
        ts_float = start_utc + ntp_offset_s + t_end_rel
        t_rel = t_end_rel

    ts_utc = np.round(ts_float).astype(np.int64)

    harmonic_summary = {}
    for j, h in enumerate(active_harmonics):
        hz_label = str(int(round(h * nominal_hz)))
        med_snr = float(np.nanmedian(snr_db_h[:, j]))
        med_f = float(np.nanmedian(f_fund_h[:, j])) if np.any(np.isfinite(f_fund_h[:, j])) else float("nan")
        harmonic_summary[hz_label] = {
            "harmonic_index": h,
            "median_snr_db": round(med_snr, 2),
            "median_fund_equiv_hz": round(med_f, 4) if np.isfinite(med_f) else None,
        }

    return {
        "ts_utc": ts_utc,
        "t_rel_s": t_rel,
        "f_hz": f_out,
        "q": q_out,
        "snr_db_per_frame": best_snr_db,
        "f_harmonics": f_fund_h,
        "snr_harmonics": snr_db_h,
        "harmonic_summary": harmonic_summary,
        "fs_proc": fs,
        "window_s": window_s,
        "hop_s": hop_s,
        "estimator_mode": estimator_mode,
    }


# ---------------------------------------------------------------------------
# 3. Frozen Reference Format Writer & Loader (`source="LOCAL_STATION"`)
# ---------------------------------------------------------------------------

def write_station_parquet(
    ts_utc: np.ndarray,
    f_hz: np.ndarray,
    out_dir: Path,
    basename: str = "local_station",
    grid: str = "GB",
    cadence_s: int = 1,
    ntp_info: Optional[Dict[str, Any]] = None,
    extra_meta: Optional[Dict[str, Any]] = None,
) -> Tuple[Path, Path, Dict[str, Any]]:
    """
    Write regularised 1-second reference Parquet + sidecar JSON atomically
    per `integration/interfaces.md` §2.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pq_path = out_dir / f"{basename}.parquet"
    js_path = out_dir / f"{basename}.json"

    df_raw = pd.DataFrame({
        "ts_utc": np.asarray(ts_utc, dtype=np.int64),
        "f_hz": np.asarray(f_hz, dtype=np.float64),
    })
    df_raw.loc[(df_raw["f_hz"] < 47.0) | (df_raw["f_hz"] > 52.0), "f_hz"] = np.nan
    df_raw = df_raw.drop_duplicates(subset=["ts_utc"], keep="last").sort_values("ts_utc").reset_index(drop=True)

    if not df_raw.empty:
        min_ts = int(df_raw["ts_utc"].iloc[0])
        max_ts = int(df_raw["ts_utc"].iloc[-1])
        grid_df = pd.DataFrame({"ts_utc": np.arange(min_ts, max_ts + 1, cadence_s, dtype=np.int64)})
        df_reg = pd.merge(grid_df, df_raw, on="ts_utc", how="left")
    else:
        min_ts, max_ts = 0, 0
        df_reg = pd.DataFrame({"ts_utc": pd.Series(dtype="int64"), "f_hz": pd.Series(dtype="float64")})

    df_reg["ts_utc"] = df_reg["ts_utc"].astype("int64")
    df_reg["f_hz"] = df_reg["f_hz"].astype("float64")
    df_reg["source"] = "LOCAL_STATION"

    tmp_pq = pq_path.with_suffix(".parquet.tmp")
    df_reg.to_parquet(tmp_pq, index=False, engine="pyarrow")
    os.replace(tmp_pq, pq_path)

    pq_sha = sha256_file(pq_path)
    n_total = int(len(df_reg))
    n_valid = int(df_reg["f_hz"].notna().sum())
    n_missing = int(df_reg["f_hz"].isna().sum())
    frac_valid = round(n_valid / max(1, n_total), 4)

    sidecar: Dict[str, Any] = {
        "source": "LOCAL_STATION",
        "cadence_s": cadence_s,
        "grid": grid,
        "coverage": [min_ts, max_ts],
        "coverage_iso": [
            datetime.fromtimestamp(min_ts, tz=timezone.utc).isoformat() if min_ts else None,
            datetime.fromtimestamp(max_ts, tz=timezone.utc).isoformat() if max_ts else None,
        ],
        "url": "local://work/W12/reference_station.py",
        "sha256": pq_sha,
        "row_count": n_total,
        "valid_count": n_valid,
        "missing_count": n_missing,
        "valid_fraction": frac_valid,
        "ntp_offset_s": ntp_info.get("offset_s") if ntp_info else 0.0,
        "ntp_rtt_s": ntp_info.get("rtt_s") if ntp_info else None,
        "ntp_measurable": ntp_info.get("measurable") if ntp_info else False,
        "ntp_server": ntp_info.get("best_server") if ntp_info else None,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    if extra_meta:
        sidecar.update(extra_meta)

    tmp_js = js_path.with_suffix(".json.tmp")
    tmp_js.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
    os.replace(tmp_js, js_path)

    return pq_path, js_path, sidecar


def load_local_station(
    start_utc: int,
    end_utc: int,
    station_parquet: Union[str, Path] = WORK_DIR / "live_run" / "local_station.parquet",
) -> pd.DataFrame:
    """Load `LOCAL_STATION` reference series in the frozen `load_reference` format."""
    pq_path = Path(station_parquet)
    if not pq_path.exists():
        return pd.DataFrame({"ts_utc": pd.Series(dtype="int64"), "f_hz": pd.Series(dtype="float64")})
    df = pd.read_parquet(pq_path, columns=["ts_utc", "f_hz"])
    df = df[(df["ts_utc"] >= int(start_utc)) & (df["ts_utc"] <= int(end_utc))].copy()
    df["ts_utc"] = df["ts_utc"].astype("int64")
    df["f_hz"] = df["f_hz"].astype("float64")
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# 4. Elexon 15s & Continental Europe Live Feed Pollers + Cross-Check
# ---------------------------------------------------------------------------

def fetch_elexon_15s(start_utc: int, end_utc: int) -> pd.DataFrame:
    """
    Load Elexon 15 s reference series via W02's `load_reference` if available,
    falling back to direct BMRS API query.
    """
    try:
        sys.path.insert(0, str(REPO_ROOT / "work" / "W02"))
        from gb_reference import load_reference as w02_load_reference
        df = w02_load_reference(int(start_utc), int(end_utc), source="ELEXON", allow_network=True)
        if not df.empty:
            return df
    except Exception:
        pass

    t0_iso = datetime.fromtimestamp(int(start_utc) - 30, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    t1_iso = datetime.fromtimestamp(int(end_utc) + 30, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = requests.get(
        ELEXON_STREAM_URL,
        params={"from": t0_iso, "to": t1_iso},
        headers=HEADERS,
        timeout=15,
    )
    r.raise_for_status()
    rows = r.json()
    if not rows:
        return pd.DataFrame({"ts_utc": pd.Series(dtype="int64"), "f_hz": pd.Series(dtype="float64")})
    df = pd.DataFrame(rows)
    ts_sec = pd.to_datetime(df["measurementTime"], utc=True).dt.as_unit("s").astype("int64").to_numpy(dtype=np.int64)
    f_vals = pd.to_numeric(df["frequency"], errors="coerce").to_numpy(dtype=np.float64)
    f_vals[(f_vals < 47.0) | (f_vals > 52.0)] = np.nan
    out = pd.DataFrame({"ts_utc": ts_sec, "f_hz": f_vals}).drop_duplicates("ts_utc").sort_values("ts_utc")
    return out[(out["ts_utc"] >= int(start_utc)) & (out["ts_utc"] <= int(end_utc))].reset_index(drop=True)


def poll_netzfrequenz_ce_series(duration_s: int = 15, interval_s: float = 1.0) -> pd.DataFrame:
    """Poll Continental Europe live 1s frequency from netzfrequenz.info/json/act.json."""
    rows = []
    t_end = time.time() + duration_s
    while time.time() < t_end:
        t0 = time.time()
        try:
            r = requests.get(NETZFREQUENZ_ACT_URL, headers=HEADERS, timeout=2.5)
            if r.status_code == 200:
                val = float(r.text.strip())
                rows.append({"ts_utc": int(round(time.time())), "f_hz": val})
        except Exception:
            pass
        elapsed = time.time() - t0
        sleep_s = max(0.05, interval_s - elapsed)
        if time.time() + sleep_s <= t_end + 0.5:
            time.sleep(sleep_s)
        else:
            break
    if not rows:
        return pd.DataFrame({"ts_utc": pd.Series(dtype="int64"), "f_hz": pd.Series(dtype="float64")})
    return pd.DataFrame(rows).drop_duplicates("ts_utc").sort_values("ts_utc").reset_index(drop=True)


def crosscheck_station_vs_15s_ref(
    df_station_1s: pd.DataFrame,
    df_ref_15s: pd.DataFrame,
    operator: str = "centred_mean_15s",
    max_lag_steps_15s: int = 4,
) -> Dict[str, Any]:
    """
    Cross-check a 1-second station trace against a 15-second reference trace (e.g. Elexon BMRS).

    Operators supported:
      - `point_15s`: instantaneous 1s station sample at exact 15s boundary `ts_utc`
      - `causal_mean_15s`: average of 1s station samples in `[ts_utc - 14, ts_utc]`
      - `centred_mean_15s`: average of 1s station samples in `[ts_utc - 7, ts_utc + 7]`
    """
    if df_station_1s.empty or df_ref_15s.empty:
        return {"status": "NO_OVERLAP", "n_overlap": 0}

    s_map = df_station_1s.dropna(subset=["f_hz"]).set_index("ts_utc")["f_hz"]
    if s_map.empty:
        return {"status": "NO_VALID_STATION_SAMPLES", "n_overlap": 0}

    ref_valid = df_ref_15s.dropna(subset=["f_hz"]).sort_values("ts_utc").reset_index(drop=True)
    ts_ref = ref_valid["ts_utc"].to_numpy(dtype=np.int64)
    f_ref = ref_valid["f_hz"].to_numpy(dtype=np.float64)

    f_stat_15s = np.full(len(ts_ref), np.nan, dtype=np.float64)
    s_ts_min, s_ts_max = int(s_map.index.min()), int(s_map.index.max())

    for idx, t in enumerate(ts_ref):
        if t < s_ts_min - 7 or t > s_ts_max + 7:
            continue
        if operator == "point_15s":
            if t in s_map:
                f_stat_15s[idx] = float(s_map.loc[t])
        elif operator == "causal_mean_15s":
            vals = [s_map.loc[tau] for tau in range(t - 14, t + 1) if tau in s_map]
            if len(vals) >= 8:
                f_stat_15s[idx] = float(np.mean(vals))
        else:  # centred_mean_15s
            vals = [s_map.loc[tau] for tau in range(t - 7, t + 8) if tau in s_map]
            if len(vals) >= 8:
                f_stat_15s[idx] = float(np.mean(vals))

    valid = np.isfinite(f_stat_15s) & np.isfinite(f_ref)
    n_ov = int(np.sum(valid))
    if n_ov < 3:
        return {"status": "INSUFFICIENT_OVERLAP", "n_overlap": n_ov}

    x = f_stat_15s[valid]
    y = f_ref[valid]
    diff_mhz = (x - y) * 1000.0
    rmse_0 = float(np.sqrt(np.mean(diff_mhz ** 2)))
    mae_0 = float(np.mean(np.abs(diff_mhz)))
    bias_0 = float(np.mean(diff_mhz))
    r_0 = float(np.corrcoef(x, y)[0, 1]) if (np.std(x) > 1e-9 and np.std(y) > 1e-9) else 0.0

    # Lag scan in 15s steps (and 1s fine lag scan if 1s station series is contiguous)
    lag_scan_15s = {}
    best_lag_s = 0
    best_r = r_0
    best_rmse = rmse_0

    for k in range(-max_lag_steps_15s, max_lag_steps_15s + 1):
        lag_s = k * 15
        if k < 0:
            xk, yk = x[-k:], y[: len(y) + k]
        elif k > 0:
            xk, yk = x[: len(x) - k], y[k:]
        else:
            xk, yk = x, y
        if len(xk) < 3 or np.std(xk) < 1e-9 or np.std(yk) < 1e-9:
            continue
        rk = float(np.corrcoef(xk, yk)[0, 1])
        rmsek = float(np.sqrt(np.mean(((xk - yk) * 1000.0) ** 2)))
        lag_scan_15s[str(lag_s)] = {"r": round(rk, 6), "rmse_mhz": round(rmsek, 4)}
        if rk > best_r + 1e-6:
            best_r = rk
            best_lag_s = lag_s
            best_rmse = rmsek

    # Fine 1-second lag scan between 1s station and 15s reference
    fine_lag_scan = {}
    fine_best_lag_s = 0
    fine_best_r = -2.0
    for lag_1s in range(-15, 16):
        shifted_vals = []
        ref_sub = []
        for idx, t in enumerate(ts_ref):
            t_q = t + lag_1s
            if operator == "point_15s":
                if t_q in s_map:
                    shifted_vals.append(float(s_map.loc[t_q]))
                    ref_sub.append(float(f_ref[idx]))
            else:
                vals = [s_map.loc[tau] for tau in range(t_q - 7, t_q + 8) if tau in s_map]
                if len(vals) >= 8:
                    shifted_vals.append(float(np.mean(vals)))
                    ref_sub.append(float(f_ref[idx]))
        if len(shifted_vals) >= 4:
            xa = np.asarray(shifted_vals)
            ya = np.asarray(ref_sub)
            if np.std(xa) > 1e-9 and np.std(ya) > 1e-9:
                rl = float(np.corrcoef(xa, ya)[0, 1])
                rmsel = float(np.sqrt(np.mean(((xa - ya) * 1000.0) ** 2)))
                fine_lag_scan[str(lag_1s)] = {"r": round(rl, 5), "rmse_mhz": round(rmsel, 3)}
                if rl > fine_best_r:
                    fine_best_r = rl
                    fine_best_lag_s = int(lag_1s)

    return {
        "status": "OK",
        "operator": operator,
        "n_overlap_15s": n_ov,
        "pearson_r_lag0": round(r_0, 6),
        "rmse_lag0_mhz": round(rmse_0, 4),
        "mae_lag0_mhz": round(mae_0, 4),
        "offset_bias_mhz": round(bias_0, 4),
        "best_lag_15s_step_s": best_lag_s,
        "best_r_15s_step": round(best_r, 6),
        "best_rmse_15s_step_mhz": round(best_rmse, 4),
        "fine_best_lag_s": fine_best_lag_s,
        "fine_best_r": round(fine_best_r, 6) if fine_best_r > -1.0 else None,
        "lag_scan_15s": lag_scan_15s,
        "fine_lag_scan_1s": fine_lag_scan,
        "aligned_ts_utc": ts_ref[valid].tolist(),
        "aligned_station_hz": np.round(x, 5).tolist(),
        "aligned_ref_hz": np.round(y, 5).tolist(),
    }


# ---------------------------------------------------------------------------
# 5. Live Diagnostic Plot & Health Check Generator
# ---------------------------------------------------------------------------

def evaluate_health_status(
    res: Dict[str, Any],
    audio_rms: float,
    audio_peak: float,
    ntp_info: Dict[str, Any],
    crosscheck: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compute deterministic station health status and operator diagnostics."""
    f_hz = res["f_hz"]
    snr_db = res["snr_db_per_frame"]
    n_total = len(f_hz)
    n_valid = int(np.sum(np.isfinite(f_hz)))
    frac_valid = float(n_valid / max(1, n_total))
    med_snr_db = float(np.nanmedian(snr_db)) if len(snr_db) else -20.0
    clipping = bool(audio_peak >= 0.98)
    silence = bool(audio_rms < 1e-5)

    reasons = []
    if silence:
        status = "SILENCE_OR_MUTED_MIC"
        reasons.append(f"Audio RMS ({audio_rms:.2e}) is near digital zero; check microphone mute switch or permissions.")
    elif clipping:
        status = "CLIPPING_WARNING"
        reasons.append(f"Audio peak ({audio_peak:.3f}) is saturating ADC (>=0.98); move mic slightly further from source or lower input gain.")
    elif frac_valid < 0.50 or med_snr_db < 6.0:
        status = "NO_MAINS_HUM_LOW_SNR"
        reasons.append(
            f"Valid ENF fraction is {frac_valid:.1%} (median harmonic SNR {med_snr_db:.1f} dB < 6.0 dB threshold). "
            "Place microphone within 2-10 cm of an AC/DC transformer, charger, or extension lead, and disable Windows 'Voice Focus' / SST noise suppression."
        )
    elif frac_valid < 0.85 or med_snr_db < 10.0:
        status = "DEGRADED_LOW_SNR"
        reasons.append(f"Moderate SNR ({med_snr_db:.1f} dB, valid {frac_valid:.1%}); station usable but move closer to hum source for <2 mHz precision.")
    else:
        status = "HEALTHY"
        reasons.append(f"Strong multi-harmonic mains lock (median SNR {med_snr_db:.1f} dB, {frac_valid:.1%} valid frames).")

    if not ntp_info.get("measurable", False):
        reasons.append("NTP UDP port 123 unreachable; falling back to local system UTC clock.")
    elif abs(ntp_info.get("offset_s", 0.0)) > 0.5:
        reasons.append(f"System clock offset is {ntp_info['offset_s']:+.3f} s (auto-corrected in station Parquet).")

    health = {
        "status": status,
        "reasons": reasons,
        "metrics": {
            "total_seconds": n_total,
            "valid_seconds": n_valid,
            "valid_fraction": round(frac_valid, 4),
            "median_harmonic_snr_db": round(med_snr_db, 2),
            "audio_rms": round(float(audio_rms), 6),
            "audio_peak": round(float(audio_peak), 6),
            "clipping_detected": clipping,
            "f_mean_hz": round(float(np.nanmean(f_hz)), 5) if n_valid > 0 else None,
            "f_std_mhz": round(float(np.nanstd(f_hz) * 1000.0), 3) if n_valid > 0 else None,
        },
        "harmonics": res.get("harmonic_summary", {}),
        "ntp": {
            "measurable": ntp_info.get("measurable", False),
            "offset_s": ntp_info.get("offset_s", 0.0),
            "rtt_s": ntp_info.get("rtt_s"),
            "server": ntp_info.get("best_server"),
        },
        "elexon_crosscheck": (
            {
                k: v
                for k, v in crosscheck.items()
                if k not in ("aligned_ts_utc", "aligned_station_hz", "aligned_ref_hz")
            }
            if crosscheck
            else None
        ),
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    return health


def save_station_live_plot(
    res: Dict[str, Any],
    health: Dict[str, Any],
    out_path: Path,
    crosscheck: Optional[Dict[str, Any]] = None,
    title_prefix: str = "GhostClock W12 Live Reference Station",
) -> None:
    """Render a 3-panel station health & Elexon cross-check plot and save atomically."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(3, 1, figsize=(11, 8.5), constrained_layout=True)
    ts = res["ts_utc"]
    t_rel = ts - ts[0] if len(ts) else np.array([])
    f_hz = res["f_hz"]
    q = res["q"]
    snr_db = res["snr_db_per_frame"]

    # Panel 1: 1s Station ENF Trace & 15s Elexon Cross-Check Overlay
    ax0 = axes[0]
    if np.any(np.isfinite(f_hz)):
        ax0.plot(t_rel, f_hz, color="#1f77b4", lw=1.2, alpha=0.85, label="Local Station 1s ENF (f_hz)")
    else:
        ax0.text(
            0.5, 0.5,
            f"NO VALID MAINS HUM LOCK ({health['status']})\nOutput gated to NaN (Risk Control Triggered)",
            transform=ax0.transAxes, ha="center", va="center",
            fontsize=11, fontweight="bold", color="#d62728",
            bbox=dict(boxstyle="round,pad=0.5", facecolor="#ffecec", edgecolor="#d62728")
        )
    if crosscheck and crosscheck.get("status") == "OK" and crosscheck.get("aligned_ts_utc"):
        cc_t = np.asarray(crosscheck["aligned_ts_utc"]) - (ts[0] if len(ts) else 0)
        cc_s = np.asarray(crosscheck["aligned_station_hz"])
        cc_r = np.asarray(crosscheck["aligned_ref_hz"])
        ax0.plot(cc_t, cc_s, "o-", color="#2ca02c", ms=4, lw=1.5, label="Station 15s Avg")
        ax0.plot(cc_t, cc_r, "s--", color="#ff7f0e", ms=4, lw=1.5, label="Reference 15s (Elexon/Grid)")
        ax0.set_title(
            f"{title_prefix} — Status: {health['status']} | "
            f"15s Cross-Check: r={crosscheck['pearson_r_lag0']:.4f}, "
            f"RMSE={crosscheck['rmse_lag0_mhz']:.2f} mHz, Lag={crosscheck['fine_best_lag_s']}s",
            fontsize=11, fontweight="bold"
        )
    else:
        ax0.set_title(
            f"{title_prefix} — Status: {health['status']} | "
            f"Valid: {health['metrics']['valid_fraction']*100:.1f}% | "
            f"NTP Offset: {health['ntp']['offset_s']:+.3f}s",
            fontsize=11, fontweight="bold"
        )
    ax0.axhline(50.0, color="gray", ls=":", lw=0.9)
    ax0.set_ylabel("Frequency (Hz)")
    ax0.set_xlabel("Time (s from start)")
    ax0.grid(True, alpha=0.3)
    ax0.legend(loc="upper right", fontsize=9)

    # Panel 2: Rolling SNR (dB) and Quality Score q(t)
    ax1 = axes[1]
    if len(t_rel):
        ax1.plot(t_rel, snr_db, color="#9467bd", lw=1.2, label="Peak Harmonic SNR (dB)")
        ax1.axhline(6.0, color="#d62728", ls="--", lw=1.0, label="Quality Gate Threshold (6.0 dB)")
    ax1.set_ylabel("Harmonic SNR (dB)")
    ax1.set_xlabel("Time (s from start)")
    ax1.grid(True, alpha=0.3)
    ax1_r = ax1.twinx()
    if len(t_rel):
        ax1_r.fill_between(t_rel, 0, q, color="#2ca02c", alpha=0.18, label="Quality q(t)")
        ax1_r.set_ylim(0, 1.05)
    ax1_r.set_ylabel("Quality q(t) [0-1]")
    ax1.legend(loc="upper left", fontsize=9)

    # Panel 3: Per-Harmonic Median SNR Bar Chart (50..300 Hz)
    ax2 = axes[2]
    h_sum = health.get("harmonics", {})
    labels = sorted(h_sum.keys(), key=lambda k: int(k))
    snrs = [h_sum[k]["median_snr_db"] for k in labels]
    colors = ["#2ca02c" if s >= 6.0 else ("#ff7f0e" if s >= 3.0 else "#d62728") for s in snrs]
    if labels:
        bars = ax2.bar([f"{k} Hz\n(H{h_sum[k]['harmonic_index']})" for k in labels], snrs, color=colors, alpha=0.85, width=0.5)
        ax2.axhline(6.0, color="#d62728", ls="--", lw=1.0, label="6 dB Lock Threshold")
        for b, s in zip(bars, snrs):
            ax2.text(b.get_x() + b.get_width() / 2.0, max(0.5, s + 0.5), f"{s:.1f} dB", ha="center", va="bottom", fontsize=8.5)
    ax2.set_ylabel("Median SNR (dB)")
    ax2.set_title("Per-Harmonic Acoustic Coupling Diagnostics (50 Hz – 300 Hz)", fontsize=10, fontweight="bold")
    ax2.grid(True, axis="y", alpha=0.3)

    tmp_png = out_path.with_suffix(".tmp.png")
    fig.savefig(tmp_png, dpi=140)
    plt.close(fig)
    os.replace(tmp_png, out_path)


# ---------------------------------------------------------------------------
# 6. Live Capture & Operator Preflight Loops
# ---------------------------------------------------------------------------

def run_preflight(out_dir: Path, device: Optional[int] = None, duration_s: float = 4.0) -> Dict[str, Any]:
    """Run operator preflight check: audio devices, NTP offset, and 4s live capture."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ntp_info = measure_ntp_offset()

    devs = sd.query_devices()
    input_devs = []
    for idx, d in enumerate(devs):
        if d.get("max_input_channels", 0) > 0:
            input_devs.append({
                "index": idx,
                "name": d.get("name"),
                "hostapi": d.get("hostapi"),
                "max_input_channels": d.get("max_input_channels"),
                "default_samplerate": d.get("default_samplerate"),
            })

    fs = 8000
    t_start = time.time() - duration_s
    try:
        rec = sd.rec(int(duration_s * fs), samplerate=fs, channels=1, dtype="float64", device=device)
        sd.wait()
        x = rec[:, 0]
        rms = float(np.sqrt(np.mean(x ** 2)))
        peak = float(np.max(np.abs(x)))
        res = extract_stream_array(
            x, fs_in=fs, start_utc=t_start, ntp_offset_s=ntp_info["offset_s"],
            window_s=min(4.0, duration_s), hop_s=1.0,
        )
        health = evaluate_health_status(res, rms, peak, ntp_info)
    except Exception as exc:
        health = {"status": "AUDIO_CAPTURE_ERROR", "error": str(exc), "ntp": ntp_info}

    report = {
        "preflight_at_utc": datetime.now(timezone.utc).isoformat(),
        "ntp": ntp_info,
        "input_devices": input_devs,
        "health": health,
    }
    (out_dir / "preflight_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def run_live_station(
    out_dir: Path,
    duration_s: float = 20.0,
    device: Optional[int] = None,
    fs: int = 8000,
    window_s: float = 8.0,
    backend: str = "sounddevice",
    ffmpeg_device_name: Optional[str] = None,
    crosscheck_elexon: bool = True,
) -> Dict[str, Any]:
    """
    Continuously capture audio from microphone/line-in in real time, extract 1s ENF,
    write rolling frozen Parquet + JSON sidecar, and cross-check against Elexon 15s.
    Safe to run for hours (bounded circular audio buffer of size `window_s * fs`).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ntp_info = measure_ntp_offset()

    ring_samples = int(round(window_s * fs))
    hop_samples = int(round(1.0 * fs))
    ring_buf = np.zeros(ring_samples, dtype=np.float64)
    samples_collected = 0

    # Keep rolling history of 1s estimates (bounded deque for up to 24h = 86,400 points)
    history_ts: deque[int] = deque(maxlen=86400)
    history_f: deque[float] = deque(maxlen=86400)
    history_q: deque[float] = deque(maxlen=86400)
    history_snr: deque[float] = deque(maxlen=86400)
    last_harmonics: Dict[str, Any] = {}
    max_peak_seen = 0.0
    sum_sq_seen = 0.0
    total_samples_seen = 0

    t_run_start = time.time()
    steps_target = int(round(duration_s)) if duration_s > 0 else 0
    steps_done = 0

    def process_one_hop(new_chunk: np.ndarray, t_chunk_end: float) -> None:
        nonlocal ring_buf, samples_collected, last_harmonics, max_peak_seen, sum_sq_seen, total_samples_seen
        n_c = len(new_chunk)
        if n_c >= ring_samples:
            ring_buf[:] = new_chunk[-ring_samples:]
        else:
            ring_buf[:-n_c] = ring_buf[n_c:]
            ring_buf[-n_c:] = new_chunk
        samples_collected += n_c
        max_peak_seen = max(max_peak_seen, float(np.max(np.abs(new_chunk))))
        sum_sq_seen += float(np.sum(new_chunk ** 2))
        total_samples_seen += n_c

        if samples_collected >= ring_samples:
            win_start_sys = t_chunk_end - window_s
            res_step = extract_stream_array(
                ring_buf, fs_in=fs, start_utc=win_start_sys,
                ntp_offset_s=ntp_info["offset_s"], window_s=window_s, hop_s=1.0,
            )
            history_ts.append(int(res_step["ts_utc"][0]))
            history_f.append(float(res_step["f_hz"][0]))
            history_q.append(float(res_step["q"][0]))
            history_snr.append(float(res_step["snr_db_per_frame"][0]))
            last_harmonics = res_step["harmonic_summary"]

    if backend == "ffmpeg":
        # FFmpeg dshow input fallback on Windows
        dev_str = ffmpeg_device_name or "Microphone Array (Intel® Smart Sound Technology for Digital Microphones)"
        cmd = [
            "ffmpeg", "-nostdin", "-v", "error",
            "-f", "dshow", "-i", f"audio={dev_str}",
            "-ac", "1", "-ar", str(fs), "-f", "f32le", "pipe:1",
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            while True:
                raw_bytes = proc.stdout.read(hop_samples * 4) if proc.stdout else b""
                if len(raw_bytes) < hop_samples * 4:
                    break
                chunk = np.frombuffer(raw_bytes, dtype=np.float32).astype(np.float64)
                process_one_hop(chunk, time.time())
                steps_done += 1
                if steps_target > 0 and steps_done >= steps_target:
                    break
        finally:
            proc.terminate()
    else:
        # sounddevice InputStream (continuous gapless callback/blocking stream)
        with sd.InputStream(samplerate=fs, channels=1, dtype="float32", device=device, blocksize=hop_samples) as stream:
            while True:
                data, overflowed = stream.read(hop_samples)
                t_now = time.time()
                chunk = data[:, 0].astype(np.float64)
                process_one_hop(chunk, t_now)
                steps_done += 1

                # Flush Parquet every 5 seconds or at end of run
                if len(history_ts) > 0 and (steps_done % 5 == 0 or (steps_target > 0 and steps_done >= steps_target)):
                    write_station_parquet(
                        np.array(history_ts, dtype=np.int64),
                        np.array(history_f, dtype=np.float64),
                        out_dir=out_dir,
                        ntp_info=ntp_info,
                    )
                if steps_target > 0 and steps_done >= steps_target:
                    break

    ts_arr = np.array(history_ts, dtype=np.int64)
    f_arr = np.array(history_f, dtype=np.float64)
    q_arr = np.array(history_q, dtype=np.float64)
    snr_arr = np.array(history_snr, dtype=np.float64)
    overall_rms = math.sqrt(sum_sq_seen / max(1, total_samples_seen))

    agg_res = {
        "ts_utc": ts_arr,
        "f_hz": f_arr,
        "q": q_arr,
        "snr_db_per_frame": snr_arr,
        "harmonic_summary": last_harmonics,
    }

    cc_res = None
    if crosscheck_elexon and len(ts_arr) > 0:
        try:
            df_el = fetch_elexon_15s(int(ts_arr[0]) - 600, int(ts_arr[-1]) + 60)
            df_st = pd.DataFrame({"ts_utc": ts_arr, "f_hz": f_arr})
            cc_res = crosscheck_station_vs_15s_ref(df_st, df_el, operator="centred_mean_15s")
            cc_res["elexon_rows_in_window"] = int(len(df_el))
        except Exception as exc:
            cc_res = {"status": "ERR", "error": str(exc)}

    health = evaluate_health_status(agg_res, overall_rms, max_peak_seen, ntp_info, crosscheck=cc_res)
    pq_path, js_path, sidecar = write_station_parquet(
        ts_arr, f_arr, out_dir=out_dir, ntp_info=ntp_info,
        extra_meta={"health_status": health["status"], "median_snr_db": health["metrics"]["median_harmonic_snr_db"]},
    )
    (out_dir / "station_health.json").write_text(json.dumps(health, indent=2), encoding="utf-8")
    save_station_live_plot(agg_res, health, out_dir / "station_live_plot.png", crosscheck=cc_res)

    return {
        "parquet_path": str(pq_path),
        "sidecar_path": str(js_path),
        "health_path": str(out_dir / "station_health.json"),
        "plot_path": str(out_dir / "station_live_plot.png"),
        "sidecar": sidecar,
        "health": health,
    }


def run_replay_station(
    audio_path: Path,
    out_dir: Path,
    start_utc: int = 1762000000,
    ref_audio_path: Optional[Path] = None,
    ref_df_15s: Optional[pd.DataFrame] = None,
    window_s: float = 8.0,
    estimator_mode: str = "v2_robust_center_aligned",
) -> Dict[str, Any]:
    """Run station pipeline on a recorded audio file (`--mode replay`) and output frozen Parquet + plots."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ntp_info = measure_ntp_offset()

    x, fs = sf.read(str(audio_path), dtype="float64")
    if x.ndim > 1:
        x = np.mean(x, axis=1)
    rms = float(np.sqrt(np.mean(x ** 2)))
    peak = float(np.max(np.abs(x)))

    # Replay file timestamps are anchored to start_utc directly (ntp_offset_s=0 for historical files)
    res = extract_stream_array(
        x, fs_in=float(fs), start_utc=float(start_utc), ntp_offset_s=0.0,
        window_s=window_s, hop_s=1.0, estimator_mode=estimator_mode,
    )

    cc_res = None
    if ref_audio_path and Path(ref_audio_path).exists():
        xr, fsr = sf.read(str(ref_audio_path), dtype="float64")
        if xr.ndim > 1:
            xr = np.mean(xr, axis=1)
        res_ref = extract_stream_array(
            xr, fs_in=float(fsr), start_utc=float(start_utc), ntp_offset_s=0.0,
            window_s=window_s, hop_s=1.0, harmonics=(1,), estimator_mode="v2_robust_center_aligned",
            min_snr_db=-10.0,
        )
        # Build 15s reference from 1s reference
        df_ref_1s = pd.DataFrame({"ts_utc": res_ref["ts_utc"], "f_hz": res_ref["f_hz"]})
        ts_15 = df_ref_1s["ts_utc"].to_numpy()
        mask_15 = (ts_15 - ts_15[0]) % 15 == 0
        # Use 15s centred average of ref to mimic 15s reference
        ref_15_rows = []
        s_ref = df_ref_1s.set_index("ts_utc")["f_hz"]
        for t in ts_15[mask_15]:
            vals = [s_ref.loc[tau] for tau in range(t - 7, t + 8) if tau in s_ref]
            if len(vals) >= 8:
                ref_15_rows.append({"ts_utc": int(t), "f_hz": float(np.mean(vals))})
        ref_df_15s = pd.DataFrame(ref_15_rows)

    if ref_df_15s is not None and not ref_df_15s.empty:
        df_st = pd.DataFrame({"ts_utc": res["ts_utc"], "f_hz": res["f_hz"]})
        cc_res = crosscheck_station_vs_15s_ref(df_st, ref_df_15s, operator="centred_mean_15s")

    health = evaluate_health_status(res, rms, peak, ntp_info, crosscheck=cc_res)
    pq_path, js_path, sidecar = write_station_parquet(
        res["ts_utc"], res["f_hz"], out_dir=out_dir, ntp_info=ntp_info,
        extra_meta={
            "replay_source_file": str(audio_path),
            "estimator_mode": estimator_mode,
            "health_status": health["status"],
            "median_snr_db": health["metrics"]["median_harmonic_snr_db"],
        },
    )
    (out_dir / "station_health.json").write_text(json.dumps(health, indent=2), encoding="utf-8")
    save_station_live_plot(
        res, health, out_dir / "station_live_plot.png", crosscheck=cc_res,
        title_prefix=f"W12 Reference Station Replay ({Path(audio_path).name})",
    )
    return {
        "parquet_path": str(pq_path),
        "sidecar_path": str(js_path),
        "health_path": str(out_dir / "station_health.json"),
        "plot_path": str(out_dir / "station_live_plot.png"),
        "sidecar": sidecar,
        "health": health,
        "crosscheck": cc_res,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="GhostClock W12 Live Reference Station & Replay CLI")
    parser.add_argument("--mode", choices=["preflight", "live", "replay"], default="preflight")
    parser.add_argument("--in", dest="in_path", type=str, default=None, help="Input WAV path for --mode replay")
    parser.add_argument("--ref-in", dest="ref_path", type=str, default=None, help="Optional reference WAV path for --mode replay")
    parser.add_argument("--out", dest="out_dir", type=str, default=str(WORK_DIR / "live_run"), help="Output directory")
    parser.add_argument("--duration-s", type=float, default=16.0, help="Duration in seconds for live capture (0=indefinite)")
    parser.add_argument("--start-utc", type=int, default=1762000000, help="Start UTC epoch seconds for replay mode")
    parser.add_argument("--device", type=int, default=None, help="Sounddevice input device index")
    parser.add_argument("--backend", choices=["sounddevice", "ffmpeg"], default="sounddevice")
    parser.add_argument("--window-s", type=float, default=8.0, help="Sliding STFT window length in seconds")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    if args.mode == "preflight":
        rep = run_preflight(out_dir, device=args.device, duration_s=min(4.0, args.duration_s))
        print(json.dumps(rep["health"], indent=2))
    elif args.mode == "live":
        res = run_live_station(
            out_dir=out_dir, duration_s=args.duration_s, device=args.device,
            window_s=args.window_s, backend=args.backend,
        )
        print(json.dumps({"sidecar": res["sidecar"], "health_status": res["health"]["status"]}, indent=2))
    elif args.mode == "replay":
        if not args.in_path:
            raise ValueError("--in <audio_path> is required for --mode replay")
        res = run_replay_station(
            audio_path=Path(args.in_path),
            out_dir=out_dir,
            start_utc=args.start_utc,
            ref_audio_path=Path(args.ref_path) if args.ref_path else None,
            window_s=args.window_s,
        )
        print(json.dumps({"sidecar": res["sidecar"], "health_status": res["health"]["status"]}, indent=2))


if __name__ == "__main__":
    main()
