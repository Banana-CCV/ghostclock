"""ONE-SHOT holdout evaluation with the frozen DEV settings (frozen.json). Runs the holdout trials with
exactly the frozen matcher params, applies the frozen per-length thresholds, writes RESULTS.json.
usage: python final_eval.py"""
import sys, os, json, subprocess
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import HERE
from analyze import add_err, metrics

fz = json.load(open(os.path.join(HERE, 'frozen.json')))
p = fz['params']; tag = fz['tag']; stat = fz['stat']; th = {int(k): v for k, v in fz['thresholds'].items()}
out = os.path.join(HERE, 'trials', f'{tag}_holdout.parquet')
if not os.path.exists(out):
    subprocess.run([sys.executable, os.path.join(HERE, 'run_trials.py'), '--cfg', p['cfg'], '--split', 'holdout',
                    '--hp', str(p['hp']), '--wmode', p['wmode'], '--qthr', 'none' if p['qthr'] is None else str(p['qthr']),
                    '--clip', str(p['clip']), '--lens', fz.get('lens', '120,300,600'), '--medfilt', str(p.get('medfilt', 0)), '--tag', tag], check=True)
gt = json.load(open(os.path.join(HERE, 'gt_w16.json')))
ho = add_err(pd.read_parquet(out), fz['dcal'], gt)
dev = add_err(pd.read_parquet(os.path.join(HERE, 'trials', f'{tag}_dev.parquet')), fz['dcal'], gt)
res = dict(
    protocol=dict(dataset='ENF-WHU (H1 real recordings vs 24-h one-day reference; H0 no-ENF recordings)',
                  excerpt_lengths_s=sorted(int(v) for v in ho.L.unique()), excerpts_per_file_per_length=int(ho.k.max() + 1),
                  wrong_refs_per_excerpt=int(ho[ho.kind == 'h1_wrong'].groupby(['fid', 'L', 'k']).size().max()),
                  h0_refs_per_excerpt=int(ho[ho.kind == 'h0'].groupby(['fid', 'L', 'k']).size().max()),
                  decision='issue a match iff %s > per-length threshold set on DEV nulls (FMR<=5%%)' % stat,
                  ground_truth='README rule: lag of noise-free H1_ref inside one-day ref (NCC), minus dcal; dcal=%.3f s fixed from DEV' % fz['dcal'],
                  frozen=fz),
    holdout=dict(all_excerpts=metrics(ho, th, stat), first_excerpt_only=metrics(ho, th, stat, only_k0=True)),
    dev=dict(all_excerpts=metrics(dev, th, stat)),
    holdout_also_vs_readme_gt_without_dcal=metrics(add_err(pd.read_parquet(out), 0.0), th, stat),
)
# error distribution of issued correct-ref matches
h1 = ho[(ho.kind == 'h1_true')]
iss = h1[h1.apply(lambda r: r[stat] > th[int(r.L)], axis=1)]
res['holdout']['issued_abs_err_s_percentiles'] = {str(q): float(np.percentile(iss.err.abs(), q)) for q in (50, 90, 95, 99)} if len(iss) else None
res['holdout']['n_files'] = dict(H1=int(h1.fid.nunique()), H0=int(ho[ho.kind == 'h0'].fid.nunique()),
                                 days=int(ho[ho.kind == 'h1_true'].ref_day.nunique()))
json.dump(res, open(os.path.join(HERE, 'RESULTS.json'), 'w'), indent=1, default=float)
for L, m in res['holdout']['all_excerpts'].items():
    print(L, {k: m[k] for k in ('h1_n', 'issued', 'coverage', 'coverage_ci', 'acc1_among_issued', 'acc1_ci', 'acc5_among_issued', 'acc5_ci',
                                'h1_wrong_n', 'h1_wrong_fmr', 'h0_n', 'h0_fmr', 'null_fmr_ci', 'top1_no_threshold_acc5')})
