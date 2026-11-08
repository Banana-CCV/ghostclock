"""Elexon BMRS (Insights) GB system-frequency archiver.

Polls https://data.elexon.co.uk/bmrs/api/v1/system/frequency every POLL_S seconds,
appends new rows (deduplicated on ts_utc) to datasets/raw/gb/elexon_live.parquet in the
frozen reference format (ts_utc int64 epoch s UTC, f_hz float64) and keeps a sidecar
.json up to date. On start it backfills from BACKFILL_FROM (2026-11-07 00:00 UTC).

Facts measured on 2026-11-08 (see FINDINGS.md): cadence 15 s, timestamps are UTC ('Z'),
max span per request 7 days, latency behind real time ~1-2.5 min, history back to 2021-08-30.

Run:   python work/C2/elexon_archiver.py            (loops forever)
       python work/C2/elexon_archiver.py --once     (backfill + one poll, then exit)
Single-instance guarded by work/C2/archiver.lock; PID written to work/C2/archiver.pid.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "work" / "C2"
OUT = ROOT / "datasets" / "raw" / "gb" / "elexon_live.parquet"
SIDECAR = OUT.with_suffix(".json")
LOG = WORK / "archiver.log"
PIDFILE = WORK / "archiver.pid"
LOCKFILE = WORK / "archiver.lock"
URL = "https://data.elexon.co.uk/bmrs/api/v1/system/frequency"
BACKFILL_FROM = dt.datetime(2026, 11, 7, 0, 0, tzinfo=dt.timezone.utc)
POLL_S = 120
REFILL_EVERY_S = 1800      # every 30 min re-request the last 24 h to heal any gaps
CHUNK = dt.timedelta(days=1)

log = logging.getLogger("elexon_archiver")


def _iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch(t0: dt.datetime, t1: dt.datetime) -> pd.DataFrame:
    """Fetch [t0, t1] (inclusive, as the API treats it) in <=1-day chunks."""
    frames = []
    a = t0
    while a < t1:
        b = min(a + CHUNK, t1)
        for attempt in range(4):
            try:
                r = requests.get(URL, params={"from": _iso(a), "to": _iso(b), "format": "json"}, timeout=60)
                r.raise_for_status()
                data = r.json()["data"]
                break
            except Exception as e:  # network hiccup: back off and retry
                log.warning("fetch %s..%s attempt %d failed: %s", _iso(a), _iso(b), attempt + 1, e)
                time.sleep(5 * (attempt + 1))
        else:
            raise RuntimeError(f"fetch failed for {_iso(a)}..{_iso(b)}")
        if data:
            df = pd.DataFrame(data)
            ts = pd.to_datetime(df["measurementTime"], utc=True)
            frames.append(pd.DataFrame({
                "ts_utc": ((ts - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1)).astype("int64"),
                "f_hz": df["frequency"].astype("float64"),
            }))
            # Elexon publishes 0.0 placeholders during outages: store them as NaN
            frames[-1].loc[~frames[-1]["f_hz"].between(45.0, 55.0), "f_hz"] = float("nan")
        a = b
    if not frames:
        return pd.DataFrame({"ts_utc": pd.Series(dtype="int64"), "f_hz": pd.Series(dtype="float64")})
    return pd.concat(frames, ignore_index=True)


def load_existing() -> pd.DataFrame:
    if OUT.exists():
        df = pd.read_parquet(OUT)[["ts_utc", "f_hz"]]
        df.loc[~df["f_hz"].between(45.0, 55.0), "f_hz"] = float("nan")
        return df
    return pd.DataFrame({"ts_utc": pd.Series(dtype="int64"), "f_hz": pd.Series(dtype="float64")})


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def save(df: pd.DataFrame) -> None:
    tmp = OUT.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False)
    for attempt in range(10):  # a reader may briefly hold the file open on Windows
        try:
            os.replace(tmp, OUT)
            break
        except PermissionError:
            time.sleep(1)
    else:
        raise PermissionError(f"could not replace {OUT}")
    side = {
        "source": "ELEXON",
        "cadence_s": 15,
        "grid": "GB",
        "coverage": [int(df.ts_utc.iloc[0]), int(df.ts_utc.iloc[-1])],
        "coverage_iso": [_iso(dt.datetime.fromtimestamp(int(df.ts_utc.iloc[0]), dt.timezone.utc)),
                         _iso(dt.datetime.fromtimestamp(int(df.ts_utc.iloc[-1]), dt.timezone.utc))],
        "n_rows": int(len(df)),
        "n_nan": int(df.f_hz.isna().sum()),
        "invalid_values_note": "Elexon 0.0 placeholders / values outside 45-55 Hz stored as NaN",
        "n_missing_15s_slots": int((df.ts_utc.iloc[-1] - df.ts_utc.iloc[0]) // 15 + 1 - len(df)),
        "url": URL,
        "dataset": "BMRS FREQ (Elexon Insights)",
        "live_archive": True,
        "updated_utc": _iso(dt.datetime.now(dt.timezone.utc)),
        "sha256": sha256(OUT),
    }
    tmpj = SIDECAR.with_suffix(".json.tmp")
    tmpj.write_text(json.dumps(side, indent=2))
    os.replace(tmpj, SIDECAR)


def merge(old: pd.DataFrame, new: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    if new.empty:
        return old, 0
    n_before = len(old)
    df = pd.concat([old, new], ignore_index=True)
    # keep the newest value for a timestamp (in case Elexon revises a value)
    df["_ok"] = df["f_hz"].notna()
    df = df.sort_values(["ts_utc", "_ok"], kind="stable")  # finite value sorts after NaN for same ts
    df = df.drop_duplicates("ts_utc", keep="last").drop(columns="_ok").sort_values("ts_utc").reset_index(drop=True)
    df["ts_utc"] = df["ts_utc"].astype("int64")
    df["f_hz"] = df["f_hz"].astype("float64")
    return df, len(df) - n_before


def acquire_lock():
    import msvcrt
    fh = open(LOCKFILE, "a+")
    try:
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        return None
    return fh


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()

    WORK.mkdir(parents=True, exist_ok=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=LOG, level=logging.INFO,
                        format="%(asctime)sZ %(levelname)s pid=%(process)d %(message)s")
    logging.Formatter.converter = time.gmtime

    lock = acquire_lock()
    if lock is None:
        log.error("another archiver instance holds %s; exiting", LOCKFILE)
        return 1
    if not args.once:
        PIDFILE.write_text(str(os.getpid()))
    log.info("start (once=%s) python=%s", args.once, sys.executable)

    df = load_existing()
    now = dt.datetime.now(dt.timezone.utc)
    try:
        bf = fetch(BACKFILL_FROM, now)
        df, n = merge(df, bf)
        save(df)
        log.info("backfill %s..%s: +%d rows, total %d, last=%s", _iso(BACKFILL_FROM), _iso(now), n, len(df),
                 _iso(dt.datetime.fromtimestamp(int(df.ts_utc.iloc[-1]), dt.timezone.utc)))
    except Exception as e:
        log.exception("backfill failed: %s", e)

    last_refill = time.time()
    while True:
        if args.once:
            break
        time.sleep(POLL_S)
        try:
            now = dt.datetime.now(dt.timezone.utc)
            if time.time() - last_refill > REFILL_EVERY_S:
                t0 = now - dt.timedelta(hours=24)
                last_refill = time.time()
            elif len(df):
                t0 = dt.datetime.fromtimestamp(int(df.ts_utc.iloc[-1]), dt.timezone.utc) - dt.timedelta(hours=1)
            else:
                t0 = BACKFILL_FROM
            new = fetch(t0, now)
            df, n = merge(df, new)
            if n:
                save(df)
            last = dt.datetime.fromtimestamp(int(df.ts_utc.iloc[-1]), dt.timezone.utc)
            log.info("poll %s..%s: fetched %d, +%d new, total %d, last=%s, latency=%.0fs",
                     _iso(t0), _iso(now), len(new), n, len(df), _iso(last), (now - last).total_seconds())
        except Exception as e:
            log.exception("poll failed: %s", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
