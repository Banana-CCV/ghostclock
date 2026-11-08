"""synth_eval.py -- render one SYNTHETIC case and evaluate rolling-shutter vs naive ENF.
usage: python synth_eval.py <case_name>     (cases defined in CASES below)
Writes synth/SYNTH_<case>.mp4, *_truth.csv, *_params.json and synth/SYNTH_<case>_eval.json.
ALL RESULTS FROM THIS SCRIPT ARE ON SYNTHETIC DATA.
"""
import json
import os
import sys

import numpy as np

import rs_enf
import synth_rs

HERE = os.path.dirname(os.path.abspath(__file__))
CASES = {
    # name: render kwargs
    "fps30_tro25": dict(fps=30, T_ro=0.025, T_exp=0.002, seed=11),
    "fps30_tro30_framemean_null": dict(fps=30, T_ro=0.030, T_exp=0.002, seed=12),
    "fps25_tro25_alias_degenerate": dict(fps=25, T_ro=0.025, T_exp=0.002, seed=13),
    "fps60_tro12": dict(fps=60, T_ro=0.012, T_exp=0.002, seed=14),
    "fps30_antibanding_exp10ms": dict(fps=30, T_ro=0.025, T_exp=0.010, seed=15),
    "fps30_weak_m1pct_crf28": dict(fps=30, T_ro=0.025, T_exp=0.002, seed=16, m1=0.01, crf=28),
}


def truth_windowed(t_truth, f_truth, tc, win_s):
    """Truth averaged with the same Hann window the STFT uses (fair comparison)."""
    tt = np.arange(t_truth[0], t_truth[-1], 0.1)
    ff = np.interp(tt, t_truth, f_truth)
    out = []
    for c in tc:
        sel = np.abs(tt - c) <= win_s / 2
        w = np.hanning(sel.sum() + 2)[1:-1]
        out.append(np.sum(w * ff[sel]) / np.sum(w))
    return np.array(out)


def metrics(fe, ft):
    err = fe - ft
    return dict(n=int(len(fe)), corr=float(np.corrcoef(fe, ft)[0, 1]),
                rmse_mHz=float(np.sqrt(np.mean(err ** 2)) * 1e3), bias_mHz=float(err.mean() * 1e3),
                p95_abs_err_mHz=float(np.percentile(np.abs(err), 95) * 1e3))


def run_case(name, dur_s=240.0, win_s=16.0):
    allow_neg = name.endswith("+bidir")       # variant: search both read-out directions
    base_name = name.replace("+bidir", "")
    kw = dict(CASES[base_name])
    mp4 = os.path.join(HERE, "synth", f"SYNTH_{base_name}.mp4")
    if not os.path.exists(mp4):
        synth_rs.render(mp4, dur_s=dur_s, **kw)
    params = json.load(open(mp4.replace(".mp4", "_params.json")))
    tr = np.loadtxt(mp4.replace(".mp4", "_truth.csv"), delimiter=",", skiprows=1)
    cache = os.path.join(HERE, "..", "..", "datasets", "raw", "video_c4", "cache",
                         f"SYNTH_{base_name}_cells.npz")   # decoded-cell cache (not a result)
    r = rs_enf.run_video(mp4, win_s=win_s, allow_negative=allow_neg, cache=cache)
    tag = "_bidir" if allow_neg else ""
    out = dict(SYNTHETIC=True, case=name, Tro_search="both directions" if allow_neg else "T_ro>0",
               params=params, fps_fit=r["fps"],
               Tro_est_ms=r["Tro"] * 1e3, Tro_true_ms=kw["T_ro"] * 1e3,
               alias_hz=r["alias"], naive_degenerate=r["degenerate"])
    for key, (tc, fe, q) in (("rolling_shutter", r["rs"]), ("naive_frame_mean", r["nv"][:3]),
                             ("strip_alias_baseline", r["strip"])):
        ft = truth_windowed(tr[:, 0], tr[:, 1], tc, win_s)
        m = metrics(fe, ft)
        m["median_q_db"] = float(np.median(q))
        out[key] = m
        np.savetxt(mp4.replace(".mp4", f"{tag}_{key}_trace.csv"), np.c_[tc, fe, q, ft], delimiter=",",
                   header="t_s,enf_hz_est,q_db,enf_hz_truth_windowed_SYNTHETIC", comments="")
    # oracle T_ro (diagnostic): how much does the T_ro search cost?
    tc, fe, q, _ = rs_enf.rs_enf_trace(r["s"], r["t"], r["fps"], r["meta"]["H"], 4, kw["T_ro"],
                                       rows=r["rows"], win_s=win_s, degenerate=r["degenerate"])
    out["rolling_shutter_oracle_Tro"] = metrics(fe, truth_windowed(tr[:, 0], tr[:, 1], tc, win_s))
    np.savez(mp4.replace(".mp4", f"{tag}_diag.npz"), Tro_grid=r["Tro_grid"], Tro_score=r["Tro_score"],
             z=r["z"], fps=r["fps"])
    json.dump(out, open(mp4.replace(".mp4", f"{tag}_eval.json"), "w"), indent=1, default=float)
    print(json.dumps(out, indent=1, default=float))


if __name__ == "__main__":
    for n in sys.argv[1:]:
        run_case(n)
