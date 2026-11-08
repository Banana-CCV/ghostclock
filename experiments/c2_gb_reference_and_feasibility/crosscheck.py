"""Fetch Elexon FREQ for the NESO months we hold, then cross-check Elexon vs NESO 1 s.

Usage: python -I work/C2/crosscheck.py
Writes datasets/raw/gb/elexon_YYYY_MM.parquet(+json), work/C2/crosscheck.json and the
overlay plot work/C2/plots/neso_vs_elexon_1h.png.
"""
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import elexon_archiver as ea  # noqa: E402

ROOT = HERE.parents[1]
GB = ROOT / "datasets" / "raw" / "gb"
MONTHS = [(2025, 10), (2026, 8), (2026, 9)]
LAGS = np.arange(-60, 61)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def elexon_month(y, m):
    out = GB / f"elexon_{y:04d}_{m:02d}.parquet"
    if out.exists():
        return pd.read_parquet(out)
    t0 = dt.datetime(y, m, 1, tzinfo=dt.timezone.utc)
    t1 = (t0 + dt.timedelta(days=32)).replace(day=1)
    df = ea.fetch(t0, t1)
    df = df[(df.ts_utc >= int(t0.timestamp())) & (df.ts_utc < int(t1.timestamp()))]
    df = df.drop_duplicates("ts_utc").sort_values("ts_utc").reset_index(drop=True)
    df.to_parquet(out, index=False)
    side = {"source": "ELEXON", "cadence_s": 15, "grid": "GB",
            "coverage": [int(df.ts_utc.iloc[0]), int(df.ts_utc.iloc[-1])],
            "url": ea.URL, "sha256": sha(out), "n_rows": int(len(df)),
            "expected_rows": int((t1 - t0).total_seconds() // 15)}
    out.with_suffix(".json").write_text(json.dumps(side, indent=2))
    return df


def stats(a, b):
    m = np.isfinite(a) & np.isfinite(b)
    e = (a[m] - b[m]) * 1000
    return {"n": int(m.sum()), "rmse_mhz": float(np.sqrt(np.mean(e ** 2))), "mean_mhz": float(e.mean()),
            "frac_exact": float(np.mean(np.abs(e) < 0.5)), "corr": float(np.corrcoef(a[m], b[m])[0, 1])}


def main():
    res = {}
    for y, m in MONTHS:
        neso = pd.read_parquet(GB / f"neso_{y:04d}_{m:02d}.parquet")
        side = json.loads((GB / f"neso_{y:04d}_{m:02d}.json").read_text())
        el = elexon_month(y, m)
        t0 = int(neso.ts_utc.iloc[0])
        f1 = np.full(int(neso.ts_utc.iloc[-1]) - t0 + 1, np.nan)
        f1[neso.ts_utc.values - t0] = neso.f_hz.values
        for a, b in side.get("bad_intervals", []):
            f1[max(a - t0, 0):max(b - t0 + 1, 0)] = np.nan
        idx = el.ts_utc.values - t0
        ok = (idx >= 70) & (idx < len(f1) - 70)
        idx, fe = idx[ok], el.f_hz.values[ok]
        cs = np.r_[0, np.nancumsum(f1)]
        cn = np.r_[0, np.cumsum(np.isfinite(f1))]

        def avg(lo, hi):  # mean of f1[i+lo .. i+hi] inclusive
            s = cs[idx + hi + 1] - cs[idx + lo]
            n = cn[idx + hi + 1] - cn[idx + lo]
            return np.where(n == hi - lo + 1, s / np.maximum(n, 1), np.nan)

        point = {int(k): stats(fe, f1[idx + k])["rmse_mhz"] for k in LAGS}
        kbest = min(point, key=point.get)
        r = {"elexon_rows": int(len(el)), "elexon_expected": int(len(f1) // 15),
             "point_rmse_by_lag_mhz": {k: round(v, 3) for k, v in point.items() if abs(k) <= 20 or k % 10 == 0},
             "best_point_lag_s": kbest, "best_point": stats(fe, f1[idx + kbest]),
             "lag0_point": stats(fe, f1[idx]),
             "avg15_trailing": stats(fe, avg(-14, 0)), "avg15_centered": stats(fe, avg(-7, 7)),
             "avg15_leading": stats(fe, avg(0, 14))}
        # best lag for a trailing 15-s mean as well
        tr = {int(k): stats(fe, avg(-14 + k, k))["rmse_mhz"] for k in range(-30, 31)}
        r["best_trailing_avg_lag_s"] = min(tr, key=tr.get)
        r["best_trailing_avg_rmse_mhz"] = tr[r["best_trailing_avg_lag_s"]]
        for w in (1, 2, 3, 5, 7):  # centred means of width 2w+1
            r[f"avg{2*w+1}_centered_rmse_mhz"] = stats(fe, avg(-w, w))["rmse_mhz"]
        e0 = (fe - f1[idx]) * 1000
        e0 = e0[np.isfinite(e0)]
        r["lag0_abs_err_pctl_mhz"] = {p: float(np.percentile(np.abs(e0), p)) for p in (50, 90, 99, 99.9)}
        r["neso_self_lag1_rmse_mhz"] = float(np.sqrt(np.nanmean((f1[1:] - f1[:-1]) ** 2)) * 1000)
        r["elexon_nan"] = int(np.isnan(el.f_hz.values).sum())
        r["elexon_missing_slots"] = int(r["elexon_expected"] - len(el))
        # within-hour detail: does Elexon ever differ from the 1 s value at its timestamp?
        res[f"{y:04d}-{m:02d}"] = r
        print(y, m, "best lag", kbest, r["best_point"], "trail", r["avg15_trailing"]["rmse_mhz"], flush=True)

    # plot: one hour, Sept 2026 (BST month) at 12:00-13:00 UTC on 2026-09-10
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    neso = pd.read_parquet(GB / "neso_2026_09.parquet")
    el = pd.read_parquet(GB / "elexon_2026_09.parquet")
    a = int(pd.Timestamp("2026-09-10 12:00", tz="UTC").timestamp())
    b = a + 3600
    n = neso[(neso.ts_utc >= a) & (neso.ts_utc < b)]
    e = el[(el.ts_utc >= a) & (el.ts_utc < b)]
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.plot((n.ts_utc - a) / 60, n.f_hz, lw=0.8, color="#4C78A8", label="NESO 1 s")
    ax.plot((e.ts_utc - a) / 60, e.f_hz, "o", ms=3.5, color="#E45756", label="Elexon BMRS FREQ (15 s)")
    ax.set_xlabel("minutes after 2026-09-10 12:00 UTC")
    ax.set_ylabel("GB frequency (Hz)")
    ax.set_title("GB grid frequency: NESO 1 s vs Elexon 15 s (same UTC timestamps, no shift applied)")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    (HERE / "plots").mkdir(exist_ok=True)
    fig.savefig(HERE / "plots" / "neso_vs_elexon_1h.png", dpi=130)
    (HERE / "crosscheck.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
