"""GhostClock C1 -- ENF extractor.

Pipeline (per file):
  decode (soundfile; ffmpeg fallback) -> mono float
  -> polyphase resample to ~1 kHz (scipy.signal.resample_poly = Kaiser-windowed FIR anti-aliasing)
     (reference files are already 400 Hz and are kept at 400 Hz)
  -> zero-phase Butterworth band-pass covering the nominal harmonics in use
  -> STFT (Hann, win_s seconds, hop 1 s, zero-padded so the bin spacing is 1/64 Hz on every sample rate)
  -> per harmonic k: band k*(50 +- hb) Hz
       * coarse: SNR-weighted *spectral combination* of all harmonic bands mapped onto a common
         fundamental-equivalent grid -> robust coarse ENF estimate per frame
       * fine: in each harmonic band, re-pick the peak within +-2 bins of k*coarse, quadratic
         (parabolic on log-power) interpolation, divide by k
       * combine fine estimates with weights = per-frame linear SNR (peak / band median),
         dropping harmonics whose SNR < snr_min (fallback: coarse estimate)
  -> f(t) [Hz, fundamental-equivalent], q(t) = combined-spectrum peak/median ratio in dB

Frame i is centred at t = i*hop + win_s/2 seconds from the file start, for every file type, so a
lag of n frames == n seconds.
"""
from __future__ import annotations
import os, glob, shutil, subprocess
from fractions import Fraction
import numpy as np
import soundfile as sf
from scipy import signal, fft as sfft

NOMINAL = 50.0
DF = 1.0 / 64.0  # FFT bin spacing (Hz) after zero padding, identical for every sample rate


def _ffmpeg():
    p = shutil.which('ffmpeg')
    if p:
        return p
    hits = glob.glob(os.path.expandvars(r'%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*\*\bin\ffmpeg.exe'))
    return hits[0] if hits else None


def load_audio(path: str):
    """Return (mono float64 signal, fs). WAV/FLAC via soundfile; anything else via ffmpeg to 8 kHz mono."""
    try:
        x, fs = sf.read(path, dtype='float64', always_2d=True)
        return x.mean(axis=1), int(fs)
    except Exception:
        ff = _ffmpeg()
        if ff is None:
            raise
        raw = subprocess.run([ff, '-v', 'error', '-i', path, '-ac', '1', '-ar', '8000', '-f', 's16le', '-'],
                             capture_output=True, check=True).stdout
        return np.frombuffer(raw, dtype='<i2').astype(np.float64) / 32768.0, 8000


def to_rate(x, fs, target):
    if fs == target:
        return x, fs
    fr = Fraction(target, fs).limit_denominator(1000)
    return signal.resample_poly(x, fr.numerator, fr.denominator), fs * fr.numerator // fr.denominator


def _parabolic(ym1, y0, yp1):
    den = ym1 - 2 * y0 + yp1
    with np.errstate(divide='ignore', invalid='ignore'):
        d = np.where(np.abs(den) > 1e-12, 0.5 * (ym1 - yp1) / den, 0.0)
    return np.clip(d, -0.5, 0.5)


