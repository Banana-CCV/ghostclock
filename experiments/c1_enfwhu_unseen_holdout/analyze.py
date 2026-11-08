"""Score trials. Threshold per excerpt length L is set on DEV null trials (h1_wrong + h0) so the
dev false-match rate is <= 5%; a match is issued iff score > threshold.
Functions are imported by tune.py and final_eval.py."""
import numpy as np, pandas as pd
from common import wilson

STATS = ('peak', 'margin', 'z')


def add_err(df, dcal, gtjson=None, rmin=0.9):
    """err vs README GT (minus a constant dcal). If gtjson given, also err_ref: vs a per-file refined GT
    gt_readme - d_i, where d_i = measured recording-vs-H1_ref lag (only when that alignment is reliable, r>=rmin)."""
    df = df.copy()
    df['gt'] = df['gt_readme'] - dcal
    df['err'] = df['lag'] - df['gt']
    if gtjson is not None:
        d = {k: (v['rec_ref_d'] if v['rec_ref_r_at_d'] >= rmin else np.nan) for k, v in gtjson.items()}
        df['d_i'] = df.fid.map(d).astype(float)
        df['err_ref'] = df['lag'] - (df['gt_readme'] - df['d_i'])
    return df


def thresholds(dev, stat, fmr=0.05):
    th = {}
    for L, g in dev[dev.kind != 'h1_true'].groupby('L'):
        v = np.sort(g[stat].values)
        # smallest t with mean(v > t) <= fmr
        idx = int(np.ceil((1 - fmr) * len(v))) - 1
        th[int(L)] = float(v[max(idx, 0)])
    return th


def metrics(df, th, stat, only_k0=False):
    if only_k0:
        df = df[df.k == 0]
    out = {}
    for L in sorted(df.L.unique()):
        g = df[df.L == L]; t = th[int(L)]
        amb = g[(g.kind == 'h1_true') & g.gt_ambiguous]
        h1 = g[(g.kind == 'h1_true') & ~g.gt_ambiguous]; iss = h1[h1[stat] > t]
        c1 = int((iss.err.abs() <= 1).sum()); c5 = int((iss.err.abs() <= 5).sum())
        top1_5 = int((h1.err.abs() <= 5).sum()); top1_1 = int((h1.err.abs() <= 1).sum())
        m = dict(threshold=t, stat=stat, h1_excluded_ambiguous_gt=len(amb),
                 h1_n=len(h1), h1_files=int(h1.fid.nunique()), issued=len(iss), abstained=len(h1) - len(iss),
                 coverage=round(len(iss) / max(len(h1), 1), 4), coverage_ci=wilson(len(iss), len(h1)),
                 acc1_among_issued=round(c1 / max(len(iss), 1), 4), acc1_ci=wilson(c1, len(iss)), correct1=c1,
                 acc5_among_issued=round(c5 / max(len(iss), 1), 4), acc5_ci=wilson(c5, len(iss)), correct5=c5,
                 wrong_offset_issued=len(iss) - c5,
                 true_match_rate5=round(c5 / max(len(h1), 1), 4), tmr5_ci=wilson(c5, len(h1)),
                 top1_no_threshold_acc1=round(top1_1 / max(len(h1), 1), 4), top1_no_threshold_acc5=round(top1_5 / max(len(h1), 1), 4),
                 top1_acc5_ci=wilson(top1_5, len(h1)),
                 median_abs_err_issued_s=float(iss.err.abs().median()) if len(iss) else None)
        if 'err_ref' in iss:
            ir = iss[iss.err_ref.notna()]; c1r = int((ir.err_ref.abs() <= 1).sum()); c2r = int((ir.err_ref.abs() <= 2).sum())
            m.update(refinedGT_issued_n=len(ir), refinedGT_acc1=round(c1r / max(len(ir), 1), 4), refinedGT_acc1_ci=wilson(c1r, len(ir)),
                     refinedGT_acc2=round(c2r / max(len(ir), 1), 4), refinedGT_acc2_ci=wilson(c2r, len(ir)),
                     refinedGT_median_abs_err_s=float(ir.err_ref.abs().median()) if len(ir) else None)
        for kind in ('h1_wrong', 'h0'):
            gk = g[g.kind == kind]; fm = int((gk[stat] > t).sum())
            m[f'{kind}_n'] = len(gk); m[f'{kind}_files'] = int(gk.fid.nunique()); m[f'{kind}_false_matches'] = fm
            m[f'{kind}_fmr'] = round(fm / max(len(gk), 1), 4); m[f'{kind}_fmr_ci'] = wilson(fm, len(gk))
        nul = g[g.kind != 'h1_true']; fm = int((nul[stat] > t).sum())
        m['null_n'] = len(nul); m['null_false_matches'] = fm; m['null_fmr'] = round(fm / max(len(nul), 1), 4); m['null_fmr_ci'] = wilson(fm, len(nul))
        out[int(L)] = m
    return out
