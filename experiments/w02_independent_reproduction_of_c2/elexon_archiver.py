"""
Live Elexon BMRS 15-second Frequency Archiver (W02).
Polls Elexon BMRS (/system/frequency/stream) every N minutes and appends
new readings to datasets/raw/elexon/live_archive.parquet (and updates live_archive.json)
without duplicates, regularised onto a strict 15-second UTC grid.

Usage:
    # Run continuously (polling every 2 minutes, for the director to run all day):
    python work/W02/elexon_archiver.py --interval-min 2

    # Run a single poll-and-append cycle and exit (for testing / verification):
    python work/W02/elexon_archiver.py --once
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ARCHIVE = REPO_ROOT / "datasets" / "raw" / "elexon" / "live_archive.parquet"
STREAM_URL = "https://data.elexon.co.uk/bmrs/api/v1/system/frequency/stream"
HEADERS = {"User-Agent": "GhostClock-W02-ElexonArchiver/1.0 (UCL-AgentVerse-2026)"}


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    retry = Retry(
        total=5,
        backoff_factor=0.6,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    return s


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def poll_once(
    sess: requests.Session,
    archive_path: Path,
    lookback_hours: float = 2.0,
    initial_backfill_days: int = 7,
) -> dict:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path = archive_path.with_suffix(".json")

    now_utc = datetime.now(timezone.utc)
    if archive_path.exists():
        df_existing = pd.read_parquet(archive_path)
        prev_rows = int(len(df_existing))
        prev_valid = int(df_existing["f_hz"].notna().sum()) if not df_existing.empty else 0
        if not df_existing.empty:
            last_valid_ts = int(df_existing.loc[df_existing["f_hz"].notna(), "ts_utc"].max())
            # Overlap by lookback_hours to fill any recently arrived batches
            fetch_start = datetime.fromtimestamp(last_valid_ts, tz=timezone.utc) - timedelta(hours=lookback_hours)
        else:
            fetch_start = now_utc - timedelta(days=initial_backfill_days)
    else:
        df_existing = pd.DataFrame(
            {"ts_utc": pd.Series(dtype="int64"), "f_hz": pd.Series(dtype="float64"), "source": pd.Series(dtype="str")}
        )
        prev_rows = 0
        prev_valid = 0
        fetch_start = datetime(now_utc.year, now_utc.month, now_utc.day, tzinfo=timezone.utc) - timedelta(
            days=initial_backfill_days
        )

    fetch_end = now_utc + timedelta(minutes=5)
    r = sess.get(
        STREAM_URL,
        params={
            "from": fetch_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "to": fetch_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        timeout=30,
    )
    r.raise_for_status()
    srv_date_hdr = r.headers.get("Date")
    srv_dt = parsedate_to_datetime(srv_date_hdr) if srv_date_hdr else now_utc
    payload = r.json()

    if payload:
        df_new = pd.DataFrame(payload)
        ts_sec = (
            pd.to_datetime(df_new["measurementTime"], utc=True)
            .dt.as_unit("s")
            .astype("int64")
            .to_numpy(dtype=np.int64)
        )
        f_vals = pd.to_numeric(df_new["frequency"], errors="coerce").to_numpy(dtype=np.float64, copy=True)
        # Physical GB grid frequency gate [47.0, 52.0] Hz to reject SCADA dropout sentinels (e.g. 0.0 Hz)
        f_vals[(f_vals < 47.0) | (f_vals > 52.0)] = np.nan
        df_incoming = pd.DataFrame({"ts_utc": ts_sec, "f_hz": f_vals})
    else:
        df_incoming = pd.DataFrame({"ts_utc": pd.Series(dtype="int64"), "f_hz": pd.Series(dtype="float64")})

    if not df_existing.empty:
        df_existing_valid = df_existing.loc[df_existing["f_hz"].notna(), ["ts_utc", "f_hz"]]
        combined = pd.concat([df_existing_valid, df_incoming], ignore_index=True)
    else:
        combined = df_incoming

    if combined.empty:
        return {"status": "empty", "polled_at_utc": srv_dt.isoformat()}

    # Deduplicate keeping the latest non-null reading per timestamp
    combined = combined.dropna(subset=["f_hz"]).drop_duplicates(subset=["ts_utc"], keep="last").sort_values("ts_utc")
    min_ts = int(combined["ts_utc"].iloc[0])
    max_ts = int(combined["ts_utc"].iloc[-1])

    # Regularise onto exact 15s grid
    full_grid = pd.DataFrame({"ts_utc": np.arange(min_ts, max_ts + 1, 15, dtype=np.int64)})
    df_reg = pd.merge(full_grid, combined[["ts_utc", "f_hz"]], on="ts_utc", how="left")
    df_reg["ts_utc"] = df_reg["ts_utc"].astype("int64")
    df_reg["f_hz"] = df_reg["f_hz"].astype("float64")
    df_reg["source"] = "ELEXON"

    # Atomic write via temporary file
    tmp_pq = archive_path.with_suffix(".parquet.tmp")
    df_reg.to_parquet(tmp_pq, index=False, engine="pyarrow")
    os.replace(tmp_pq, archive_path)

    pq_sha = sha256_file(archive_path)
    new_valid = int(df_reg["f_hz"].notna().sum())
    added_valid = max(0, new_valid - prev_valid)
    latency_s = float((srv_dt - datetime.fromtimestamp(max_ts, tz=timezone.utc)).total_seconds())

    sidecar = {
        "source": "ELEXON",
        "cadence_s": 15,
        "grid": "GB",
        "coverage": [min_ts, max_ts],
        "coverage_iso": [
            datetime.fromtimestamp(min_ts, tz=timezone.utc).isoformat(),
            datetime.fromtimestamp(max_ts, tz=timezone.utc).isoformat(),
        ],
        "url": STREAM_URL,
        "sha256": pq_sha,
        "licence": "Elexon BMRS Open Data Licence (v2.0)",
        "row_count": int(len(df_reg)),
        "valid_count": new_valid,
        "missing_count": int(df_reg["f_hz"].isna().sum()),
        "last_polled_utc": srv_dt.isoformat(),
        "latest_latency_s": round(latency_s, 1),
    }
    tmp_js = sidecar_path.with_suffix(".json.tmp")
    tmp_js.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
    os.replace(tmp_js, sidecar_path)

    return {
        "polled_at_utc": srv_dt.isoformat(),
        "fetched_window_rows": int(len(df_incoming)),
        "archive_total_rows": int(len(df_reg)),
        "archive_valid_rows": new_valid,
        "newly_added_rows": added_valid,
        "coverage_start_iso": sidecar["coverage_iso"][0],
        "coverage_end_iso": sidecar["coverage_iso"][1],
        "latest_f_hz": float(df_reg["f_hz"].iloc[-1]),
        "latest_latency_s": round(latency_s, 1),
        "sha256": pq_sha,
    }


def main():
    parser = argparse.ArgumentParser(description="Live Elexon BMRS 15s Frequency Archiver (W02)")
    parser.add_argument(
        "--interval-min",
        type=float,
        default=2.0,
        help="Polling interval in minutes when running continuously (default: 2.0)",
    )
    parser.add_argument(
        "--lookback-hours",
        type=float,
        default=2.0,
        help="Lookback window in hours on each incremental poll (default: 2.0)",
    )
    parser.add_argument(
        "--archive-path",
        type=str,
        default=str(DEFAULT_ARCHIVE),
        help="Path to live_archive.parquet",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single poll-and-append cycle and exit immediately",
    )
    parser.add_argument(
        "--max-polls",
        type=int,
        default=0,
        help="Stop after N polls (0 = run indefinitely until Ctrl+C)",
    )
    args = parser.parse_args()

    archive_path = Path(args.archive_path)
    sess = make_session()
    polls_done = 0

    while True:
        polls_done += 1
        try:
            info = poll_once(sess, archive_path, lookback_hours=args.lookback_hours)
            print(json.dumps(info), flush=True)
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "error": str(exc),
                        "polled_at_utc": datetime.now(timezone.utc).isoformat(),
                    }
                ),
                flush=True,
            )

        if args.once or (args.max_polls > 0 and polls_done >= args.max_polls):
            break
        time.sleep(max(5.0, args.interval_min * 60.0))


if __name__ == "__main__":
    main()