def extract_enf(x, fs, harmonics=(1, 2, 3, 4, 5, 6, 7), win_s=16.0, hop_s=1.0, hb=0.5,
                snr_min=2.0, target_fs=1000, chunk=256):
    """Return dict(t, f, q, fk, snrk, harmonics, params)."""
    x, fs = to_rate(np.asarray(x, float), fs, target_fs if fs > target_fs else fs)
    nyq = fs / 2
    harmonics = tuple(k for k in harmonics if k * (NOMINAL + hb) + 2 < nyq)
    lo, hi = NOMINAL - 5, min(max(harmonics) * NOMINAL + 10, nyq * 0.95)
    sos = signal.butter(4, [lo, hi], btype='bandpass', fs=fs, output='sos')
    x = signal.sosfiltfilt(sos, x)
    win = int(round(win_s * fs)); hop = int(round(hop_s * fs)); nfft = int(round(fs / DF))
    nfr = (len(x) - win) // hop + 1
    if nfr < 1:
        raise ValueError('signal shorter than one window')
    w = signal.windows.hann(win, sym=False)
    # bin ranges per harmonic
    bands = []
    for k in harmonics:
        b0 = int(np.floor(k * (NOMINAL - hb) / DF)); b1 = int(np.ceil(k * (NOMINAL + hb) / DF))
        bands.append((k, b0, b1))
    bmax = max(b1 for _, _, b1 in bands) + 3
    # common fundamental-equivalent grid for spectral combination
    grid = np.arange(NOMINAL - hb, NOMINAL + hb + 1e-9, DF / 4)
    K = len(harmonics)
    f_out = np.empty(nfr); q_out = np.empty(nfr)
    fk = np.full((nfr, K), np.nan); snrk = np.zeros((nfr, K))
    frames = np.lib.stride_tricks.sliding_window_view(x, win)[::hop][:nfr]
    for s in range(0, nfr, chunk):
        F = frames[s:s + chunk] * w
        P = np.abs(sfft.rfft(F, n=nfft, axis=1)[:, :bmax]) ** 2 + 1e-30
        n = P.shape[0]
        comb = np.zeros((n, grid.size))
        snr_frame = np.zeros((n, K))
        for j, (k, b0, b1) in enumerate(bands):
            band = P[:, b0:b1 + 1]
            med = np.median(band, axis=1)
            snr_frame[:, j] = band.max(axis=1) / med
            # map band onto the common grid (linear interpolation in bin index)
            pos = grid * k / DF - b0
            i0 = np.clip(np.floor(pos).astype(int), 0, band.shape[1] - 2); fr = pos - np.floor(pos)
            g = band[:, i0] * (1 - fr) + band[:, i0 + 1] * fr
            comb += (g / med[:, None]) * snr_frame[:, j:j + 1]
        cm = comb.argmax(axis=1)
        cmc = np.clip(cm, 1, grid.size - 2)
        rr = np.arange(n)
        lc = np.log(comb)
        coarse = grid[cmc] + _parabolic(lc[rr, cmc - 1], lc[rr, cmc], lc[rr, cmc + 1]) * (DF / 4)
        q_out[s:s + n] = 10 * np.log10(comb.max(axis=1) / np.median(comb, axis=1))
        # fine per-harmonic estimates near k*coarse
        num = np.zeros(n); den = np.zeros(n); lp = np.log(P)
        for j, (k, b0, b1) in enumerate(bands):
            c = np.round(coarse * k / DF).astype(int)
            idx = c[:, None] + np.arange(-2, 3)[None, :]
            loc = P[rr[:, None], idx]
            m = loc.argmax(axis=1)
            pk = c + m - 2
            d = _parabolic(lp[rr, pk - 1], lp[rr, pk], lp[rr, pk + 1])
            est = (pk + d) * DF / k
            snr = snr_frame[:, j]
            fk[s:s + n, j] = est; snrk[s:s + n, j] = snr
            use = (snr >= snr_min) & (np.abs(est - coarse) < 2 * DF)
            num += np.where(use, snr * est, 0); den += np.where(use, snr, 0)
        f_out[s:s + n] = np.where(den > 0, num / np.maximum(den, 1e-30), coarse)
    t = np.arange(nfr) * hop_s + win_s / 2
    return dict(t=t, f=f_out, q=q_out, fk=fk, snrk=snrk, harmonics=np.array(harmonics),
                params=dict(win_s=win_s, hop_s=hop_s, hb=hb, snr_min=snr_min, fs=fs))


def spectrogram_band(x, fs, f_lo, f_hi, win_s=16.0, hop_s=1.0, target_fs=1000):
    """Power spectrogram restricted to [f_lo, f_hi] (for plots)."""
    x, fs = to_rate(np.asarray(x, float), fs, target_fs if fs > target_fs else fs)
    win = int(win_s * fs); hop = int(hop_s * fs); nfft = int(round(fs / DF))
    frames = np.lib.stride_tricks.sliding_window_view(x, win)[::hop]
    b0, b1 = int(f_lo / DF), int(f_hi / DF) + 1
    out = []
    for s in range(0, len(frames), 256):
        F = (frames[s:s + 256] - frames[s:s + 256].mean(axis=1, keepdims=True)) * signal.windows.hann(win, sym=False)
        out.append(np.abs(sfft.rfft(F, n=nfft, axis=1)[:, b0:b1]) ** 2)
    S = np.concatenate(out)
    return np.arange(len(S)) * hop_s + win_s / 2, np.arange(b0, b1) * DF, S
