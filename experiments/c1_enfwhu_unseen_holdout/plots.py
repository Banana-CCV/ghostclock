"""Figures for C1 (reads frozen.json + holdout trials). usage: python plots.py"""
import sys, os, json
import numpy as np, pandas as pd
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
import enf, match
from analyze import add_err

P = os.path.join(HERE, 'plots'); os.makedirs(P, exist_ok=True)
fz = json.load(open(os.path.join(HERE, 'frozen.json')))
prm = fz['params']; stat = fz['stat']; th = {int(k): v for k, v in fz['thresholds'].items()}
days, d_of = day_groups()
ho = add_err(pd.read_parquet(os.path.join(HERE, 'trials', f"{fz['tag']}_holdout.parquet")), fz['dcal'])
L0 = 300
g = ho[(ho.L == L0)]
h1 = g[g.kind == 'h1_true']
succ = h1[(h1[stat] > th[L0]) & (h1.err.abs() <= 1)].sort_values(stat, ascending=False)
fail = h1[~((h1[stat] > th[L0]) & (h1.err.abs() <= 5))].sort_values(stat)
h0 = g[g.kind == 'h0'].sort_values(stat, ascending=False)
gtj = json.load(open(os.path.join(HERE, 'gt_w16.json')))
succ = succ[succ.fid.map(lambda f: gtj[f]['rec_ref_r_at_d'] >= 0.98)]
s_row = succ.iloc[len(succ) // 2]  # a typical (median-score) success on a clean recording
fail = fail[np.isfinite(fail.lag) & (fail.peak > -1)]
print('success example', s_row.fid, s_row.start, s_row[stat], s_row.err)


def prep(tr):
    return match.preprocess(tr['f'], tr['q'], hp_s=prm['hp'], wmode=prm['wmode'], q_thr=prm['qthr'], clip_hz=prm['clip'], medfilt=prm.get('medfilt', 0))


def ref_obj(day):
    tr = load_trace(prm['cfg'], 'H1_ref_one_day', day + '_ref')
    y, _ = match.preprocess(tr['f'], tr['q'], hp_s=prm['hp'], wmode='none', clip_hz=0.5)
    return tr, match.Reference(y, ref_valid(tr))

# 1. spectrogram + ridge (success recording; fundamental band and the strongest harmonic band)
win = 16.0 if prm['cfg'] == 'w16' else 8.0
def spec(rid, fname, note=''):
  tr = load_trace(prm['cfg'], 'H1', rid)
  x, fs = enf.load_audio(os.path.join(DATA, 'H1', rid + '.wav'))
  kbest = int(tr['harmonics'][np.argmax(np.median(tr['snrk'], axis=0))])
  fig, ax = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
  for a_, k in zip(ax, (1, kbest)):
    t, f, S = enf.spectrogram_band(x, fs, k * 49.6, k * 50.4, win_s=win)
    a_.pcolormesh(t, f / k, 10 * np.log10(S.T + 1e-20), shading='auto', cmap='magma')
    a_.plot(tr['t'], tr['f'], color='cyan', lw=0.8, label='tracked ENF (all harmonics combined)')
    a_.set_ylabel(f'f / {k}  (Hz)'); a_.set_title(f'H1/{rid}.wav  harmonic k={k} ({k*50} Hz band), shown as fundamental-equivalent {note}')
    a_.set_ylim(49.6, 50.4); a_.legend(loc='upper right', fontsize=8)
  ax[-1].set_xlabel('time in recording (s, window centre)')
  fig.tight_layout(); fig.savefig(os.path.join(P, fname), dpi=120); plt.close(fig)
rid = s_row.fid
spec(rid, 'spectrogram_ridge.png')
spec('057', 'spectrogram_interference_057.png', '(tracker jumps to a steady 250.8 Hz tone)')
tr = load_trace(prm['cfg'], 'H1', rid)

# 2. overlay: extracted excerpt vs reference at matched offset
rtr, R = ref_obj(d_of[rid])
s = int(s_row.start); L = int(s_row.L)
lag = int(round(s_row.lag)); gtv = s_row['gt']
fig, ax = plt.subplots(figsize=(11, 4))
tt = np.arange(L)
ax.plot(tt, rtr['f'][int(round(gtv)):int(round(gtv)) + L], color='k', lw=1.2, label='one-day reference ENF at ground-truth offset')
_, wfull = prep(tr); ww = wfull[s:s + L]
fx = tr['f'][s:s + L].copy(); fu = np.where(ww > 0, fx, np.nan)
ax.plot(tt, fx, color='0.7', lw=0.8, ls=':', label='extracted, frames given weight 0 by matcher')
ax.plot(tt, fu, color='tab:orange', lw=1.2, label=f'extracted from audio, frames used (H1/{rid}, {L} s excerpt, {int((ww>0).sum())}/{L})')
ax.set_xlabel('seconds into excerpt'); ax.set_ylabel('Hz')
ax.set_title(f'Overlay: matched offset {s_row.lag:.1f} s, ground truth {gtv:.1f} s, error {s_row.err:+.2f} s, NCC {s_row.peak:.3f}')
ax.legend(fontsize=8); fig.tight_layout(); fig.savefig(os.path.join(P, 'overlay_success.png'), dpi=120); plt.close(fig)


def landscape(row, fname, title):
    kind = row.kind
    grp = 'H1' if kind != 'h0' else 'H0'
    t_ = load_trace(prm['cfg'], grp, row.fid)
    xx, ww = prep(t_)
    _, RR = ref_obj(row.ref_day)
    s, L = int(row.start), int(row.L)
    r = RR.ncc(xx[s:s + L], ww[s:s + L])
    fig, (ax, az) = plt.subplots(1, 2, figsize=(14, 4.2), gridspec_kw=dict(width_ratios=[2.2, 1]))
    rf = np.where(np.isfinite(r), r, np.nan); B = 60; nb = len(rf) // B
    env = np.nanmax(rf[:nb * B].reshape(nb, B), axis=1)
    ax.plot(np.arange(nb) * B / 3600, env, lw=0.6, color='tab:blue', label='NCC (upper envelope, max per 60 s)')
    c = int(row.lag) if np.isfinite(row.lag) else int(np.nanargmax(rf)); lo, hi = max(0, c - 900), min(len(rf), c + 900)
    az.plot((np.arange(lo, hi) - c), rf[lo:hi], lw=0.8, color='tab:blue')
    az.axhline(th[L], color='r', ls='--'); az.set_xlabel('offset relative to top-1 (s)'); az.set_title('zoom +-15 min around top-1', fontsize=9)
    if kind == 'h1_true': az.axvline(row['gt'] - c, color='g', ls=':')
    if stat == 'peak':
        ax.axhline(th[L], color='r', ls='--', label=f'dev null threshold (FMR<=5%) = {th[L]:.3f}')
    else:
        ax.axhline(row.second + th[L] if stat == 'margin' else np.nan, color='r', ls='--',
                   label=f'second peak + dev margin threshold {th[L]:.3f}')
    if kind == 'h1_true':
        ax.axvline(row['gt'] / 3600, color='g', ls=':', label='ground truth')
    ax.plot(row.lag / 3600, row.peak, 'r^', label=f'top-1 (peak {row.peak:.3f}, margin {row.margin:.3f})')
    ax.set_xlabel('candidate offset in one-day reference (h)'); ax.set_ylabel('weighted NCC')
    ax.set_title(title, fontsize=10); ax.legend(fontsize=7, loc='lower right'); fig.tight_layout()
    fig.savefig(os.path.join(P, fname), dpi=120); plt.close(fig)

landscape(s_row, 'landscape_success.png', f'Success: H1/{s_row.fid} {L0}s excerpt vs own day ref {s_row.ref_day} (err {s_row.err:+.2f} s)')
if len(fail):
    fr = fail.sort_values('peak', ascending=False).iloc[0]
    landscape(fr, 'landscape_failure.png', f'Failure (abstained, peak below threshold): H1/{fr.fid} {L0}s excerpt vs own day ref {fr.ref_day} (top-1 err {fr.err:+.0f} s, {stat} {fr[stat]:.3f})')
hr = h0.iloc[0]
landscape(hr, 'landscape_h0.png', f'H0 (no ENF): {hr.fid} {L0}s excerpt vs day ref {hr.ref_day} (highest-scoring H0 trial)')

# 4. accuracy vs excerpt length (holdout)
res = json.load(open(os.path.join(HERE, 'RESULTS.json')))['holdout']['all_excerpts']
Ls = sorted(int(k) for k in res)
fig, ax = plt.subplots(figsize=(7, 4.5))
for key, lab, c in (('coverage', 'coverage (match issued)', 'tab:blue'), ('acc1_among_issued', 'acc +-1 s among issued', 'tab:green'),
                    ('acc5_among_issued', 'acc +-5 s among issued', 'tab:olive'), ('null_fmr', 'false-match rate (wrong-ref + H0)', 'tab:red')):
    y = [res[str(L)][key] for L in Ls]
    cik = {'coverage': 'coverage_ci', 'acc1_among_issued': 'acc1_ci', 'acc5_among_issued': 'acc5_ci', 'null_fmr': 'null_fmr_ci'}[key]
    lo = [y[i] - (res[str(L)][cik][0] or 0) for i, L in enumerate(Ls)]; hi = [(res[str(L)][cik][1] or 0) - y[i] for i, L in enumerate(Ls)]
    ax.errorbar(np.array(Ls) / 60, y, yerr=[lo, hi], marker='o', capsize=3, label=lab, color=c)
ax.set_xlabel('excerpt length (min)'); ax.set_ylabel('rate (Wilson 95% CI)'); ax.set_ylim(-0.02, 1.02)
ax.set_title('HOLDOUT: ENF-WHU H1 timestamp matching vs excerpt length'); ax.legend(fontsize=8); ax.grid(alpha=.3)
fig.tight_layout(); fig.savefig(os.path.join(P, 'accuracy_vs_length.png'), dpi=120); plt.close(fig)
print('plots written to', P)
