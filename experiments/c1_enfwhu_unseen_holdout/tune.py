"""DEV-only selection. For each matcher setting (trials/<tag>_dev.parquet) and decision statistic,
set per-length thresholds on dev nulls (FMR<=5%) and score the dev true-match rate (issued AND
|err|<=TOL s). Picks the best (tag, stat) by mean true-match rate over lengths; writes frozen.json.
usage: python tune.py --dcal <s> --tol 5 tag1 tag2 ..."""
import sys, os, json, argparse
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import HERE
from analyze import add_err, thresholds, metrics, STATS

ap = argparse.ArgumentParser(); ap.add_argument('--dcal', type=float, required=True); ap.add_argument('--tol', type=float, default=5)
ap.add_argument('--stat', default=None); ap.add_argument('--lens', default='120,300,600'); ap.add_argument('--out', default='frozen.json'); ap.add_argument('tags', nargs='+'); a = ap.parse_args()
rows = []; best = None
for tag in a.tags:
    dev = add_err(pd.read_parquet(os.path.join(HERE, 'trials', f'{tag}_dev.parquet')), a.dcal)
    for stat in ([a.stat] if a.stat else STATS):
        th = thresholds(dev, stat)
        m = metrics(dev, th, stat)
        tm = []
        for L, mm in m.items():
            h1 = dev[(dev.kind == 'h1_true') & (dev.L == L) & ~dev.gt_ambiguous]
            tm.append(float(((h1[stat] > th[L]) & (h1.err.abs() <= a.tol)).mean()))
        score = float(np.mean(tm))
        rows.append(dict(tag=tag, stat=stat, score=round(score, 4), **{f'tmr_L{L}': round(v, 3) for L, v in zip(m, tm)},
                         **{f'top1acc5_L{L}': m[L]['top1_no_threshold_acc5'] for L in m},
                         **{f'cov_L{L}': m[L]['coverage'] for L in m}))
        if best is None or score > best[0]:
            best = (score, tag, stat, th, json.loads(dev['params'].iloc[0]), m)
tab = pd.DataFrame(rows).sort_values('score', ascending=False)
pd.set_option('display.width', 250); print(tab.to_string(index=False))
tab.to_csv(os.path.join(HERE, a.out.replace('frozen', 'tuning_dev').replace('.json', '.csv')), index=False)
score, tag, stat, th, params, m = best
json.dump(dict(tag=tag, stat=stat, lens=a.lens, thresholds=th, params=params, dcal=a.dcal, tol_for_selection=a.tol,
               dev_score=score, dev_metrics=m, note='frozen on DEV only; holdout untouched until final_eval.py'),
          open(os.path.join(HERE, a.out), 'w'), indent=1)
print('FROZEN:', tag, stat, th)
