"""GB grid-frequency reference loader (frozen interface v1, integration/interfaces.md section 2).

    load_reference(start_utc, end_utc, source="NESO") -> DataFrame[ts_utc int64, f_hz float64]

Returns a REGULAR grid covering [start_utc, end_utc] inclusive (cadence 1 s for NESO,
15 s for ELEXON; ELEXON grid is ts % 15 == 0), with f_hz = NaN where the source has no
valid value (missing rows, Elexon 0.0 placeholders, NESO flat-filled outages listed in the
sidecar `bad_intervals`). df.attrs carries {source, cadence_s, grid, files, corrections}.

Sources
  NESO   : datasets/raw/gb/neso_YYYY_MM.parquet (1 s, from the NESO CKAN monthly CSVs,
           published ~5-6 weeks after month end). Per-month timestamp corrections from
           ghostclock/data/neso_time_corrections.json are applied (e.g. Oct 2025 file is +3600 s
           vs Elexon UTC). With fetch=True, missing months are downloaded + converted.
  ELEXON : datasets/raw/gb/elexon_live.parquet (live archiver) + elexon_YYYY_MM.parquet;
           any remaining gap is fetched from the BMRS API when fetch=True (history to
           2021-08-30, 7-day max span per request, ~1-2.5 min latency).

CLI:
  python -m ghostclock.gb_reference --source ELEXON --start 2026-11-08T09:00Z --end 2026-11-08T10:00Z [--out x.parquet] [--fetch]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from ._paths import GB_DIR as GB, PKG_DATA, rel

CORR_FILE = PKG_DATA / "neso_time_corrections.json"
CADENCE = {"NESO": 1, "ELEXON": 15}


def _to_epoch(x) -> int:
    if isinstance(x, (int, np.integer)):
        return int(x)
    ts = pd.Timestamp(x)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return int(ts.tz_convert("UTC").timestamp())


def _months(a: int, b: int):
    m = pd.Timestamp(a, unit="s").to_period("M")
    end = pd.Timestamp(b, unit="s").to_period("M")
    while m <= end:
        yield m.year, m.month
        m += 1


def _neso_corrections() -> dict:
    if CORR_FILE.exists():
        return json.loads(CORR_FILE.read_text()).get("shift_s", {})
    return {}


def _fetch_neso_month(y: int, m: int) -> None:
    months = json.loads((PKG_DATA / "neso_months.json").read_text())
    url = next((r["url"] for r in months if r["url"].endswith(f"/fnew-{y}-{m}.csv")), None)
    if url is None:
        raise FileNotFoundError(f"NESO has no published file for {y}-{m:02d} (see ghostclock/data/neso_months.json)")
    import requests
    d = GB / "neso_csv"
    d.mkdir(parents=True, exist_ok=True)
    csv = d / f"fnew-{y}-{m}.csv"
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(csv, "wb") as fh:
            for blk in r.iter_content(1 << 20):
                fh.write(blk)
    from .neso_convert import convert
    convert(csv)


def _load_neso(a: int, b: int, fetch: bool):
    corr = _neso_corrections()
    frames, files, applied = [], [], {}
    # a correction can move rows across a month boundary: read one month either side
    for y, m in _months(a - 7200, b + 7200):
        p = GB / f"neso_{y:04d}_{m:02d}.parquet"
        if not p.exists():
            touches = not (pd.Timestamp(year=y, month=m, day=1, tz="UTC").timestamp() > b or
                           (pd.Timestamp(year=y, month=m, day=1, tz="UTC") + pd.offsets.MonthBegin(1)).timestamp() <= a)
            if fetch and touches:
                _fetch_neso_month(y, m)
            else:
                continue
        df = pd.read_parquet(p)
        side = json.loads(p.with_suffix(".json").read_text())
        f = df.f_hz.values.astype("float64").copy()
        t = df.ts_utc.values.astype("int64")
        for lo, hi in side.get("bad_intervals", []):
            f[(t >= lo) & (t <= hi)] = np.nan
        sh = int(corr.get(f"{y:04d}_{m:02d}", 0))
        if sh:
            t = t + sh
            applied[f"{y:04d}_{m:02d}"] = sh
        frames.append(pd.DataFrame({"ts_utc": t, "f_hz": f}))
        files.append(rel(p))
    return frames, files, applied


def _load_elexon(a: int, b: int, fetch: bool):
    frames, files = [], []
    for p in [GB / "elexon_live.parquet"] + [GB / f"elexon_{y:04d}_{m:02d}.parquet" for y, m in _months(a, b)]:
        if p.exists():
            frames.append(pd.read_parquet(p)[["ts_utc", "f_hz"]])
            files.append(rel(p))
    have = pd.concat(frames) if frames else pd.DataFrame({"ts_utc": [], "f_hz": []})
    have = have[(have.ts_utc >= a) & (have.ts_utc <= b)]
    n_exp = (b - (a + (-a) % 15)) // 15 + 1
    if fetch and have.ts_utc.nunique() < n_exp:
        import datetime as dt
        from . import elexon_archiver as ea
        t0 = dt.datetime.fromtimestamp(a, dt.timezone.utc)
        t1 = dt.datetime.fromtimestamp(b, dt.timezone.utc)
        frames.append(ea.fetch(t0, t1))
        files.append(ea.URL)
    return frames, files, {}


def load_reference(start_utc, end_utc, source: str = "NESO", fetch: bool = False) -> pd.DataFrame:
    source = source.upper()
    if source not in CADENCE:
        raise ValueError(f"source must be one of {list(CADENCE)}")
    a, b = _to_epoch(start_utc), _to_epoch(end_utc)
    if b < a:
        raise ValueError("end_utc < start_utc")
    cad = CADENCE[source]
    frames, files, applied = (_load_neso if source == "NESO" else _load_elexon)(a, b, fetch)
    g0 = a + (-a) % cad
    grid = np.arange(g0, b + 1, cad, dtype="int64")
    out = pd.DataFrame({"ts_utc": grid, "f_hz": np.nan})
    if frames:
        df = pd.concat(frames, ignore_index=True)
        df = df[(df.ts_utc >= g0) & (df.ts_utc <= b)]
        df.loc[~df.f_hz.between(45.0, 55.0), "f_hz"] = np.nan
        # prefer finite values, then the last-listed file (live archive is listed first)
        df = df.assign(_ok=df.f_hz.notna()).sort_values(["ts_utc", "_ok"], kind="stable")
        df = df.drop_duplicates("ts_utc", keep="last")
        s = pd.Series(df.f_hz.values, index=df.ts_utc.values)
        out["f_hz"] = s.reindex(grid).values.astype("float64")
    out.attrs = {"source": source, "cadence_s": cad, "grid": "GB", "files": files,
                 "time_corrections_applied_s": applied,
                 "frac_valid": float(out.f_hz.notna().mean()) if len(out) else 0.0}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default="NESO", choices=list(CADENCE))
    ap.add_argument("--start", required=True, help="ISO time (UTC if no offset) or epoch seconds")
    ap.add_argument("--end", required=True)
    ap.add_argument("--out", help="write .parquet or .csv (+ sidecar .json)")
    ap.add_argument("--fetch", action="store_true", help="download missing data from NESO/Elexon")
    args = ap.parse_args()
    conv = lambda s: int(s) if s.isdigit() else s  # noqa: E731
    df = load_reference(conv(args.start), conv(args.end), args.source, fetch=args.fetch)
    info = {k: v for k, v in df.attrs.items()}
    info.update(n=len(df), coverage=[int(df.ts_utc.iloc[0]), int(df.ts_utc.iloc[-1])] if len(df) else None,
                f_min=float(df.f_hz.min()) if df.f_hz.notna().any() else None,
                f_max=float(df.f_hz.max()) if df.f_hz.notna().any() else None)
    if args.out:
        out = Path(args.out)
        (df.to_csv(out, index=False) if out.suffix == ".csv" else df.to_parquet(out, index=False))
        import hashlib
        side = {"source": args.source, "cadence_s": CADENCE[args.source], "grid": "GB",
                "coverage": info["coverage"], "url": info["files"],
                "sha256": hashlib.sha256(out.read_bytes()).hexdigest()}
        out.with_suffix(".json").write_text(json.dumps(side, indent=2))
    print(json.dumps(info, indent=1))


if __name__ == "__main__":
    main()
