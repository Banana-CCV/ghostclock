"""
fetch_neso.py — Download and verify real GB 1-second system frequency data from NESO.
Follows integration/interfaces.md Section 2 (Grid reference series: ts_utc int64, f_hz float64).
"""
import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests


NESO_DATAPACKAGE_URL = "https://api.neso.energy/api/3/action/datapackage_show?id=system-frequency-data"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def discover_neso_resources() -> list[dict]:
    resp = requests.get(NESO_DATAPACKAGE_URL, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    resources = data.get("result", {}).get("resources", [])
    csv_resources = []
    for r in resources:
        url = r.get("path") or r.get("url") or ""
        name = r.get("name") or r.get("title") or Path(url).stem
        if url.lower().endswith(".csv"):
            csv_resources.append({
                "id": r.get("id"),
                "name": name,
                "title": r.get("title", name),
                "url": url,
                "format": r.get("format", "CSV"),
                "last_modified": r.get("last_modified"),
            })
    return csv_resources


def download_and_standardize(res: dict, out_dir: Path, split_label: str) -> dict:
    url = res["url"]
    fname = Path(url).name
    raw_csv_path = out_dir / fname
    parquet_path = out_dir / f"{Path(fname).stem}.parquet"
    sidecar_path = out_dir / f"{Path(fname).stem}.json"

    if not raw_csv_path.exists():
        print(f"[fetch_neso] Downloading {fname} from {url} ...")
        t0 = time.time()
        with requests.get(url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(raw_csv_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 512):
                    if chunk:
                        f.write(chunk)
        print(f"[fetch_neso] Downloaded {raw_csv_path.stat().st_size / 1e6:.2f} MB in {time.time() - t0:.1f}s")
    else:
        print(f"[fetch_neso] Using cached {raw_csv_path}")

    raw_sha = sha256_file(raw_csv_path)
    df = pd.read_csv(raw_csv_path)
    cols = list(df.columns)
    ts_col = cols[0]
    f_col = cols[1]

    # Parse timestamps in UTC
    ts_parsed = pd.to_datetime(df[ts_col], utc=True, format="ISO8601", errors="coerce")
    if ts_parsed.isna().mean() > 0.1:
        ts_parsed = pd.to_datetime(df[ts_col], utc=True, errors="coerce")

    valid_mask = ts_parsed.notna() & pd.to_numeric(df[f_col], errors="coerce").notna()
    df_clean = pd.DataFrame({
        "ts_utc": ts_parsed[valid_mask].dt.as_unit("s").astype("int64"),
        "f_hz": pd.to_numeric(df.loc[valid_mask, f_col], errors="coerce").astype(np.float64),
    })
    df_clean = df_clean.sort_values("ts_utc").drop_duplicates(subset=["ts_utc"], keep="first")

    start_utc = int(df_clean["ts_utc"].iloc[0])
    end_utc = int(df_clean["ts_utc"].iloc[-1])
    n_expected = end_utc - start_utc + 1
    n_observed = len(df_clean)

    # Regularize to exact 1-second grid as required by integration/interfaces.md Section 2
    full_grid = pd.DataFrame({"ts_utc": np.arange(start_utc, end_utc + 1, dtype=np.int64)})
    merged = pd.merge(full_grid, df_clean, on="ts_utc", how="left")
    n_missing = int(merged["f_hz"].isna().sum())
    if n_missing > 0:
        merged["f_hz"] = merged["f_hz"].interpolate(method="linear").bfill().ffill()

    merged["source"] = "NESO"
    merged.to_parquet(parquet_path, index=False)
    pq_sha = sha256_file(parquet_path)

    sidecar = {
        "source": "NESO",
        "cadence_s": 1,
        "grid": "GB",
        "split": split_label,
        "coverage": [start_utc, end_utc],
        "coverage_iso": [
            pd.to_datetime(start_utc, unit="s", utc=True).isoformat(),
            pd.to_datetime(end_utc, unit="s", utc=True).isoformat(),
        ],
        "n_samples_regular": int(len(merged)),
        "n_samples_raw": int(n_observed),
        "n_interpolated_gaps": n_missing,
        "f_mean_hz": float(merged["f_hz"].mean()),
        "f_std_hz": float(merged["f_hz"].std()),
        "f_min_hz": float(merged["f_hz"].min()),
        "f_max_hz": float(merged["f_hz"].max()),
        "url": url,
        "raw_csv_file": raw_csv_path.name,
        "raw_csv_bytes": int(raw_csv_path.stat().st_size),
        "raw_csv_sha256": raw_sha,
        "parquet_file": parquet_path.name,
        "parquet_sha256": pq_sha,
        "sha256": pq_sha,
        "licence": "NESO Open Data Licence (CC-BY / Open Government Licence v3.0 equivalent)",
        "retrieved_utc": pd.Timestamp.now(tz="UTC").isoformat(),
    }
    with open(sidecar_path, "w", encoding="utf-8") as f:
        json.dump(sidecar, f, indent=2)

    print(
        f"[fetch_neso] Standardized {parquet_path.name} ({split_label}): "
        f"{sidecar['coverage_iso'][0]} .. {sidecar['coverage_iso'][1]} "
        f"(N={len(merged):,}, gaps={n_missing}, mean={sidecar['f_mean_hz']:.5f} Hz, "
        f"std={sidecar['f_std_hz']*1000:.2f} mHz)"
    )
    return sidecar


def main():
    parser = argparse.ArgumentParser(description="Download and prepare NESO 1s GB frequency data.")
    parser.add_argument("--out-dir", type=str, default="work/W11/data", help="Output directory")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    resources = discover_neso_resources()
    print(f"[fetch_neso] Discovered {len(resources)} CSV resources on NESO Data Portal.")
    if len(resources) < 2:
        print("[fetch_neso] ERROR: Expected at least 2 monthly CSV resources.", file=sys.stderr)
        sys.exit(1)

    # Show last 5 resources
    for r in resources[-5:]:
        print(f"  - {r['name']} | {r['title']} | {r['url']}")

    # Select the two most recent complete monthly files for dev and holdout
    dev_res = resources[-2]
    holdout_res = resources[-1]

    dev_meta = download_and_standardize(dev_res, out_dir, split_label="dev")
    holdout_meta = download_and_standardize(holdout_res, out_dir, split_label="holdout")

    manifest = {
        "dataset": "NESO Historical 1-Second System Frequency Data (GB)",
        "portal_url": "https://www.neso.energy/data-portal/system-frequency-data",
        "api_url": NESO_DATAPACKAGE_URL,
        "licence": "NESO Open Data Licence",
        "retrieved_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "splits": {
            "dev": dev_meta,
            "holdout": holdout_meta,
        },
    }
    manifest_path = out_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"[fetch_neso] Wrote manifest to {manifest_path}")


if __name__ == "__main__":
    main()
