"""Sanity check for wrong-reference trials: do any two one-day references cover overlapping time?
Take 4 x 30-min chunks of each day reference and search them in every other day reference (NCC).
Overlapping days would show NCC ~1 at some lag. Output: work/C1/ref_overlap_<cfg>.json"""
import sys, os, json
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
import match
cfg = sys.argv[1] if len(sys.argv) > 1 else 'w16'
days, _ = day_groups()
tr = {d: load_trace(cfg, 'H1_ref_one_day', d + '_ref') for d in days}
R = {d: match.Reference(match.preprocess(t['f'], t['q'], wmode='none', clip_hz=0.5)[0], ref_valid(t)) for d, t in tr.items()}
res = {}; worst = []
for a in days:
    n = len(tr[a]['f']); v = ref_valid(tr[a])
    starts = [int(n * p) for p in (0.1, 0.35, 0.6, 0.85)]
    for b in days:
        if a == b: continue
        best = -1
        for s in starts:
            x, w = match.preprocess(tr[a]['f'][s:s + 1800], tr[a]['q'][s:s + 1800], wmode='none', clip_hz=0.5)
            w = w * v[s:s + 1800]
            best = max(best, match.peak_stats(R[b].ncc(x, w))['peak'])
        res[f'{a}|{b}'] = best; worst.append((best, a, b))
worst.sort(reverse=True)
print('top cross-day NCC (30-min chunks):', [(round(p, 3), a, b) for p, a, b in worst[:8]])
print('valid fraction per day ref:', {d: round(float(ref_valid(t).mean()), 4) for d, t in tr.items()})
json.dump(dict(max_ncc=res, top=[(p, a, b) for p, a, b in worst[:20]],
               valid_frac={d: float(ref_valid(t).mean()) for d, t in tr.items()},
               n_frames={d: int(len(t['f'])) for d, t in tr.items()}), open(os.path.join(HERE, f'ref_overlap_{cfg}.json'), 'w'), indent=1)
