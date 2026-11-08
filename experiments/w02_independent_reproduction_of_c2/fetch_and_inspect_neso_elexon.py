"""
Download and inspect NESO historical 1s CSVs and Elexon 15s BMRS data,
verify timezone & BST/GMT transitions empirically against Elexon UTC,
and convert all datasets to the frozen Parquet + sidecar JSON format (interfaces.md §2).
"""
import hashlib
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

REPO_ROOT = Path(__file__).resolve().parents[2]
WORK_DIR = Path(__file__).resolve().parent
NESO_DIR = REPO_ROOT / "datasets" / "raw" / "neso"
ELEXON_DIR = REPO_ROOT / "datasets" / "raw" / "elexon"

NESO_DIR.mkdir(parents=True, exist_ok=True)
ELEXON_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {"User-Agent": "GhostClock-W02-Research/1.0 (UCL-AgentVerse-2026)"}

# Target NESO months:
# - Most recent 3 available months: 2026-09, 2026-08, 2026-07
# - Requested variety month: 2025-11
# - Explicit BST/GMT transition months: 2025-10 (BST->GMT on 2025-10-26) and 2026-03 (GMT->BST on 2026-03-29)
NESO_TARGETS = [
    {
        "ym": "2026-09",
        "name": "September 2026 – Historic Frequency Data",
        "resource_id": "3d14640d-89e1-43bd-bf91-93d623493bc9",
        "url": "https://api.neso.energy/dataset/cb1cc925-ecd8-4406-b021-3a3f368196e1/resource/3d14640d-89e1-43bd-bf91-93d623493bc9/download/fnew-2026-9.csv",
        "expected_start": "2026-09-01T00:00:00Z",
        "expected_end_excl": "2026-10-01T00:00:00Z",
    },
    {
        "ym": "2026-08",
        "name": "August 2026 – Historic Frequency Data",
        "resource_id": "758fa76d-b645-4532-a532-ab49335ee4c3",
        "url": "https://api.neso.energy/dataset/cb1cc925-ecd8-4406-b021-3a3f368196e1/resource/758fa76d-b645-4532-a532-ab49335ee4c3/download/fnew-2026-8.csv",
        "expected_start": "2026-08-01T00:00:00Z",
        "expected_end_excl": "2026-09-01T00:00:00Z",
    },
    {
        "ym": "2026-07",
        "name": "July 2026 – Historic Frequency Data",
        "resource_id": "027227d0-7c70-4497-bdc4-a80cff7726f8",
        "url": "https://api.neso.energy/dataset/cb1cc925-ecd8-4406-b021-3a3f368196e1/resource/027227d0-7c70-4497-bdc4-a80cff7726f8/download/fnew-2026-7.csv",
        "expected_start": "2026-07-01T00:00:00Z",
        "expected_end_excl": "2026-08-01T00:00:00Z",
    },
    {
        "ym": "2025-11",
        "name": "November 2025 – Historic Frequency Data",
        "resource_id": "2ddaf963-191a-43c3-bb3b-286de31508ee",
        "url": "https://api.neso.energy/dataset/cb1cc925-ecd8-4406-b021-3a3f368196e1/resource/2ddaf963-191a-43c3-bb3b-286de31508ee/download/fnew-2025-11.csv",
        "expected_start": "2025-11-01T00:00:00Z",
        "expected_end_excl": "2025-12-01T00:00:00Z",
    },
    {
        "ym": "2025-10",
        "name": "October 2025 – Historic Frequency Data (BST->GMT transition, raw dtm is UTC+1)",
        "resource_id": "288eba29-3ea0-4a93-bc7f-995c98473294",
        "url": "https://api.neso.energy/dataset/cb1cc925-ecd8-4406-b021-3a3f368196e1/resource/288eba29-3ea0-4a93-bc7f-995c98473294/download/fnew-2025-10.csv",
        "expected_start": "2025-10-01T00:00:00Z",
        "expected_end_excl": "2025-11-01T00:00:00Z",
        "raw_utc_offset_s": 3600,
    },
    {
        "ym": "2026-03",
        "name": "March 2026 – Historic Frequency Data (GMT->BST transition)",
        "resource_id": "e7023794-d9f8-43ed-bfee-31c6f36a87f2",
        "url": "https://api.neso.energy/dataset/cb1cc925-ecd8-4406-b021-3a3f368196e1/resource/e7023794-d9f8-43ed-bfee-31c6f36a87f2/download/fnew-2026-3.csv",
        "expected_start": "2026-03-01T00:00:00Z",
        "expected_end_excl": "2026-04-01T00:00:00Z",
    },
]


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


