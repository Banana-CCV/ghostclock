"""
GB Grid Frequency Reference Loader & CLI (W02).
Implements the frozen interface from integration/interfaces.md §2:
    load_reference(start_utc: int, end_utc: int, source: str = "NESO") -> pd.DataFrame[ts_utc, f_hz]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Union

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

REPO_ROOT = Path(__file__).resolve().parents[2]
NESO_DIR = REPO_ROOT / "datasets" / "raw" / "neso"
ELEXON_DIR = REPO_ROOT / "datasets" / "raw" / "elexon"
PROBE_JSON = Path(__file__).resolve().parent / "probe_results.json"

HEADERS = {"User-Agent": "GhostClock-W02-GBReference/1.0 (UCL-AgentVerse-2026)"}

# Empirically verified across all 21 NESO monthly files (2025-01 through 2026-09) against Elexon BMRS UTC:
# - In 2025, NESO exported all seven summer-time monthly files (2025-04 through 2025-10) with dtm = UTC + 3600s (BST).
# - Starting in 2025-11 and continuing through all of 2026 (including all 2026 summer months 2026-04..2026-09),
#   NESO exports dtm in strict UTC (lag = 0s year-round).
NESO_BST_SHIFTED_MONTHS = frozenset({
    "2025-04",
    "2025-05",
    "2025-06",
    "2025-07",
    "2025-08",
    "2025-09",
    "2025-10",
})


def get_neso_month_utc_offset_s(ym: str) -> int:
    """
    Return the raw timestamp offset (dtm_naive_utc - true_ts_utc) in seconds for a NESO monthly CSV.
    Returns +3600 for 2025-04..2025-10 (where raw dtm was exported in BST = UTC+1) and 0 for
    all 2025 GMT months and all 2026 months (where raw dtm is exported in true UTC year-round).
    """
    return 3600 if ym in NESO_BST_SHIFTED_MONTHS else 0


def _to_epoch_sec(val: Union[int, float, str, datetime]) -> int:
    if isinstance(val, (int, np.integer)):
        return int(val)
    if isinstance(val, (float, np.floating)):
        return int(round(val))
    if isinstance(val, datetime):
        if val.tzinfo is None:
            val = val.replace(tzinfo=timezone.utc)
        return int(val.timestamp())
    if isinstance(val, str):
        s = val.strip()
        if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
            return int(s)
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    raise TypeError(f"Unsupported timestamp type: {type(val)}")


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    retry = Retry(
        total=4,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    return s


def _load_parquet_slices(directory: Path, start_utc: int, end_utc: int) -> list[pd.DataFrame]:
    if not directory.exists():
        return []
    frames = []
    for pq_file in sorted(directory.glob("*.parquet")):
        json_file = pq_file.with_suffix(".json")
        if json_file.exists():
            try:
                meta = json.loads(json_file.read_text(encoding="utf-8"))
                cov = meta.get("coverage", [])
                if len(cov) == 2 and (cov[1] < start_utc or cov[0] > end_utc):
                    continue
            except Exception:
                pass
        try:
            df = pd.read_parquet(
                pq_file,
                columns=["ts_utc", "f_hz"],
                filters=[("ts_utc", ">=", start_utc), ("ts_utc", "<=", end_utc)],
            )
            if not df.empty:
                frames.append(df)
        except Exception:
            df = pd.read_parquet(pq_file, columns=["ts_utc", "f_hz"])
            df = df[(df["ts_utc"] >= start_utc) & (df["ts_utc"] <= end_utc)]
            if not df.empty:
                frames.append(df)
    return frames


def _fetch_elexon_on_demand(start_utc: int, end_utc: int) -> pd.DataFrame:
    sess = _make_session()
    url = "https://data.elexon.co.uk/bmrs/api/v1/system/frequency/stream"
    start_dt = datetime.fromtimestamp(start_utc, tz=timezone.utc)
    end_dt = datetime.fromtimestamp(end_utc, tz=timezone.utc)
    chunks = []
    cur = start_dt
    while cur <= end_dt:
        nxt = min(cur + timedelta(days=7), end_dt)
        r = sess.get(
            url,
            params={
                "from": cur.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "to": nxt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            timeout=30,
        )
        r.raise_for_status()
        rows = r.json()
        if rows:
            chunks.extend(rows)
        if nxt >= end_dt:
            break
        cur = nxt + timedelta(seconds=1)
    if not chunks:
        return pd.DataFrame({"ts_utc": pd.Series(dtype="int64"), "f_hz": pd.Series(dtype="float64")})
    df = pd.DataFrame(chunks)
    ts_sec = pd.to_datetime(df["measurementTime"], utc=True).dt.as_unit("s").astype("int64").to_numpy(dtype=np.int64)
    f_vals = pd.to_numeric(df["frequency"], errors="coerce").to_numpy(dtype=np.float64)
    out = pd.DataFrame({"ts_utc": ts_sec, "f_hz": f_vals})
    out = out[(out["ts_utc"] >= start_utc) & (out["ts_utc"] <= end_utc)]
    return out


def _regularise_grid(df: pd.DataFrame, start_utc: int, end_utc: int, cadence_s: int) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame({"ts_utc": pd.Series(dtype="int64"), "f_hz": pd.Series(dtype="float64")})
    df = df.copy()
    # Physical GB grid frequency gate [47.0, 52.0] Hz to reject SCADA dropout sentinels (e.g. 0.0 Hz)
    df.loc[(df["f_hz"] < 47.0) | (df["f_hz"] > 52.0), "f_hz"] = np.nan
    df = df.drop_duplicates(subset=["ts_utc"], keep="last").sort_values("ts_utc").reset_index(drop=True)
    # Align grid to the actual available integer multiples of cadence_s within [start_utc, end_utc]
    min_ts = int(df["ts_utc"].iloc[0])
    max_ts = int(df["ts_utc"].iloc[-1])
    grid = pd.DataFrame({"ts_utc": np.arange(min_ts, max_ts + 1, cadence_s, dtype=np.int64)})
    merged = pd.merge(grid, df[["ts_utc", "f_hz"]], on="ts_utc", how="left")
    merged["ts_utc"] = merged["ts_utc"].astype("int64")
    merged["f_hz"] = merged["f_hz"].astype("float64")
    # Mask flat-filled NESO outages (constant frequency run >= 120 consecutive 1 s samples, e.g. 2026-09-15 11,158s & 2026-03-31 479s)
    if cadence_s == 1 and len(merged) >= 120:
        f_arr = merged["f_hz"].to_numpy(dtype=np.float64, copy=True)
        same = np.r_[False, np.abs(np.diff(f_arr)) < 1e-9] & (~np.isnan(f_arr))
        changes = np.diff(np.r_[0, same.view(np.int8), 0])
        starts = np.where(changes == 1)[0] - 1
        ends = np.where(changes == -1)[0] - 1
        for s_i, e_i in zip(starts, ends):
            if (e_i - s_i + 1) >= 120:
                f_arr[max(0, s_i) : e_i + 1] = np.nan
        merged["f_hz"] = f_arr
    return merged


def load_reference(
    start_utc: Union[int, str, datetime],
    end_utc: Union[int, str, datetime],
    source: str = "NESO",
    allow_network: bool = True,
) -> pd.DataFrame:
    """
    Frozen interface (integration/interfaces.md §2):
    Load GB grid frequency reference series between start_utc and end_utc (inclusive).

    Parameters
    ----------
    start_utc : int (or ISO-8601 str / datetime)
        Start timestamp in Unix epoch seconds (UTC).
    end_utc : int (or ISO-8601 str / datetime)
        End timestamp in Unix epoch seconds (UTC).
    source : str, default "NESO"
        One of "NESO" (1 s historical), "ELEXON" (15 s near-real-time & rolling history),
        or "AUTO" (uses NESO 1 s if fully covered locally, else falls back to ELEXON 15 s).
    allow_network : bool, default True
        Whether to query Elexon API on-demand if a requested ELEXON range is not in local Parquet cache.

    Returns
    -------
    pd.DataFrame
        DataFrame with exact columns ["ts_utc", "f_hz"] where ts_utc is int64 and f_hz is float64.
    """
    t0 = _to_epoch_sec(start_utc)
    t1 = _to_epoch_sec(end_utc)
    if t1 < t0:
        raise ValueError(f"end_utc ({t1}) must be >= start_utc ({t0})")

    src = source.strip().upper()
    if src not in ("NESO", "ELEXON", "AUTO"):
        raise ValueError(f"Unsupported source '{source}'. Expected 'NESO', 'ELEXON', or 'AUTO'.")

    if src in ("NESO", "AUTO"):
        neso_frames = _load_parquet_slices(NESO_DIR, t0, t1)
        if neso_frames:
            df_neso = pd.concat(neso_frames, ignore_index=True)
            df_neso = _regularise_grid(df_neso, t0, t1, cadence_s=1)
            if src == "NESO" or (
                not df_neso.empty
                and int(df_neso["ts_utc"].iloc[0]) <= t0
                and int(df_neso["ts_utc"].iloc[-1]) >= t1
            ):
                return df_neso[["ts_utc", "f_hz"]]
        elif src == "NESO":
            return pd.DataFrame({"ts_utc": pd.Series(dtype="int64"), "f_hz": pd.Series(dtype="float64")})

    # ELEXON path (or AUTO fallback)
    elexon_frames = _load_parquet_slices(ELEXON_DIR, t0, t1)
    df_el = pd.concat(elexon_frames, ignore_index=True) if elexon_frames else pd.DataFrame(
        {"ts_utc": pd.Series(dtype="int64"), "f_hz": pd.Series(dtype="float64")}
    )

    # Check if local cache covers [t0, t1] within 15s tolerance
    needs_fetch = df_el.empty or (int(df_el["ts_utc"].min()) > t0 + 15) or (int(df_el["ts_utc"].max()) < t1 - 15)
    if needs_fetch and allow_network:
        try:
            df_net = _fetch_elexon_on_demand(t0, t1)
            if not df_net.empty:
                df_el = pd.concat([df_el, df_net], ignore_index=True)
        except Exception as exc:
            if df_el.empty:
                raise RuntimeError(f"Failed to fetch Elexon reference for [{t0}, {t1}]: {exc}") from exc

    return _regularise_grid(df_el, t0, t1, cadence_s=15)[["ts_utc", "f_hz"]]


def list_local_inventory() -> dict:
    inventory = {"NESO": [], "ELEXON": []}
    for label, d in [("NESO", NESO_DIR), ("ELEXON", ELEXON_DIR)]:
        if not d.exists():
            continue
        for js in sorted(d.glob("*.json")):
            try:
                meta = json.loads(js.read_text(encoding="utf-8"))
                cov = meta.get("coverage", [None, None])
                inventory[label].append({
                    "file": js.with_suffix(".parquet").name,
                    "cadence_s": meta.get("cadence_s"),
                    "coverage_utc": cov,
                    "coverage_iso": [
                        datetime.fromtimestamp(cov[0], tz=timezone.utc).isoformat() if cov[0] else None,
                        datetime.fromtimestamp(cov[1], tz=timezone.utc).isoformat() if cov[1] else None,
                    ],
                    "row_count": meta.get("row_count"),
                    "missing_count": meta.get("missing_count"),
                    "sha256": meta.get("sha256"),
                })
            except Exception:
                pass
    return inventory


def main():
    parser = argparse.ArgumentParser(description="GB Grid Frequency Reference Loader CLI (W02)")
    parser.add_argument("--start-utc", type=str, help="Start UTC (Unix epoch seconds or ISO-8601 string)")
    parser.add_argument("--end-utc", type=str, help="End UTC (Unix epoch seconds or ISO-8601 string)")
    parser.add_argument("--source", type=str, default="NESO", choices=["NESO", "ELEXON", "AUTO"], help="Reference source")
    parser.add_argument("--out", type=str, default=None, help="Optional output file (.parquet or .csv)")
    parser.add_argument("--no-network", action="store_true", help="Disable on-demand Elexon API calls")
    parser.add_argument("--inventory", action="store_true", help="Print local Parquet inventory JSON and exit")
    args = parser.parse_args()

    if args.inventory:
        print(json.dumps(list_local_inventory(), indent=2))
        return

    if not args.start_utc or not args.end_utc:
        parser.error("--start-utc and --end-utc are required unless --inventory is specified.")

    t0 = _to_epoch_sec(args.start_utc)
    t1 = _to_epoch_sec(args.end_utc)
    df = load_reference(t0, t1, source=args.source, allow_network=not args.no_network)

    summary = {
        "source_requested": args.source,
        "start_utc": t0,
        "end_utc": t1,
        "start_iso": datetime.fromtimestamp(t0, tz=timezone.utc).isoformat(),
        "end_iso": datetime.fromtimestamp(t1, tz=timezone.utc).isoformat(),
        "rows_returned": int(len(df)),
        "valid_rows": int(df["f_hz"].notna().sum()) if not df.empty else 0,
        "missing_rows": int(df["f_hz"].isna().sum()) if not df.empty else 0,
        "actual_min_ts": int(df["ts_utc"].iloc[0]) if not df.empty else None,
        "actual_max_ts": int(df["ts_utc"].iloc[-1]) if not df.empty else None,
        "inferred_cadence_s": int(df["ts_utc"].iloc[1] - df["ts_utc"].iloc[0]) if len(df) > 1 else None,
        "f_mean_hz": round(float(df["f_hz"].mean()), 6) if not df.empty else None,
        "f_std_hz": round(float(df["f_hz"].std()), 6) if len(df) > 1 else None,
        "f_min_hz": round(float(df["f_hz"].min()), 6) if not df.empty else None,
        "f_max_hz": round(float(df["f_hz"].max()), 6) if not df.empty else None,
    }

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.suffix.lower() == ".csv":
            df.to_csv(out_path, index=False)
        else:
            df.to_parquet(out_path, index=False, engine="pyarrow")
        summary["saved_to"] = str(out_path)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
