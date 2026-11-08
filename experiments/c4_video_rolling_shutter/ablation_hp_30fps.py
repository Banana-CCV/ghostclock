import sys, numpy as np
sys.path.insert(0, r'<WORKSPACE>\work\C4')
import rs_enf, synth_eval
from scipy.ndimage import uniform_filter1d
name = sys.argv[1]; Tro = float(sys.argv[2])
mp4 = rf'<WORKSPACE>\work\C4\synth\SYNTH_{name}.mp4'
cache = rf'<WORKSPACE>\datasets\raw\video_c4\cache\SYNTH_{name}_cells.npz'
import os
if not os.path.exists(cache):
    cells, pts, clipf, meta, kept = rs_enf.decode_cells(mp4, verbose=False)
    np.savez(cache, cells=cells, pts=pts, clipf=clipf, meta=np.array(meta), kept=np.zeros(0))
d = np.load(cache, allow_pickle=True); cells, pts, clipf, meta = d['cells'], d['pts'], d['clipf'], d['meta'].item()
tr = np.loadtxt(mp4.replace('.mp4', '_truth.csv'), delimiter=',', skiprows=1)
t, fps, _ = rs_enf.regular_frame_times(pts)
mask = rs_enf.static_mask(cells, clipf)
def ev(tc, fe, lab):
    ft = synth_eval.truth_windowed(tr[:, 0], tr[:, 1], tc, 16.0)
    m = synth_eval.metrics(fe, ft); print(f'{lab:40s} r={m["corr"]:.3f} rmse={m["rmse_mHz"]:.2f} bias={m["bias_mHz"]:.2f}')
for mw in [60.0, 1e9]:
    s, naive, rows, motion = rs_enf.row_signals(cells, mask, fps, mw)
    for hp in [True, False]:
        z = rs_enf.heterodyne(s, t, Tro, meta['H'], 4, 100.0, rows)
        if hp:
            z = z - uniform_filter1d(z.real, int(60 * fps), mode='nearest') - 1j * uniform_filter1d(z.imag, int(60 * fps), mode='nearest')
        tc, fb, q = rs_enf.track(z, fps, -0.5, 0.5, 16.0, 1.0)
        ev(tc, (100 + fb) / 2, f'cellmean={mw} zHP={hp}')
    tn, fn, qn, _ = rs_enf.naive_enf_trace(naive, fps)
    ev(tn, fn, f'naive cellmean={mw}')
# mean instead of median across columns
rel = cells / np.maximum(uniform_filter1d(cells, int(60*fps), axis=0, mode='nearest'), 1) - 1
s2 = np.where(mask[None], rel, 0).sum(2) / np.maximum(mask.sum(1), 1)
z = rs_enf.heterodyne(s2, t, Tro, meta['H'], 4, 100.0, mask.sum(1) >= 3)
tc, fb, q = rs_enf.track(z, fps, -0.5, 0.5, 16.0, 1.0); ev(tc, (100 + fb) / 2, 'column MEAN, no zHP')
