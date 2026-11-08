"""Dataset audit: find internally duplicated stretches inside each one-day reference.
For each day ref, every 600-s chunk (step 600 s) is searched in the same day ref; another lag (>120 s away)
with NCC >= 0.995 means that stretch of reference ENF appears (near-)identically twice. Writes dup_scan_w16.json"""
import sys, os, json
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
import match
days, d_of = day_groups(); out = {}
for day in days:
    tr = load_trace('w16', 'H1_ref_one_day', day + '_ref'); f = tr['f']
    R = match.Reference(f, ref_valid(tr)); n = len(f); dup = []
    for s in range(0, n - 600, 600):
        x, w = match.preprocess(f[s:s + 600], tr['q'][s:s + 600], wmode='none', clip_hz=0.5)
        r = R.ncc(x, w); r[max(0, s - 120):s + 121] = -np.inf
        k = int(np.argmax(r))
        if r[k] >= 0.995:
            dup.append((s, k, round(float(r[k]), 4), round(1000 * float(np.sqrt(np.mean((f[s:s+600] - f[k:k+600]) ** 2))), 3)))
    out[day] = dict(n_chunks=len(range(0, n - 600, 600)), dup_chunks=len(dup), examples=dup[:6])
    print(day, out[day]['dup_chunks'], '/', out[day]['n_chunks'], dup[:3], flush=True)
json.dump(out, open(os.path.join(HERE, 'dup_scan_w16.json'), 'w'), indent=1)
