"""run_real.py -- REAL data: Zenodo 3549379 MOV2_20190508_200450A.mp4 vs its mains reference.

Video filename time 20:04:50, reference WAV filename time 20:03:40 (same day, Vigo, 50 Hz)
-> nominal lag 70 s (video t=0 corresponds to reference t=70 s).  Filename stamps have 1 s
resolution, so the lag is also confirmed by a correlation search (+-60 s).
Writes real_MOV2_results.json, real_MOV2_results.npz, real_MOV2_{rs,naive}_trace.csv.
"""
import json
import os

import numpy as np

import rs_enf

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
RAW = os.path.join(ROOT, "datasets", "raw", "video_c4")
VIDEO = os.path.join(RAW, "MOV2_20190508_200450A.mp4")
WAV = os.path.join(RAW, "b827ebd746d7_tensiunator2_20190508_200340.wav")
CACHE = os.path.join(RAW, "cache", "MOV2_cells.npz")
NOMINAL_LAG = (20 * 3600 + 4 * 60 + 50) - (20 * 3600 + 3 * 60 + 40)  # 70 s
WIN = 16.0


def main():
    if not os.path.exists(CACHE):
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        cells, pts, clipf, meta, kept = rs_enf.decode_cells(VIDEO, keep=(3000, 60))
        np.savez(CACHE, cells=cells, pts=pts, clipf=clipf, meta=np.array(meta), kept=kept)
    r = rs_enf.run_video(VIDEO, win_s=WIN, cache=CACHE)
    # diagnostic: both read-out directions
    Tb, gb, sb = rs_enf.estimate_Tro(r["s"], r["t"], r["fps"], r["meta"]["H"], 4, 100.0, r["rows"],
                                     n_use=int(180 * r["fps"]), allow_negative=True)
    ref_csv = os.path.join(HERE, "ref_MOV2_enf_trace.csv")
    if os.path.exists(ref_csv):
        R = np.loadtxt(ref_csv, delimiter=",", skiprows=1); tr, fr, qr = R[:, 0], R[:, 1], R[:, 2]
    else:
        tr, fr, qr, _, _ = rs_enf.reference_enf(WAV, win_s=WIN)
        np.savetxt(ref_csv, np.c_[tr, fr, qr], delimiter=",",
                   header="t_s_from_wav_start,enf_hz,q_db", comments="")
    tc, fe, q = r["rs"]
    tn, fn, qn = r["nv"][:3]
    ts, fs_, qs = r["strip"]
    lags = np.arange(NOMINAL_LAG - 60, NOMINAL_LAG + 60.01, 0.5)
    out = dict(DATA="REAL", video=os.path.relpath(VIDEO, ROOT), reference=os.path.relpath(WAV, ROOT),
               cache=CACHE, fps_fit=r["fps"], timing=r["tinfo"], frames=int(len(r["t"])),
               duration_s=float(r["t"][-1]), Tro_ms=r["Tro"] * 1e3,
               Tro_ms_bidirectional_search=Tb * 1e3, alias_hz=r["alias"],
               naive_degenerate=r["degenerate"], static_cells=int(r["mask"].sum()),
               rows_used=int(r["rows"].sum()), window_s=WIN, hop_s=1.0, nominal_lag_s=NOMINAL_LAG,
               reference_enf_range_hz=[float(fr.min()), float(fr.max())],
               reference_median_q_db=float(np.median(qr)))
    for key, (a, b, qq) in (("rolling_shutter", (tc, fe, q)), ("naive_frame_mean", (tn, fn, qn)),
                            ("strip_alias_baseline", (ts, fs_, qs))):
        Lbest, cs = rs_enf.lag_search(a, b, tr, fr, lags)
        m_nom = rs_enf.compare(a, b, tr, fr, NOMINAL_LAG)
        m_best = rs_enf.compare(a, b, tr, fr, Lbest)
        side = cs[np.abs(lags - Lbest) > 10]
        out[key] = dict(m_nom, lag_s=NOMINAL_LAG, median_q_db=float(np.median(qq)),
                        best_lag_s=Lbest, at_best_lag=m_best,
                        corr_peak_minus_max_sidelobe_gt10s=float(np.nanmax(cs) - np.nanmax(side)))
        out[key + "_lag_curve"] = dict(lags=lags.tolist(), corr=np.nan_to_num(cs).tolist())
        np.savetxt(os.path.join(HERE, f"real_MOV2_{key}_trace.csv"), np.c_[a, b, qq],
                   delimiter=",", header="t_video_s,enf_hz,q_db", comments="")
    full = np.arange(0, tr[-1] - tc[-1] + 0.01, 0.5)
    _, cfull = rs_enf.lag_search(tc, fe, tr, fr, full)
    out["rolling_shutter_full_lag_curve"] = dict(lags=full.tolist(), corr=np.nan_to_num(cfull).tolist())
    out["lag_used_s"] = NOMINAL_LAG
    out["motion_score_median"] = float(np.median(r["motion"]))
    json.dump(out, open(os.path.join(HERE, "real_MOV2_results.json"), "w"), indent=1, default=float)
    np.savez(os.path.join(HERE, "real_MOV2_results.npz"), z=r["z"], fps=r["fps"], tc=tc, fe=fe, q=q,
             tn=tn, fn=fn, qn=qn, ts=ts, fs_strip=fs_, qs=qs, tr=tr, fr=fr, g=r["Tro_grid"], sc=r["Tro_score"], gb=gb, sb=sb,
             naive=r["naive"], s_mean=r["s"].mean(axis=0), motion=r["motion"])
    print(json.dumps({k: v for k, v in out.items() if not k.endswith("_curve")}, indent=1,
                     default=float))


if __name__ == "__main__":
    main()
