import os, json, glob
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(ROOT, 'datasets', 'raw', 'enf-whu', 'repo', 'ENF-WHU-Dataset')
CACHE = os.path.join(HERE, 'cache')


def load_trace(cfg, grp, name):
    d = np.load(os.path.join(CACHE, cfg, grp, name + '.npz'))
    return {k: d[k] for k in d.files}


def day_groups():
    days = sorted(os.path.basename(f)[:-8] for f in glob.glob(os.path.join(DATA, 'H1_ref_one_day', '*.wav')))
    m = {}
    for d in days:
        a = d.split('-')
        for i in range(int(a[0]), int(a[-1]) + 1):
            m[f'{i:03d}'] = d
    return days, m


def split():
    return json.load(open(os.path.join(HERE, 'split.json')))


def ref_valid(tr):
    """Reference frame validity: plausible frequency and a clean spectral peak."""
    return (np.abs(tr['f'] - 50.0) < 0.5) & (tr['q'] > 10.0)


def wilson(k, n, z=1.96):
    if n == 0:
        return [None, None]
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d; h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(float(c - h), 4), round(float(c + h), 4)]