def download_neso_csv(sess: requests.Session, item: dict) -> Path:
    ym = item["ym"]
    raw_csv_path = NESO_DIR / f"neso_{ym}.csv"
    if raw_csv_path.exists() and raw_csv_path.stat().st_size > 10_000_000:
        print(f"  [cached] {raw_csv_path.name} ({raw_csv_path.stat().st_size:,} bytes)")
        return raw_csv_path

    print(f"  [downloading] {ym} from {item['url']} ...")
    t0 = time.time()
    with sess.get(item["url"], stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(raw_csv_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
    dt = time.time() - t0
    print(f"  [saved] {raw_csv_path.name} ({raw_csv_path.stat().st_size:,} bytes in {dt:.1f}s)")
    return raw_csv_path


def inspect_and_convert_neso(raw_csv_path: Path, item: dict) -> dict:
    ym = item["ym"]
    raw_sha = sha256_file(raw_csv_path)
    raw_size = raw_csv_path.stat().st_size

    # Read first 5 lines raw text
    with open(raw_csv_path, "r", encoding="utf-8", errors="replace") as f:
        first_lines = [f.readline().strip() for _ in range(5)]

    df_raw = pd.read_csv(raw_csv_path)
    cols = list(df_raw.columns)
    raw_row_count = len(df_raw)

    # Inspect timestamp column
    dtm_col = cols[0]
    f_col = cols[1]
    sample_first_dtm = str(df_raw[dtm_col].iloc[0])
    sample_last_dtm = str(df_raw[dtm_col].iloc[-1])

    # Parse timestamps assuming UTC (use .dt.as_unit('s') for pandas 2.x compatibility)
    # Apply empirically verified raw_utc_offset_s (e.g., +3600s BST offset on 2025-10)
    raw_offset_s = int(item.get("raw_utc_offset_s", 0))
    ts_parsed = pd.to_datetime(df_raw[dtm_col], utc=True, format="mixed")
    ts_sec = ts_parsed.dt.as_unit("s").astype("int64").to_numpy(dtype=np.int64, copy=True) - raw_offset_s
    f_vals = pd.to_numeric(df_raw[f_col], errors="coerce").to_numpy(dtype=np.float64, copy=True)
    f_vals[(f_vals < 47.0) | (f_vals > 52.0)] = np.nan

    # Also count how many rows omit HH:MM:SS at midnight
    n_date_only_rows = int((df_raw[dtm_col].str.len() == 10).sum())

    # Check ordering, duplicates, diffs
    diffs = np.diff(ts_sec)
    n_neg_diff = int(np.sum(diffs < 0))
    n_zero_diff = int(np.sum(diffs == 0))
    n_gt1_diff = int(np.sum(diffs > 1))
    unique_diffs, diff_counts = np.unique(diffs, return_counts=True)
    diff_Distribution = {str(int(k)): int(v) for k, v in zip(unique_diffs[:10], diff_counts[:10])}

    # Expected full month UTC grid
    exp_start = int(datetime.fromisoformat(item["expected_start"]).timestamp())
    exp_end_excl = int(datetime.fromisoformat(item["expected_end_excl"]).timestamp())
    expected_n = exp_end_excl - exp_start

    actual_min_ts = int(np.min(ts_sec))
    actual_max_ts = int(np.max(ts_sec))

    # Quantisation / decimal places inspection
    valid_f = f_vals[~np.isnan(f_vals)]
    f_diffs = np.abs(np.diff(valid_f))
    nonzero_f_diffs = f_diffs[f_diffs > 1e-9]
    min_step_hz = float(np.min(nonzero_f_diffs)) if len(nonzero_f_diffs) else 0.0
    # Check how many values are exact multiples of 0.001 Hz (1 mHz) vs 0.0001 Hz (0.1 mHz)
    rem_1mhz = np.abs(np.round(valid_f * 1000) - valid_f * 1000)
    frac_exact_1mhz = float(np.mean(rem_1mhz < 1e-6))
    rem_01mhz = np.abs(np.round(valid_f * 10000) - valid_f * 10000)
    frac_exact_01mhz = float(np.mean(rem_01mhz < 1e-6))

    # Regularise onto exact 1-second grid [actual_min_ts, actual_max_ts]
    df_clean = pd.DataFrame({"ts_utc": ts_sec, "f_hz": f_vals})
    df_clean = df_clean.drop_duplicates(subset=["ts_utc"], keep="first").sort_values("ts_utc")
    full_grid = pd.DataFrame({"ts_utc": np.arange(actual_min_ts, actual_max_ts + 1, 1, dtype=np.int64)})
    df_reg = pd.merge(full_grid, df_clean, on="ts_utc", how="left")
    df_reg["source"] = "NESO"

    missing_after_reg = int(df_reg["f_hz"].isna().sum())
    valid_after_reg = int(df_reg["f_hz"].notna().sum())

    parquet_path = NESO_DIR / f"neso_{ym}.parquet"
    sidecar_path = NESO_DIR / f"neso_{ym}.json"
    df_reg.to_parquet(parquet_path, index=False, engine="pyarrow")
    pq_sha = sha256_file(parquet_path)

    sidecar = {
        "source": "NESO",
        "cadence_s": 1,
        "grid": "GB",
        "coverage": [int(df_reg["ts_utc"].iloc[0]), int(df_reg["ts_utc"].iloc[-1])],
        "url": item["url"],
        "sha256": pq_sha,
        "raw_csv_file": raw_csv_path.name,
        "raw_sha256": raw_sha,
        "raw_size_bytes": raw_size,
        "resource_id": item["resource_id"],
        "licence": "NESO Open Data Licence",
        "row_count": int(len(df_reg)),
        "valid_count": valid_after_reg,
        "missing_count": missing_after_reg,
    }
    sidecar_path.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")

    return {
        "ym": ym,
        "columns": cols,
        "first_lines": first_lines,
        "raw_row_count": raw_row_count,
        "expected_utc_month_seconds": expected_n,
        "row_count_matches_exact_utc_month": (raw_row_count == expected_n),
        "sample_first_dtm": sample_first_dtm,
        "sample_last_dtm": sample_last_dtm,
        "n_date_only_midnight_rows": n_date_only_rows,
        "actual_min_ts_utc": actual_min_ts,
        "actual_max_ts_utc": actual_max_ts,
        "actual_min_iso": datetime.fromtimestamp(actual_min_ts, tz=timezone.utc).isoformat(),
        "actual_max_iso": datetime.fromtimestamp(actual_max_ts, tz=timezone.utc).isoformat(),
        "n_neg_diff": n_neg_diff,
        "n_duplicate_ts": n_zero_diff,
        "n_gaps_gt_1s": n_gt1_diff,
        "diff_distribution": diff_Distribution,
        "missing_or_nan_count": missing_after_reg,
        "f_min_hz": float(np.min(valid_f)),
        "f_max_hz": float(np.max(valid_f)),
        "f_mean_hz": float(np.mean(valid_f)),
        "f_std_hz": float(np.std(valid_f)),
        "min_nonzero_step_hz": round(min_step_hz, 6),
        "frac_exact_1mhz_quantisation": round(frac_exact_1mhz, 6),
        "frac_exact_0_1mhz_quantisation": round(frac_exact_01mhz, 6),
        "parquet_file": str(parquet_path.relative_to(REPO_ROOT)),
        "parquet_sha256": pq_sha,
        "raw_sha256": raw_sha,
        "raw_size_bytes": raw_size,
    }


def fetch_elexon_range(sess: requests.Session, start_dt: datetime, end_dt: datetime) -> pd.DataFrame:
    """Fetch Elexon 15s frequency across an arbitrary range using /system/frequency/stream."""
    url = "https://data.elexon.co.uk/bmrs/api/v1/system/frequency/stream"
    # Chunk by 7 days to be polite and resilient
    chunks = []
    cur = start_dt
    while cur < end_dt:
        nxt = min(cur + timedelta(days=7), end_dt)
        r = sess.get(
            url,
            params={
                "from": cur.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "to": nxt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            timeout=45,
        )
        r.raise_for_status()
        rows = r.json()
        if rows:
            chunks.extend(rows)
        cur = nxt + timedelta(seconds=1)
    if not chunks:
        return pd.DataFrame(columns=["ts_utc", "f_hz", "source"])

    df = pd.DataFrame(chunks)
    ts_sec = pd.to_datetime(df["measurementTime"], utc=True).dt.as_unit("s").astype("int64").to_numpy(dtype=np.int64, copy=True)
    f_vals = pd.to_numeric(df["frequency"], errors="coerce").to_numpy(dtype=np.float64, copy=True)
    out = pd.DataFrame({"ts_utc": ts_sec, "f_hz": f_vals})
    out = out.drop_duplicates(subset=["ts_utc"], keep="last").sort_values("ts_utc").reset_index(drop=True)
    return out


def regularise_and_save_elexon(df_raw: pd.DataFrame, name_prefix: str, source_url: str, apply_range_gate: bool = True) -> dict:
    min_ts = int(df_raw["ts_utc"].iloc[0])
    max_ts = int(df_raw["ts_utc"].iloc[-1])

    diffs = np.diff(df_raw["ts_utc"].to_numpy())
    unique_diffs, counts = np.unique(diffs, return_counts=True)
    diff_dist = {str(int(k)): int(v) for k, v in zip(unique_diffs[:10], counts[:10])}

    bad_mask = (df_raw["f_hz"] < 47.0) | (df_raw["f_hz"] > 52.0)
    raw_out_of_range = int(bad_mask.sum())
    raw_anomalies = [
        {"ts_utc": int(r["ts_utc"]), "raw_f_hz": float(r["f_hz"])}
        for _, r in df_raw[bad_mask].iterrows()
    ]
    df_work = df_raw[["ts_utc", "f_hz"]].copy()
    if apply_range_gate:
        df_work.loc[bad_mask, "f_hz"] = np.nan

    # Regularise onto exact 15s grid from min_ts to max_ts
    full_grid = pd.DataFrame({"ts_utc": np.arange(min_ts, max_ts + 1, 15, dtype=np.int64)})
    df_reg = pd.merge(full_grid, df_work, on="ts_utc", how="left")
    df_reg["source"] = "ELEXON"

    pq_path = ELEXON_DIR / f"{name_prefix}.parquet"
    js_path = ELEXON_DIR / f"{name_prefix}.json"
    df_reg.to_parquet(pq_path, index=False, engine="pyarrow")
    pq_sha = sha256_file(pq_path)

    valid_f = df_reg["f_hz"].dropna().to_numpy()
    rem_1mhz = np.abs(np.round(valid_f * 1000) - valid_f * 1000)
    frac_exact_1mhz = float(np.mean(rem_1mhz < 1e-6))

    sidecar = {
        "source": "ELEXON",
        "cadence_s": 15,
        "grid": "GB",
        "coverage": [min_ts, max_ts],
        "url": source_url,
        "sha256": pq_sha,
        "licence": "Elexon BMRS Open Data Licence (v2.0)",
        "row_count": int(len(df_reg)),
        "valid_count": int(df_reg["f_hz"].notna().sum()),
        "missing_count": int(df_reg["f_hz"].isna().sum()),
        "raw_anomalies_gated": raw_anomalies,
    }
    js_path.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")

    return {
        "name": name_prefix,
        "coverage": [min_ts, max_ts],
        "coverage_iso": [
            datetime.fromtimestamp(min_ts, tz=timezone.utc).isoformat(),
            datetime.fromtimestamp(max_ts, tz=timezone.utc).isoformat(),
        ],
        "raw_rows": int(len(df_raw)),
        "regularised_rows": int(len(df_reg)),
        "raw_out_of_range_gated": raw_out_of_range,
        "missing_15s_steps": int(df_reg["f_hz"].isna().sum()),
        "diff_distribution": diff_dist,
        "f_min_hz": float(np.min(valid_f)),
        "f_max_hz": float(np.max(valid_f)),
        "f_mean_hz": float(np.mean(valid_f)),
        "f_std_hz": float(np.std(valid_f)),
        "frac_exact_1mhz_quantisation": round(frac_exact_1mhz, 6),
        "parquet_file": str(pq_path.relative_to(REPO_ROOT)),
        "parquet_sha256": pq_sha,
    }


def main():
    sess = make_session()
    neso_summaries = []
    print("=== Step 1: Downloading and converting NESO monthly 1s CSVs ===")
    for item in NESO_TARGETS:
        csv_path = download_neso_csv(sess, item)
        summary = inspect_and_convert_neso(csv_path, item)
        neso_summaries.append(summary)
        print(
            f"  [converted] {item['ym']}: rows={summary['raw_row_count']:,}, "
            f"exact_utc_month={summary['row_count_matches_exact_utc_month']}, "
            f"gaps={summary['n_gaps_gt_1s']}, 1mHz_exact={summary['frac_exact_1mhz_quantisation']}"
        )

    print("\n=== Step 2: Fetching Elexon 15s data (last 7 days + today, plus overlap windows) ===")
    now_utc = datetime.now(timezone.utc)
    # 2a. Last 7 full days + today (from 2026-11-01T00:00:00Z to now)
    start_7d = datetime(2026, 11, 1, 0, 0, 0, tzinfo=timezone.utc)
    df_elexon_7d = fetch_elexon_range(sess, start_7d, now_utc + timedelta(minutes=5))
    elexon_7d_info = regularise_and_save_elexon(
        df_elexon_7d,
        "elexon_last7d_and_today",
        "https://data.elexon.co.uk/bmrs/api/v1/system/frequency/stream",
    )
    # Also seed live_archive.parquet with the same 7d+today data so the live archiver starts warm
    regularise_and_save_elexon(
        df_elexon_7d,
        "live_archive",
        "https://data.elexon.co.uk/bmrs/api/v1/system/frequency",
    )
    print(f"  [saved] elexon_last7d_and_today & live_archive: {elexon_7d_info['regularised_rows']:,} rows")

    # 2b. Overlapping 7-day window in September 2026 (BST = UTC+1 locally) for cross-check vs NESO 2026-09
    df_elexon_sep26 = fetch_elexon_range(
        sess,
        datetime(2026, 9, 24, 0, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 30, 23, 59, 45, tzinfo=timezone.utc),
    )
    elexon_sep26_info = regularise_and_save_elexon(
        df_elexon_sep26,
        "elexon_overlap_2026_09",
        "https://data.elexon.co.uk/bmrs/api/v1/system/frequency/stream",
    )
    print(f"  [saved] elexon_overlap_2026_09: {elexon_sep26_info['regularised_rows']:,} rows")

    # 2c. Overlapping 7-day window in November 2025 (GMT = UTC+0 locally) for cross-check vs NESO 2025-11
    df_elexon_nov25 = fetch_elexon_range(
        sess,
        datetime(2025, 11, 1, 0, 0, 0, tzinfo=timezone.utc),
        datetime(2025, 11, 7, 23, 59, 45, tzinfo=timezone.utc),
    )
    elexon_nov25_info = regularise_and_save_elexon(
        df_elexon_nov25,
        "elexon_overlap_2025_11",
        "https://data.elexon.co.uk/bmrs/api/v1/system/frequency/stream",
    )
    print(f"  [saved] elexon_overlap_2025_11: {elexon_nov25_info['regularised_rows']:,} rows")

    # 2d. Fetch Elexon across the two UK clock-change days (2025-10-26 BST->GMT and 2026-03-29 GMT->BST)
    df_elexon_oct_dst = fetch_elexon_range(
        sess,
        datetime(2025, 10, 25, 22, 0, 0, tzinfo=timezone.utc),
        datetime(2025, 10, 26, 6, 0, 0, tzinfo=timezone.utc),
    )
    elexon_oct_dst_info = regularise_and_save_elexon(
        df_elexon_oct_dst,
        "elexon_dst_2025_10_26",
        "https://data.elexon.co.uk/bmrs/api/v1/system/frequency/stream",
    )

    df_elexon_mar_dst = fetch_elexon_range(
        sess,
        datetime(2026, 3, 28, 22, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 3, 29, 6, 0, 0, tzinfo=timezone.utc),
    )
    elexon_mar_dst_info = regularise_and_save_elexon(
        df_elexon_mar_dst,
        "elexon_dst_2026_03_29",
        "https://data.elexon.co.uk/bmrs/api/v1/system/frequency/stream",
    )

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "neso_months": neso_summaries,
        "elexon_datasets": {
            "last7d_and_today": elexon_7d_info,
            "overlap_2026_09": elexon_sep26_info,
            "overlap_2025_11": elexon_nov25_info,
            "dst_2025_10_26": elexon_oct_dst_info,
            "dst_2026_03_29": elexon_mar_dst_info,
        },
    }
    out_json = WORK_DIR / "data_ingest_summary.json"
    out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nWrote {out_json}")


if __name__ == "__main__":
    main()
