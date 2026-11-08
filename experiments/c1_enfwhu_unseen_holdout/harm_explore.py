"""DEV-only extractor exploration: recombine stored per-harmonic estimates (fk, snrk) in different ways and
measure agreement with the recording's own H1_ref trace (max corr over lags -6..6 s). No holdout files touched."""
import numpy as np, json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
sp = split(); ids = sp['H1']['dev']

def recombine(tr, mode, T):
    fk, s = tr['fk'].astype(float), tr['snrk'].astype(float)
    if mode == 'base': return tr['f']
    if mode == 'frame':   # per-frame SNR weights, harmonics below T dropped
        w = np.where(s >= T, s, 0)
    elif mode == 'frame2':
        w = np.where(s >= T, s ** 2, 0)
    elif mode == 'file':  # per-file harmonic selection by median SNR
        m = np.median(s, axis=0); w = np.tile(np.where(m >= T, m, 0), (len(fk), 1))
        if w.sum() == 0: w = np.tile((m == m.max()).astype(float), (len(fk), 1))
    elif mode == 'best':
        m = np.median(s, axis=0); w = np.tile((m == m.max()).astype(float), (len(fk), 1))
    den = w.sum(1); f = np.where(den > 0, (w * fk).sum(1) / np.maximum(den, 1e-30), tr['f'])
    return f

def agree(f, ref):
    best = -1
    for L in range(-6, 7):
        i0 = max(0, -L); i1 = min(len(ref), len(f) - L)
        a = f[i0 + L:i1 + L]; b = ref[i0:i1]
        ok = np.abs(a - np.median(a)) < 0.1
        if ok.sum() < 50: continue
        best = max(best, np.corrcoef(a[ok], b[ok])[0, 1])
    return best

res = {}
modes = [('base', 0), ('frame', 5), ('frame', 10), ('frame', 20), ('frame2', 5), ('file', 10), ('file', 20), ('file', 50), ('best', 0)]
for rid in ids:
    tr = load_trace('w16', 'H1', rid); ref = load_trace('w16', 'H1_ref', rid + '_ref')['f']
    res[rid] = [agree(recombine(tr, m, T), ref) for m, T in modes]
A = np.array(list(res.values()))
for j, (m, T) in enumerate(modes):
    print(f'{m:6s} T={T:3d}  median r {np.median(A[:, j]):.3f}  mean r {A[:, j].mean():.3f}  #r>0.9 {(A[:, j] > 0.9).sum()}  #r>0.7 {(A[:, j] > 0.7).sum()}  n={len(A)}')
