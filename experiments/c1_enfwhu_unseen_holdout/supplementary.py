"""Post-hoc (NO tuning) supplementary analyses appended to RESULTS.json under 'supplementary':
 - own-day vs sampled-wrong-day ranking per length (would the correct day win a 3-way search?)
 - concentration of wrong-reference false matches by recording
 - ground-truth audit summary (rec-vs-H1_ref offsets, ambiguous GT, reference overlap)"""
import json, os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import HERE, wilson
from analyze import add_err
R = json.load(open(os.path.join(HERE, 'RESULTS.json'))); fz = json.load(open(os.path.join(HERE, 'frozen.json')))
th = {int(k): v for k, v in fz['thresholds'].items()}; g = json.load(open(os.path.join(HERE, 'gt_w16.json')))
sup = {}
for sp in ('dev', 'holdout'):
    d = add_err(pd.read_parquet(os.path.join(HERE, 'trials', f"{fz['tag']}_{sp}.parquet")), 0, g)
    d = d[~d.gt_ambiguous | (d.kind != 'h1_true')]
    d['iss'] = d.peak > d.L.map(th)
    h = d[d.kind == 'h1_true'].set_index(['fid', 'L', 'k'])
    j = h.join(d[d.kind == 'h1_wrong'].groupby(['fid', 'L', 'k']).peak.max().rename('wrong_max'))
    rk = {}
    for L, x in j.groupby(level='L'):
        k1 = int((x.peak > x.wrong_max).sum()); k2 = int(((x.peak > x.wrong_max) & (x.err.abs() <= 5)).sum())
        rk[int(L)] = dict(n=len(x), own_day_beats_both_wrong_days=k1, rate=round(k1 / len(x), 4), ci=wilson(k1, len(x)),
                          own_day_wins_and_offset_within_5s=k2, rate2=round(k2 / len(x), 4), ci2=wilson(k2, len(x)))
    w = d[(d.kind == 'h1_wrong') & d.iss]
    sup[sp] = dict(three_way_day_search=rk, wrong_ref_false_matches_by_file=w.groupby('fid').size().sort_values(ascending=False).to_dict(),
                   wrong_ref_false_matches_total=len(w))
v = list(g.values()); rel = [o for o in v if o['rec_ref_r_at_d'] >= 0.9]
sup['ground_truth_audit'] = dict(
    rec_vs_H1ref_offset_reliable_files=len(rel), of=len(v),
    offset_s_median=float(np.median([o['rec_ref_d'] for o in rel])), offset_s_min=float(min(o['rec_ref_d'] for o in rel)),
    offset_s_max=float(max(o['rec_ref_d'] for o in rel)),
    note='per-file offset between recording and its H1_ref, not constant -> README GT good to ~+-5 s only',
    duplicated_reference_day='089-107 (hours repeated); 090 and 091 GT ambiguous; dev only',
    max_cross_day_ncc_30min=0.811)
R['supplementary'] = sup
json.dump(R, open(os.path.join(HERE, 'RESULTS.json'), 'w'), indent=1, default=float)
for sp in ('dev', 'holdout'):
    print(sp, {L: (x['own_day_beats_both_wrong_days'], x['n'], x['rate']) for L, x in sup[sp]['three_way_day_search'].items()})
    print(sp, 'wrong-ref FM by file', sup[sp]['wrong_ref_false_matches_by_file'])
