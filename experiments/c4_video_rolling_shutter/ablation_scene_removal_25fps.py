import sys, os, numpy as np
sys.path.insert(0, r'<WORKSPACE>\work\C4')
import rs_enf, synth_eval
from scipy.ndimage import uniform_filter1d
name = sys.argv[1]; Tro = float(sys.argv[2])
mp4 = rf'<WORKSPACE>\work\C4\synth\SYNTH_{name}.mp4'
cache = rf'<WORKSPACE>\datasets\raw\video_c4\cache\SYNTH_{name}_cells.npz'
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
for mw in [60.0, 120.0, 1e9]:
    s, naive, rows, motion = rs_enf.row_signals(cells, mask, fps, mw)
    for hp in [60, 120, 'all', None]:
        z = rs_enf.heterodyne(s, t, Tro, meta['H'], 4, 100.0, rows)
        if hp == 'all': z = z - z.mean()
        elif hp:
            z = z - uniform_filter1d(z.real, int(hp * fps), mode='nearest') - 1j * uniform_filter1d(z.imag, int(hp * fps), mode='nearest')
        tc, fb, q = rs_enf.track(z, fps, -0.5, 0.5, 16.0, 1.0)
        ev(tc, (100 + fb) / 2, f'cellmean={mw} zHP={hp}')
