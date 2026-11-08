"""Blind ENF dating of a venue recording against the GB Elexon 15 s feed (director tool).

usage: python -m ghostclock.tools.blind_match <trace.csv> --case CASE_X [--qmin 15] [--search-start 2026-11-07T00:00Z]
- Uses ONLY the extracted ENF trace (t_s, enf_hz, q_db). No filename, metadata or claimed time is read.
- Search window: the whole live Elexon archive ($GHOSTCLOCK_GB_DIR/elexon_live.parquet), interpolated to 1 s
  (W02: better than block averaging), smoothed with the same window as the extractor.
- Null: the same trace scored against 7 earlier days of Elexon data (fetched via ghostclock.gb_reference),
  which the recording cannot have come from -> empirical distribution of best wrong-day peaks.
Outputs $GHOSTCLOCK_OUT/blind/<case>/{result.json, landscape.png, overlay.png}.
"""
import argparse, json, sys
from pathlib import Path
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from ghostclock._paths import GB_DIR, OUT_DIR  # noqa: E402


def load_ref(start, end, live=True):
    if live:
        e = pd.read_parquet(GB_DIR / "elexon_live.parquet")
    else:
        from ghostclock import gb_reference as g
        e = g.load_reference(start, end, source="ELEXON", fetch=True)
    e = e[(e.ts_utc >= start) & (e.ts_utc < end)].dropna()
    e = e[(e.f_hz > 49.0) & (e.f_hz < 51.0)]
    t1 = np.arange(int(e.ts_utc.min()), int(e.ts_utc.max()) + 1)
    f1 = np.interp(t1, e.ts_utc.to_numpy(), e.f_hz.to_numpy())
    return t1, f1


def smooth(x, w):
    k = np.ones(int(w)) / int(w)
    return np.convolve(x, k, mode="same")


def ncc_scan(ref, q, w):
    """Weighted NCC of query q (with weights w, NaN-free) at every offset of ref (FFT-free sliding, vectorised by chunks)."""
    n = len(q); L = len(ref) - n + 1
    w = w / w.sum()
    qc = q - np.sum(w * q)
    qs = np.sqrt(np.sum(w * qc ** 2))
    win = np.lib.stride_tricks.sliding_window_view(ref, n)
    out = np.empty(L)
    for i in range(0, L, 20000):
        R = win[i:i + 20000]
        mu = R @ w
        Rc = R - mu[:, None]
        out[i:i + 20000] = (Rc * qc) @ w / (np.sqrt((Rc ** 2) @ w) * qs + 1e-15)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("trace"); ap.add_argument("--case", required=True)
    ap.add_argument("--qmin", type=float, default=15.0); ap.add_argument("--win", type=float, default=16.0)
    ap.add_argument("--search-start", default="2026-11-07T00:00:00Z"); ap.add_argument("--null-days", type=int, default=7)
    a = ap.parse_args()
    out = OUT_DIR / "blind" / a.case; out.mkdir(parents=True, exist_ok=True)
    tr = np.loadtxt(a.trace, delimiter=",", skiprows=1)
    t, f, q = tr[:, 0], tr[:, 1], tr[:, 2]
    # regularise the trace to 1 s steps from its first window centre
    tt = np.arange(np.ceil(t[0]), np.floor(t[-1]) + 1)
    ff = np.interp(tt, t, f); qq = np.interp(tt, t, q)
    good = (qq >= a.qmin) & (np.abs(ff - np.median(ff)) < 0.15)
    w = good.astype(float) + 1e-6
    ff = np.where(good, ff, np.median(ff[good]) if good.any() else 50.0)
    s0 = int(pd.Timestamp(a.search_start).timestamp()); s1 = int(pd.Timestamp.now(tz="UTC").timestamp())
    rt, rf = load_ref(s0, s1, live=True)
    rf_s = smooth(rf, a.win)
    sc = ncc_scan(rf_s, ff, w)
    # candidate start times = reference time at offset minus the trace's first sample time
    cand_start = rt[: len(sc)] - tt[0]
    i1 = int(np.nanargmax(sc))
    excl = np.abs(np.arange(len(sc)) - i1) > 120
    i2 = int(np.nanargmax(np.where(excl, sc, -np.inf)))
    # null: the same trace against earlier days (cannot be the true day)
    nulls = []
    for d in range(1, a.null_days + 1):
        n0 = s0 - d * 86400
        try:
            nt, nf = load_ref(n0, n0 + 86400, live=False)
            nulls.append(float(np.nanmax(ncc_scan(smooth(nf, a.win), ff, w))))
        except Exception as e:
            print("null day failed", d, e)
    nulls = np.array(nulls)
    hrs = (len(sc)) / 3600
    p_emp = float((np.sum(nulls >= sc[i1]) + 1) / (len(nulls) + 1)) if len(nulls) else None
    res = {"case": a.case, "trace": a.trace, "trace_duration_s": float(tt[-1] - tt[0]), "usable_frac": float(good.mean()),
           "search_window_utc": [pd.to_datetime(s0, unit="s", utc=True).isoformat(), pd.to_datetime(s1, unit="s", utc=True).isoformat()],
           "search_hours": hrs, "best_start_utc": pd.to_datetime(cand_start[i1], unit="s", utc=True).isoformat(), "best_ncc": float(sc[i1]),
           "second_start_utc": pd.to_datetime(cand_start[i2], unit="s", utc=True).isoformat(), "second_ncc": float(sc[i2]),
           "margin": float(sc[i1] - sc[i2]), "null_wrong_day_best_ncc": nulls.round(4).tolist(),
           "null_max": float(nulls.max()) if len(nulls) else None, "p_empirical_vs_wrong_days": p_emp,
           "note": "Blind: no filename/metadata used. Compare best_start_utc with the team's withheld ground truth AFTERWARDS."}
    json.dump(res, open(out / "result.json", "w"), indent=1)
    print(json.dumps(res, indent=1))
    # figures
    fig, ax = plt.subplots(figsize=(12, 3.6))
    ax.plot(pd.to_datetime(cand_start, unit="s"), sc, lw=0.5, color="#555")
    ax.axhline(nulls.max() if len(nulls) else np.nan, color="#d62728", ls="--", lw=1, label=f"best score on {len(nulls)} wrong days")
    ax.scatter([pd.to_datetime(cand_start[i1], unit="s")], [sc[i1]], color="#1f77b4", zorder=5, label="best candidate")
    ax.set_ylabel("match score (NCC)"); ax.set_title(f"{a.case}: blind search over {hrs:.1f} h of GB grid history"); ax.legend(loc="lower left")
    fig.tight_layout(); fig.savefig(out / "landscape.png", dpi=140); plt.close(fig)
    j = i1
    seg = rf_s[j: j + len(ff)]
    fig, ax = plt.subplots(figsize=(12, 3.6))
    tx = pd.to_datetime(cand_start[j] + tt, unit="s")
    ax.plot(tx, seg, color="black", lw=1.4, label="GB grid (Elexon, smoothed)")
    ax.plot(tx, np.where(good, ff, np.nan) - np.mean(ff[good]) + np.mean(seg[good]), color="#1f77b4", lw=1.2, label="recovered from recording (offset-aligned)")
    ax.set_ylabel("Hz"); ax.legend(); ax.set_title(f"{a.case}: recording vs grid at best candidate (NCC {sc[i1]:.3f})")
    fig.tight_layout(); fig.savefig(out / "overlay.png", dpi=140); plt.close(fig)


if __name__ == "__main__":
    main()
