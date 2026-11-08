"""Extract ENF traces for every ENF-WHU file under a named config; cache to work/C1/cache/<cfg>/<group>/<name>.npz
usage: python extract_all.py <cfg> [--groups H1,H1_ref,H0,H1_ref_one_day] [--procs 4]
"""
import os, sys, glob, time, argparse
import numpy as np
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import enf

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, 'datasets', 'raw', 'enf-whu', 'repo', 'ENF-WHU-Dataset')
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cache')
CONFIGS = {
    'w16': dict(win_s=16.0, harmonics=(1, 2, 3, 4, 5, 6, 7)),
    'w8': dict(win_s=8.0, harmonics=(1, 2, 3, 4, 5, 6, 7)),
}


def job(a):
    cfg, grp, path = a
    out = os.path.join(CACHE, cfg, grp, os.path.basename(path)[:-4] + '.npz')
    if os.path.exists(out):
        return out, 0.0
    t = time.time()
    x, fs = enf.load_audio(path)
    r = enf.extract_enf(x, fs, **CONFIGS[cfg])
    os.makedirs(os.path.dirname(out), exist_ok=True)
    np.savez_compressed(out, t=r['t'], f=r['f'].astype(np.float64), q=r['q'].astype(np.float32),
                        fk=r['fk'].astype(np.float32), snrk=r['snrk'].astype(np.float32),
                        harmonics=r['harmonics'])
    return out, time.time() - t


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('cfg'); ap.add_argument('--groups', default='H1,H1_ref,H0,H1_ref_one_day')
    ap.add_argument('--procs', type=int, default=4); a = ap.parse_args()
    jobs = []
    for g in a.groups.split(','):
        files = sorted(glob.glob(os.path.join(DATA, g, '*.wav')))
        jobs += [(a.cfg, g, f) for f in files]
    # big files first for load balance
    jobs.sort(key=lambda j: -os.path.getsize(j[2]))
    t0 = time.time()
    with Pool(a.procs) as p:
        for i, (out, dt) in enumerate(p.imap_unordered(job, jobs)):
            print(f'[{i+1}/{len(jobs)}] {os.path.relpath(out, CACHE)} {dt:.1f}s (elapsed {time.time()-t0:.0f}s)', flush=True)
