"""Director's independent check of W06's smoke claim (r=0.976, RMSE 5.48 mHz on ENF-WHU H1/003).
Reference ENF is computed here with my own simple STFT + parabolic interpolation on 003_ref.wav,
not with W06 code. Then W06's saved trace is compared at matching window centres."""
import numpy as np, soundfile as sf
from scipy.signal import stft

# needs the ENF-WHU dataset and W06 smoke trace (not committed): set GHOSTCLOCK_WORKSPACE to the original workspace
import os
ROOT = os.environ.get("GHOSTCLOCK_WORKSPACE", ".")
ref, fs = sf.read(ROOT + r"\datasets\raw\enf-whu\repo\ENF-WHU-Dataset\H1_ref\003_ref.wav")
if ref.ndim > 1:
    ref = ref[:, 0]
win_s, hop_s = 16.0, 1.0
nper, nhop = int(win_s * fs), int(hop_s * fs)
f, t, Z = stft(ref, fs=fs, window="hann", nperseg=nper, noverlap=nper - nhop, nfft=nper * 16, boundary=None, padded=False)
P = np.abs(Z) ** 2
band = (f > 49.5) & (f < 50.5)
fb, Pb = f[band], P[band]
k = Pb.argmax(0)
k = np.clip(k, 1, len(fb) - 2)
a, b, c = [np.log(Pb[k + d, np.arange(Pb.shape[1])] + 1e-30) for d in (-1, 0, 1)]
delta = 0.5 * (a - c) / (a - 2 * b + c)
fref = fb[k] + delta * (fb[1] - fb[0])
tref = t  # window centres (s)

w = np.load(ROOT + r"\work\W06\smoke_traces\003.trace.npz")
tw, fw = w["t"], w["f"]
fr_i = np.interp(tw, tref, fref, left=np.nan, right=np.nan)
m = np.isfinite(fr_i) & np.isfinite(fw)
x, y = fw[m] - fw[m].mean(), fr_i[m] - fr_i[m].mean()
r = float(np.corrcoef(x, y)[0, 1])
rmse_mhz = float(np.sqrt(np.mean((fw[m] - fr_i[m]) ** 2)) * 1000)
rmse_demeaned_mhz = float(np.sqrt(np.mean((x - y) ** 2)) * 1000)
# lag check: is best alignment at zero lag?
lags = range(-5, 6)
rl = {L: float(np.corrcoef(np.roll(x, L)[10:-10], y[10:-10])[0, 1]) for L in lags}
print(f"ref fs={fs} dur={len(ref)/fs:.1f}s windows={len(fref)} matched={m.sum()}")
print(f"independent r={r:.4f} rmse={rmse_mhz:.2f} mHz demeaned_rmse={rmse_demeaned_mhz:.2f} mHz")
print("corr by lag (s):", {k_: round(v, 4) for k_, v in rl.items()})
print(f"ref ENF range {fref.min():.3f}-{fref.max():.3f} Hz; W06 range {np.nanmin(fw):.3f}-{np.nanmax(fw):.3f}")
