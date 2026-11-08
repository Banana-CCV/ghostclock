"""Freeze a deterministic grouped dev/holdout split (run once, BEFORE any tuning).
H1: grouped by recording day (= one-day reference file; e.g. 043-059 is one group of 17 recordings).
H0: grouped by source recording O01..O10 (crops 01..40 mapped to their source in h0_groups.json).
Groups are shuffled with a fixed seed and assigned to dev until dev holds >= 60% of recordings."""
import json, os, glob, random
D='datasets/raw/enf-whu/repo/ENF-WHU-Dataset'; SEED=20261108
days=sorted(os.path.basename(f)[:-8] for f in glob.glob(D+'/H1_ref_one_day/*.wav'))
def members(g):
    a=g.split('-'); return [f'{i:03d}' for i in range(int(a[0]), int(a[-1])+1)]
h0=json.load(open('work/C1/h0_groups.json'))
h0g={f'O{i:02d}':[f'O{i:02d}'] for i in range(1,11)}
for crop,v in h0.items(): h0g[v['source']].append(crop)
def assign(groups, frac, rng):
    keys=sorted(groups); rng.shuffle(keys); total=sum(len(groups[k]) for k in keys); dev=[]; n=0
    for k in keys:
        if n < frac*total: dev.append(k); n+=len(groups[k])
    return sorted(dev), sorted(set(keys)-set(dev))
rng=random.Random(SEED)
h1g={d:members(d) for d in days}
d1,h1=assign(h1g,0.6,rng); d0,h0_=assign(h0g,0.6,rng)
split=dict(seed=SEED, created='2026-11-08, before any tuning',
  rule='grouped: H1 by recording day (one-day ref), H0 by source O-file; groups shuffled (random.Random(seed)) and taken into dev until >=60% of files',
  H1_days=dict(dev=d1, holdout=h1), H1=dict(dev=sorted(sum((h1g[g] for g in d1),[])), holdout=sorted(sum((h1g[g] for g in h1),[]))),
  H0_groups=dict(dev={g:sorted(h0g[g]) for g in d0}, holdout={g:sorted(h0g[g]) for g in h0_}),
  H0=dict(dev=sorted(sum((h0g[g] for g in d0),[])), holdout=sorted(sum((h0g[g] for g in h0_),[]))))
json.dump(split,open('work/C1/split.json','w'),indent=1)
for k in ['H1','H0']: print(k, {s:len(v) for s,v in split[k].items()})
print('H1 days', {s:len(v) for s,v in split['H1_days'].items()}, 'H0 groups', {s:list(v) for s,v in split['H0_groups'].items()})
