"""GhostClock C1 -- quality-weighted, mean-removed normalised cross-correlation (NCC) matcher.

NCC(tau) = weighted Pearson correlation between excerpt x (length L, weights w) and the reference
segment y[tau : tau+L], for every tau in the full reference, computed with FFTs:
   A = sum w*xc*y_tau ,  B = sum w*y_tau ,  C = sum w*y_tau^2
   NCC = A / ( sqrt(sum w*xc^2) * sqrt(C - B^2/sum w) )
Reference-side windows containing invalid reference frames get NCC = -inf.
"""
import numpy as np
from scipy import fft as sfft


def moving_average(v, n):
    if n <= 1:
        return np.zeros_like(v)
    k = np.ones(n) / n
    pad = n // 2
    vp = np.pad(v, (pad, n - 1 - pad), mode='edge')
    return np.convolve(vp, k, mode='valid')


def preprocess(f, q, hp_s=0, clip_hz=0.1, q_thr=None, wmode='q', q_ref=None, medfilt=0):
    """Return (signal, weights). hp_s>0 removes a centred moving average of hp_s frames (high-pass).
    Frames with |f - median| > clip_hz get weight 0. Weight mode:
      'none' -> 1, 'gate' -> 1 if q>=q_thr, 'q' -> linear SNR weight 10^(q/20) normalised, gated by q_thr."""
    f = np.asarray(f, float).copy()
    if medfilt and medfilt > 1:
        from scipy.signal import medfilt as _mf
        f = _mf(f, int(medfilt) | 1)
    med = np.nanmedian(f)
    bad = ~np.isfinite(f) | (np.abs(f - med) > clip_hz)
    f[bad] = med
    w = np.ones_like(f)
    if wmode == 'q':
        w = 10 ** (np.asarray(q, float) / 20.0); w = w / np.median(w)
        w = np.minimum(w, 4.0)
    if q_thr is not None and wmode != 'none':
        w = np.where(np.asarray(q) >= q_thr, w, 0.0)
    w[bad] = 0.0
    if hp_s and hp_s > 1:
        f = f - moving_average(f, int(hp_s))
    else:
        f = f - med
    return f, w


class Reference:
    """Pre-FFT'd reference trace for fast repeated matching."""

    def __init__(self, y, valid=None, nfft=None):
        y = np.asarray(y, float)
        self.N = len(y)
        self.valid = np.ones(self.N, bool) if valid is None else np.asarray(valid, bool)
        y = np.where(self.valid, y, 0.0)
        y = y - y[self.valid].mean()
        self.y = y
        self.nfft = nfft or sfft.next_fast_len(self.N + 4096)
        self.Y = sfft.rfft(y, self.nfft)
        self.Y2 = sfft.rfft(y * y, self.nfft)
        self.Vinv = sfft.rfft((~self.valid).astype(float), self.nfft)

    def _corr(self, Fy, k):
        L = len(k)
        r = sfft.irfft(Fy * np.conj(sfft.rfft(k, self.nfft)), self.nfft)
        return r[: self.N - L + 1]

    def ncc(self, x, w):
        L = len(x)
        if L > self.N:
            raise ValueError('excerpt longer than reference')
        sw = w.sum()
        xm = (w * x).sum() / sw
        xc = (x - xm) * (w > 0)
        sx = np.sqrt((w * xc * xc).sum())
        A = self._corr(self.Y, w * xc)
        B = self._corr(self.Y, w)
        C = self._corr(self.Y2, w)
        if not hasattr(self, '_bad'): self._bad = {}
        if L not in self._bad: self._bad[L] = self._corr(self.Vinv, np.ones(L)) > 0.5
        bad = self._bad[L]
        var = C - B * B / sw
        with np.errstate(invalid='ignore', divide='ignore'):
            r = A / (sx * np.sqrt(np.maximum(var, 1e-18)))
        r[bad | (var <= 1e-15)] = -np.inf
        return r


def peak_stats(r, excl=60):
    """top-1 lag (sub-frame, parabolic), peak, second peak outside +-excl frames, margin, z-score."""
    k = int(np.argmax(r)); pk = float(r[k])
    lag = float(k)
    if 0 < k < len(r) - 1 and np.isfinite(r[k - 1]) and np.isfinite(r[k + 1]):
        den = r[k - 1] - 2 * r[k] + r[k + 1]
        if abs(den) > 1e-12:
            lag += float(np.clip(0.5 * (r[k - 1] - r[k + 1]) / den, -0.5, 0.5))
    rr = r.copy(); rr[max(0, k - excl): k + excl + 1] = -np.inf
    second = float(np.max(rr)) if np.isfinite(rr).any() else -1.0
    fin = r[np.isfinite(r)]
    z = float((pk - fin.mean()) / (fin.std() + 1e-12))
    return dict(lag=lag, peak=pk, second=second, margin=pk - second, z=z)
