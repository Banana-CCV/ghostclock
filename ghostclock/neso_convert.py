"""Convert NESO monthly 1-s frequency CSVs (dtm,f) to the frozen reference format.

Usage: python -m ghostclock.neso_convert data/gb/neso_csv/fnew-2026-9.csv [...]
Writes datasets/raw/gb/neso_YYYY_MM.parquet + .json and prints QC stats as JSON.
Timestamps in the CSV are naive; this script treats them as UTC (verified: see the
timezone checks in FINDINGS.md - DST-change day has no duplicate/missing hour and the
Elexon cross-check gives lag 0 s in both BST and GMT months).
"""
import hashlib
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from ._paths import GB_DIR as OUTDIR, PKG_DATA, rel
except ImportError:  # run as a script
    import sys as _s; _s.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ghostclock._paths import GB_DIR as OUTDIR, PKG_DATA, rel
PKG = json.loads((PKG_DATA / "neso_months.json").read_text())


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def convert(csv: Path) -> dict:
    y, m = map(int, re.search(r"(\d{4})-(\d{1,2})\.csv$", csv.name).groups())
    raw = pd.read_csv(csv, dtype={"dtm": str, "f": str})
    n_raw = len(raw)
    # precision: max decimals as written
    dec = raw["f"].str.split(".").str[1].str.len().fillna(0)
    ts = pd.to_datetime(raw["dtm"], format="ISO8601")
    f = pd.to_numeric(raw["f"], errors="coerce").astype("float64")
    t = ((ts - pd.Timestamp(0)) // pd.Timedelta(seconds=1)).astype("int64")
    df = pd.DataFrame({"ts_utc": t, "f_hz": f})
    n_nan = int(df.f_hz.isna().sum())
    n_dup = int(df.ts_utc.duplicated().sum())
    df = df.dropna().drop_duplicates("ts_utc").sort_values("ts_utc").reset_index(drop=True)
    start = pd.Timestamp(year=y, month=m, day=1)
    end = start + pd.offsets.MonthBegin(1)
    expected = int((end - start).total_seconds())
    d = np.diff(df.ts_utc.values)
    gaps = d[d > 1]
    gap_idx = np.where(d > 1)[0]
    biggest = sorted(zip(d[gap_idx].tolist(), df.ts_utc.values[gap_idx].tolist()), reverse=True)[:5]
    # frozen value of the frequency (flat-line runs >= 60 s) as a data-quality flag
    flat = (np.diff(df.f_hz.values) == 0)
    run, maxrun = 0, 0
    for x in flat:
        run = run + 1 if x else 0
        maxrun = max(maxrun, run)
    out = OUTDIR / f"neso_{y:04d}_{m:02d}.parquet"
    df.to_parquet(out, index=False)
    url = next((r["url"] for r in PKG if r["url"].endswith("/" + csv.name)), None)
    side = {
        "source": "NESO", "cadence_s": 1, "grid": "GB",
        "coverage": [int(df.ts_utc.iloc[0]), int(df.ts_utc.iloc[-1])],
        "coverage_iso": [pd.Timestamp(df.ts_utc.iloc[0], unit="s").isoformat() + "Z",
                         pd.Timestamp(df.ts_utc.iloc[-1], unit="s").isoformat() + "Z"],
        "url": url, "sha256": sha256(out), "csv_sha256": sha256(csv),
        "timestamp_note": "CSV dtm is naive; treated as UTC (verified, see work/C2/FINDINGS.md)",
        "n_rows": int(len(df)), "expected_rows": expected,
    }
    out.with_suffix(".json").write_text(json.dumps(side, indent=2))
    # DST change-day check (last Sunday of March / October)
    dst = None
    if m in (3, 10):
        last = end - pd.Timedelta(days=1)
        sun = last - pd.Timedelta(days=(last.weekday() + 1) % 7)
        day0 = int((sun - pd.Timestamp(0)).total_seconds())
        n_day = int(((df.ts_utc >= day0) & (df.ts_utc < day0 + 86400)).sum())
        raw_day = int(raw["dtm"].str.startswith(sun.strftime("%Y-%m-%d")).sum())
        dst = {"date": sun.strftime("%Y-%m-%d"), "rows_on_day_raw": raw_day, "rows_on_day_dedup": n_day,
               "note": "86400 => UTC (local time would give 82800 or 90000 / duplicates)"}
    return {
        "file": csv.name, "out": rel(out), "rows_raw": n_raw, "rows": int(len(df)),
        "expected_rows": expected, "missing_s": expected - int(len(df)), "nan_rows": n_nan, "dup_ts": n_dup,
        "cadence_mode_s": int(pd.Series(d).mode()[0]), "n_gaps": int(len(gaps)),
        "largest_gaps_s_at_ts": biggest, "decimals_max": int(dec.max()),
        "decimals_mode": int(dec.mode()[0]), "f_min": float(df.f_hz.min()), "f_max": float(df.f_hz.max()),
        "f_step_min_nonzero": float(np.min(np.abs(np.diff(df.f_hz.values))[np.abs(np.diff(df.f_hz.values)) > 0])),
        "max_flat_run_s": int(maxrun), "dst_check": dst, "coverage_iso": side["coverage_iso"],
    }


if __name__ == "__main__":
    res = [convert(Path(p)) for p in sys.argv[1:]]
    print(json.dumps(res, indent=1))
