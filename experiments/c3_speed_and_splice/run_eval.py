"""Stage 1 of the evaluation: build manipulated clips and extract features.

REAL recordings (ENF-WHU H1 / H0) + SYNTHETIC manipulations made here:
  * speed, pitch+tempo : ffmpeg  asetrate=8000*k,aresample=8000   (like sped-up CCTV)
  * speed, tempo only  : ffmpeg  atempo=k                          (pitch preserved)
  * splices            : sample-exact deletion of d s / insertion of i s of audio
                         from >= 60 s elsewhere in the same recording (numpy concat,
                         no cross-fade)
For each recording one seeded source segment is used; clips of length L are
prefixes of the manipulated output (so lengths are nested, not independent).

Writes work/C3/eval/features.jsonl (one row per clip). Thresholds are NOT applied
here: tune.py fixes them on dev, report.py applies them to holdout.

Usage: python run_eval.py [--workers 6] [--limit N]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zlib

import numpy as np
import soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = r"<WORKSPACE>\datasets\raw\enf-whu\repo\ENF-WHU-Dataset"
OUT = os.path.join(HERE, "eval")
DEMO = os.path.join(HERE, "demo")
KS = [0.8, 0.9, 0.95, 0.98, 1.02, 1.05, 1.1, 1.25, 1.5, 1.75, 2.0]
LENGTHS = [5, 8, 15, 30, 60]
TEMPO_LENGTHS = [8, 30]          # atempo evaluated at two lengths (compute budget)
LAMS = [0.5, 1.5, 3.0]
SRC_DUR = 125.0                  # source seconds for speed manipulations (k=2 -> 62.5 s out)
SPLICE_L = [15, 30]
DELETES = [1, 2, 5, 10, 30]
INSERTS = [2, 5, 10]
SR = 8000


def rng_for(name, salt=0):
    return np.random.default_rng(zlib.crc32(f"{name}:{salt}".encode()) + 20261108)


def ffmpeg_speed(src_wav, tmpdir, ks, method):
    import speed_check as sc
    ff = sc.find_ffmpeg()
    n = len(ks)
    labels = [f"o{i}" for i in range(n)]
    fc = f"[0:a]asplit={n}" + "".join(f"[s{i}]" for i in range(n)) + ";"
    for i, k in enumerate(ks):
        filt = f"asetrate={SR}*{k},aresample={SR}" if method == "rate" else f"atempo={k}"
        fc += f"[s{i}]{filt}[{labels[i]}];"
    cmd = [ff, "-v", "error", "-y", "-i", src_wav, "-filter_complex", fc.rstrip(";")]
    outs = []
    for i, k in enumerate(ks):
        o = os.path.join(tmpdir, f"{method}_{k}.wav")
        cmd += ["-map", f"[{labels[i]}]", "-t", "61", "-c:a", "pcm_s16le", o]
        outs.append(o)
    subprocess.run(cmd, check=True)
    return {k: sf.read(o)[0] for k, o in zip(ks, outs)}


def speed_feats(x, sr):
    import speed_check as sc
    p = sc.load_params()
    fts, _ = sc.features(x, sr, p, lams=LAMS)
    return {str(l): {k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()} for l, d in fts.items()}


def splice_feats(x, sr):
    import splice_check as sp
    p = sp.load_params()
    p["theta"] = 1e9  # no decision here
    r = sp.analyse(x, sr, params=p)
    out = dict(line_snr=None if r.get("line") is None else r["line"]["snr_db"], peaks=[])
    if r.get("line") is None:
        # analyse returns early when no line passes t_line; record the raw best line anyway
        ln = sp.pick_line(sp.to_analysis_rate(x, sr, p["sr"]), p["sr"], p)
        out["line_snr"] = round(ln[3], 1) if ln else None
        p2 = dict(p); p2["t_line"] = -1e9
        r = sp.analyse(x, sr, params=p2)
    tf, J, _ = r["_trace"]
    e = int(round(p["edge_s"] / p["frame_s"]))
    Jv = J.copy(); Jv[:e] = np.nan; Jv[-e:] = np.nan
    # local maxima of J (> 0.2 rad), as (t, J)
    for i in range(1, len(Jv) - 1):
        if np.isfinite(Jv[i]) and Jv[i] > 0.2 and Jv[i] >= np.nanmax(Jv[max(0, i - 3):i + 4]):
            out["peaks"].append((round(float(tf[i]), 2), round(float(Jv[i]), 3)))
    out["max_J"] = round(float(np.nanmax(Jv)), 3) if np.isfinite(Jv).any() else None
    out["median_J"] = round(float(np.nanmedian(Jv)), 3) if np.isfinite(Jv).any() else None
    out["line_n"] = r["line"]["n"] if r.get("line") else None
    return out


def job(args):
    rec, cls, split, mode = args
    t0 = time.time()
    path = os.path.join(ROOT, cls, rec + ".wav")
    x, sr = sf.read(path)
    assert sr == SR
    dur = len(x) / sr
    rows = []
    starts = [0] if mode == "H1" else list(range(6))
    tmp = tempfile.mkdtemp(dir=os.path.join(HERE, "eval", "tmp"))
    try:
        for si in starts:
            rng = rng_for(rec, si)
            s0 = float(rng.uniform(5.0, dur - SRC_DUR - 5.0))
            seg = x[int(s0 * sr): int((s0 + SRC_DUR) * sr)]
            src = os.path.join(tmp, "src.wav")
            sf.write(src, seg, sr, subtype="PCM_16")
            base = dict(rec=rec, cls=cls, split=split, start_s=round(s0, 2), start_idx=si)
            # originals
            for L in LENGTHS:
                rows.append(dict(base, task="speed", method="orig", k=1.0, L=L,
                                 f=speed_feats(seg[: L * sr], sr)))
            ks_rate = KS if mode == "H1" else [1.75]
            rate = ffmpeg_speed(src, tmp, ks_rate, "rate")
            for k, y in rate.items():
                for L in LENGTHS:
                    rows.append(dict(base, task="speed", method="rate", k=k, L=L,
                                     f=speed_feats(y[: L * sr], sr)))
                if mode == "H1" and k == 1.75 and rec in ("090", "120", "065", "002"):
                    os.makedirs(DEMO, exist_ok=True)
                    sf.write(os.path.join(DEMO, f"{rec}_orig_8s.wav"), seg[: 8 * sr], sr, subtype="PCM_16")
                    sf.write(os.path.join(DEMO, f"{rec}_rate1.75_8s.wav"), y[: 8 * sr], sr, subtype="PCM_16")
            if mode == "H1":
                tempo = ffmpeg_speed(src, tmp, KS, "tempo")
                for k, y in tempo.items():
                    for L in TEMPO_LENGTHS:
                        rows.append(dict(base, task="speed", method="tempo", k=k, L=L,
                                         f=speed_feats(y[: L * sr], sr)))
            # splices (and unmodified controls), drawn away from the speed segment where possible
            for L in SPLICE_L:
                if mode != "H1":
                    a = int(rng.uniform(0, dur - L - 1) * sr)
                    rows.append(dict(base, task="splice", kind="none", d=0, L=L, t_splice=None,
                                     f=splice_feats(x[a: a + L * sr], sr)))
                    continue
                for rep in range(2):
                    a = int(rng.uniform(0, dur - L - 1) * sr)
                    rows.append(dict(base, task="splice", kind="none", d=0, L=L, t_splice=None, rep=rep,
                                     f=splice_feats(x[a: a + L * sr], sr)))
                for d in DELETES:
                    a = int(rng.uniform(0, dur - L - d - 1) * sr)
                    c = float(rng.uniform(0.3 * L, 0.7 * L))
                    ci = int(c * sr)
                    y = np.concatenate([x[a: a + ci], x[a + ci + d * sr: a + L * sr + d * sr]])
                    rows.append(dict(base, task="splice", kind="delete", d=d, L=L, t_splice=round(c, 3),
                                     f=splice_feats(y, sr)))
                for d in INSERTS:
                    a = int(rng.uniform(0, dur - L - 1) * sr)
                    c = float(rng.uniform(0.3 * (L - d), 0.7 * (L - d)))
                    ci = int(c * sr)
                    # insert from >= 60 s away
                    while True:
                        b = int(rng.uniform(0, dur - d - 1) * sr)
                        if abs(b - a) > 60 * sr:
                            break
                    y = np.concatenate([x[a: a + ci], x[b: b + d * sr], x[a + ci: a + (L - d) * sr]])
                    rows.append(dict(base, task="splice", kind="insert", d=d, L=L, t_splice=round(c, 3),
                                     t_splice_end=round(c + d, 3), f=splice_feats(y, sr)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return rec, rows, time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--only", default=None, help="comma list of recs")
    a = ap.parse_args()
    split = json.load(open(os.path.join(HERE, "split.json")))
    jobs = [(r, "H1", "dev", "H1") for r in split["H1"]["dev"]] + \
           [(r, "H1", "holdout", "H1") for r in split["H1"]["holdout"]] + \
           [(r, "H0", "dev", "H0") for r in split["H0"]["dev_sources"]] + \
           [(r, "H0", "holdout", "H0") for r in split["H0"]["holdout_sources"]]
    os.makedirs(os.path.join(OUT, "tmp"), exist_ok=True)
    outp = os.path.join(OUT, "features.jsonl")
    done = set()
    if os.path.exists(outp):
        for line in open(outp):
            done.add(json.loads(line)["rec"])
    jobs = [j for j in jobs if j[0] not in done]
    if a.only:
        jobs = [j for j in jobs if j[0] in a.only.split(",")]
    # interleave dev/holdout/H0 so partial runs are balanced
    jobs.sort(key=lambda j: zlib.crc32(j[0].encode()))
    if a.limit:
        jobs = jobs[: a.limit]
    print(f"{len(jobs)} jobs ({len(done)} recs already done)", flush=True)
    from multiprocessing import Pool
    with Pool(a.workers) as pool, open(outp, "a") as fh:
        for i, (rec, rows, dt) in enumerate(pool.imap_unordered(job, jobs)):
            for r in rows:
                fh.write(json.dumps(r) + "\n")
            fh.flush()
            print(f"[{i + 1}/{len(jobs)}] {rec}: {len(rows)} rows in {dt:.0f}s", flush=True)


if __name__ == "__main__":
    main()
