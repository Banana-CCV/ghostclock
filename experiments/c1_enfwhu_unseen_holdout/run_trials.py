"""Run matching trials for one split and one matcher setting; writes work/C1/trials/<tag>_<split>.parquet
Trial kinds:
  h1_true  : excerpt of H1 recording vs its OWN one-day reference (full 24 h); gt known
  h1_wrong : same excerpt vs a different day's reference from the same split (any issued match = false)
  h0       : excerpt of an H0 recording (no ENF) vs a day reference from the same split (any issued match = false)
Excerpt starts are drawn from a seeded RNG keyed only on (file, L, k), so they are identical across settings.
usage: python run_trials.py --cfg w16 --split dev --hp 0 --wmode q --qthr none --tag w16_hp0_q
"""
import sys, os, json, argparse, zlib
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
import match

ap = argparse.ArgumentParser()
ap.add_argument('--cfg', default='w16'); ap.add_argument('--split', default='dev')
ap.add_argument('--hp', type=int, default=0); ap.add_argument('--wmode', default='q')
ap.add_argument('--qthr', default='none'); ap.add_argument('--clip', type=float, default=0.1)
ap.add_argument('--lens', default='120,300,600'); ap.add_argument('--K', type=int, default=3)
ap.add_argument('--nwrong', type=int, default=2); ap.add_argument('--nh0ref', type=int, default=3)
ap.add_argument('--tag', required=True); ap.add_argument('--medfilt', type=int, default=0)
a = ap.parse_args()
qthr = None if a.qthr == 'none' else float(a.qthr)
LENS = [int(v) for v in a.lens.split(',')]
days, d_of = day_groups(); sp = split()
gt = json.load(open(os.path.join(HERE, 'gt_w16.json')))  # GT always from the w16 reference-vs-reference match
sdays = sp['H1_days'][a.split]


def rng_for(*key):
    return np.random.default_rng(zlib.crc32('|'.join(map(str, key)).encode()))


refs = {}
def get_ref(day):
    if day not in refs:
        tr = load_trace(a.cfg, 'H1_ref_one_day', day + '_ref')
        v = ref_valid(tr)
        y, _ = match.preprocess(tr['f'], tr['q'], hp_s=a.hp, wmode='none', clip_hz=0.5)
        refs[day] = match.Reference(y, v)
    return refs[day]


def prep(tr):
    return match.preprocess(tr['f'], tr['q'], hp_s=a.hp, wmode=a.wmode, q_thr=qthr, clip_hz=a.clip, medfilt=a.medfilt)


dupdays = {d for d, v in json.load(open(os.path.join(HERE, 'dup_scan_w16.json'))).items() if v['dup_chunks'] > 0}
rawref = {}
def gt_ambiguous(day, g0, L):
    """True if the reference stretch at the ground-truth offset occurs (NCC>=0.995) elsewhere in the same day
    reference (dataset artifact found by dup_scan.py: 089-107 repeats whole hours)."""
    if day not in dupdays:
        return False
    if day not in rawref:
        tr = load_trace('w16', 'H1_ref_one_day', day + '_ref'); rawref[day] = (tr, match.Reference(tr['f'], ref_valid(tr)))
    tr, R = rawref[day]; g0 = int(round(g0))
    xx, ww = match.preprocess(tr['f'][g0:g0 + L], tr['q'][g0:g0 + L], wmode='none', clip_hz=0.5)
    r = R.ncc(xx, ww); r[max(0, g0 - 60):g0 + 61] = -np.inf
    return bool(np.max(r) >= 0.995)


rows = []
def run(kind, fid, L, k, s, day, x, w, gtl=None):
    if w[s:s + L].sum() < 0.2 * L:  # essentially no usable frames -> abstain by construction
        st = dict(lag=np.nan, peak=-1.0, second=-1.0, margin=0.0, z=0.0)
    else:
        st = match.peak_stats(get_ref(day).ncc(x[s:s + L], w[s:s + L]))
    rows.append(dict(kind=kind, fid=fid, L=L, k=k, start=s, ref_day=day, gt_readme=gtl,
                     gt_ambiguous=(gt_ambiguous(day, gtl, L) if kind == 'h1_true' else False), **st))


for rid in sp['H1'][a.split]:
    tr = load_trace(a.cfg, 'H1', rid); x, w = prep(tr); n = len(x)
    others = [d for d in sdays if d != d_of[rid]]
    for L in LENS:
        if n < L:
            continue
        for k in range(a.K):
            s = int(rng_for(rid, L, k).integers(0, n - L + 1))
            run('h1_true', rid, L, k, s, d_of[rid], x, w, gt[rid]['lag_ref'] + s)
            wr = rng_for('wrong', rid, L, k).choice(others, size=min(a.nwrong, len(others)), replace=False)
            for d in wr:
                run('h1_wrong', rid, L, k, s, d, x, w)
for fid in sp['H0'][a.split]:
    tr = load_trace(a.cfg, 'H0', fid); x, w = prep(tr); n = len(x)
    for L in LENS:
        if n < L:
            continue
        for k in range(a.K):
            s = int(rng_for(fid, L, k).integers(0, n - L + 1))
            for d in rng_for('h0ref', fid, L, k).choice(sdays, size=min(a.nh0ref, len(sdays)), replace=False):
                run('h0', fid, L, k, s, d, x, w)
os.makedirs(os.path.join(HERE, 'trials'), exist_ok=True)
df = pd.DataFrame(rows); df['tag'] = a.tag; df['cfg'] = a.cfg; df['split'] = a.split
df['params'] = json.dumps(dict(cfg=a.cfg, hp=a.hp, wmode=a.wmode, qthr=qthr, clip=a.clip, medfilt=a.medfilt))
out = os.path.join(HERE, 'trials', f'{a.tag}_{a.split}.parquet'); df.to_parquet(out)
print(out, len(df), df.groupby(['kind', 'L']).size().to_dict())
