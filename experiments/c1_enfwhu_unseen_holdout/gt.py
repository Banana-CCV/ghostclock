"""Ground truth + alignment audit.
For every H1 recording:
  (a) README ground truth: locate the noise-free H1_ref/<id>_ref.wav ENF trace inside its one-day
      reference trace by full-length NCC (unweighted) -> lag_ref (s, sub-second), peak, margin.
  (b) recording-vs-H1_ref alignment: NCC of the recording's own ENF trace against its H1_ref trace at
      integer lags -30..30 s (+ parabolic refinement) -> d (s). d>0 means the recording's trace at
      t+d matches the reference at t.
Output: work/C1/gt_<cfg>.json.  (a) uses only reference files; (b) is an audit, reported per split.
usage: python gt.py w16
"""
import sys, json, os
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
import match

cfg = sys.argv[1] if len(sys.argv) > 1 else 'w16'
days, d_of = day_groups()
sp = split()
out = {}
refs = {}
for rid in sorted(d_of):
    day = d_of[rid]
    if day not in refs:
        tr = load_trace(cfg, 'H1_ref_one_day', day + '_ref')
        refs[day] = match.Reference(tr['f'], ref_valid(tr))
    R = refs[day]
    hr = load_trace(cfg, 'H1_ref', rid + '_ref')
    x, w = match.preprocess(hr['f'], hr['q'], wmode='none', clip_hz=0.5)
    r = R.ncc(x, w)
    st = match.peak_stats(r, excl=60)
    # (b) recording vs its own H1_ref at small lags
    rc = load_trace(cfg, 'H1', rid)
    xr, wr = match.preprocess(rc['f'], rc['q'], wmode='q', q_thr=None, clip_hz=0.2)
    yr = hr['f'] - np.median(hr['f'])
    lags = np.arange(-30, 31); cs = []
    for L in lags:
        # recording frame i+L  <->  ref frame i
        i0 = max(0, -L); i1 = min(len(yr), len(xr) - L)
        a = xr[i0 + L:i1 + L]; ww = wr[i0 + L:i1 + L]; b = yr[i0:i1]
        am = (ww * a).sum() / ww.sum(); bm = (ww * b).sum() / ww.sum()
        cs.append((ww * (a - am) * (b - bm)).sum() / np.sqrt((ww * (a - am) ** 2).sum() * (ww * (b - bm) ** 2).sum()))
    cs = np.array(cs); k = int(np.argmax(cs)); d = float(lags[k])
    if 0 < k < len(cs) - 1:
        den = cs[k - 1] - 2 * cs[k] + cs[k + 1]
        if abs(den) > 1e-12: d += float(np.clip(0.5 * (cs[k - 1] - cs[k + 1]) / den, -.5, .5))
    out[rid] = dict(day=day, split='dev' if rid in sp['H1']['dev'] else 'holdout',
                    lag_ref=st['lag'], ref_peak=st['peak'], ref_margin=st['margin'],
                    rec_ref_d=d, rec_ref_r_at_d=float(cs[k]), rec_ref_r_at_0=float(cs[30]),
                    rec_len=int(len(rc['f'])), ref_len=int(len(hr['f'])))
    print(rid, day, {k_: (round(v, 3) if isinstance(v, float) else v) for k_, v in out[rid].items() if k_ not in ('day',)}, flush=True)
json.dump(out, open(os.path.join(HERE, f'gt_{cfg}.json'), 'w'), indent=1)
for s in ('dev', 'holdout'):
    v = [o for o in out.values() if o['split'] == s]
    d = np.array([o['rec_ref_d'] for o in v]); rr = np.array([o['rec_ref_r_at_d'] for o in v])
    good = rr > 0.8
    print(s, 'n', len(v), 'ref_peak min', round(min(o['ref_peak'] for o in v), 4), 'ref_margin min', round(min(o['ref_margin'] for o in v), 4))
    print(s, 'rec-vs-ref d (all): median', np.median(d).round(2), 'IQR', np.percentile(d, [25, 75]).round(2),
          '| r>0.8 subset n', good.sum(), 'median', np.median(d[good]).round(2), 'p5/p95', np.percentile(d[good], [5, 95]).round(2))
