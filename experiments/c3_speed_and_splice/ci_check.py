"""Holdout check of the bootstrap 95% CI for k (run after tune_and_report.py tune).

For every holdout H1 recording, rebuild the same source segment used in run_eval.py
(start_s from features.jsonl), make SYNTHETIC asetrate versions at k in {1.05, 1.75}
plus the original (k=1), and run the full speed_check.analyse (with CI) on the
8 s and 30 s prefixes. Coverage = true k inside the reported CI. The "measurement"
CI is evaluated only for clips where the decision matches the truth (detected for
k != 1, CONSISTENT for k = 1). The grid-band CI also includes +/-0.2 Hz of grid deviation.
Writes eval/ci_check.json.
"""
import json
import os
import sys
import tempfile
from multiprocessing import Pool

import numpy as np
import soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from run_eval import ROOT, SR, SRC_DUR, ffmpeg_speed  # noqa: E402

KS = [1.05, 1.75]
LS = [8, 30]


def one(args):
    import speed_check as sc
    rec, s0 = args
    x, sr = sf.read(os.path.join(ROOT, "H1", rec + ".wav"))
    seg = x[int(s0 * sr): int((s0 + SRC_DUR) * sr)]
    out = []
    with tempfile.TemporaryDirectory(dir=os.path.join(HERE, "eval", "tmp")) as td:
        src = os.path.join(td, "src.wav")
        sf.write(src, seg, sr, subtype="PCM_16")
        ys = {1.0: seg, **ffmpeg_speed(src, td, KS, "rate")}
    for k, y in ys.items():
        for L in LS:
            r = sc.analyse(y[: L * sr], sr)
            out.append(dict(rec=rec, k=k, L=L, decision=r["decision"], k_hat=r.get("k"),
                            ci=r.get("k_ci95"), ci_grid=r.get("k_ci95_incl_grid_band")))
    return out


def main():
    rows = [json.loads(l) for l in open(os.path.join(HERE, "eval", "features.jsonl"))]
    starts = {}
    for r in rows:
        if r["cls"] == "H1" and r["split"] == "holdout":
            starts[r["rec"]] = r["start_s"]
    res = []
    with Pool(7) as p:
        for o in p.imap_unordered(one, sorted(starts.items())):
            res.extend(o)
    summ = {}
    for k in [1.0] + KS:
        for L in LS:
            R = [r for r in res if r["k"] == k and r["L"] == L]
            want = "CONSISTENT_WITH_REALTIME" if k == 1.0 else "SPEED_ALTERED_REVIEW"
            ok = [r for r in R if r["decision"] == want and r["ci"]]
            cov = sum(r["ci"][0] <= k <= r["ci"][1] for r in ok)
            covg = sum(r["ci_grid"][0] <= k <= r["ci_grid"][1] for r in ok)
            width = [r["ci"][1] - r["ci"][0] for r in ok]
            err = [abs(r["k_hat"] - k) / k for r in ok]
            summ[f"k{k}_L{L}"] = dict(n=len(R), n_correct_decision_with_ci=len(ok), ci_covers_true_k=cov,
                                      ci_incl_grid_band_covers_true_k=covg,
                                      median_ci_width=float(np.median(width)) if width else None,
                                      median_rel_k_error=float(np.median(err)) if err else None)
    json.dump(dict(summary=summ, rows=res), open(os.path.join(HERE, "eval", "ci_check.json"), "w"), indent=1)
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
