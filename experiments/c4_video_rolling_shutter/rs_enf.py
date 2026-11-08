"""rs_enf.py -- ENF from mains-lamp flicker in video via the rolling shutter (GhostClock / C4).

Pipeline (see METHOD.md for the physics and citations):
  1. decode frames -> luminance (Y plane), reduce each frame to a grid of "cells"
     (row_bin rows x 1/n_col of the width).  Keeps per-row resolution, ~100x less data.
  2. static mask: drop cells that are clipped / dark (tv-range Y) ; motion is handled
     robustly per frame by a median across column blocks.
  3. scene removal: divide every cell by its long-window temporal mean (relative
     modulation), i.e. subtract the temporal mean image in log/relative terms.
  4. row signal s[k, r]: robust median over good column blocks of the relative residual.
  5. row-time model: row r of frame k is sampled at  t_k + r * T_ro / H  (T_ro = row
     read-out time of the whole frame, idle = 1/fps - T_ro).  Heterodyne every row
     sample by exp(-j 2 pi f0 t) with f0 = 2 * f_grid, sum over rows -> one complex
     baseband sample z_k per frame.  (Equivalent to "periodic zero-out" concatenation of
     Choi/Wong/Su/Wu: the idle period is a gap of zeros at the true times.)
  6. T_ro estimated by search: maximise the spectral peak sharpness of z near 0 Hz.
  7. track the baseband peak (STFT, zero-padded, quadratic interpolation) ->
     f_light = f0 + f_bb ; ENF = f_light / 2 ; q = peak-to-floor ratio (dB).
  Baseline: naive per-frame mean brightness of the same static region, tracked at the
  temporal alias of f0 (|f0 - n*fps|; degenerate = 0 Hz at 25 fps / 50 Hz grid).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.io import wavfile

# ----------------------------------------------------------------------------- decode


def decode_cells(path, row_bin=4, n_col=16, max_frames=None, keep=None, clip_hi=235, clip_lo=18,
                 clip_every=150, verbose=True):
    """Decode video -> cells[K, R, C] (float32 mean luminance), pts[K] (s), meta.

    keep=(start, count): also return full-resolution Y frames for that range (for plots).
    Clip statistics (fraction of pixels >= clip_hi or <= clip_lo per cell) are sampled every
    `clip_every` frames.
    """
    import av
    cont = av.open(path)
    st = cont.streams.video[0]
    st.thread_type = "AUTO"
    H, W = st.codec_context.height, st.codec_context.width
    R, C = H // row_bin, n_col
    cw = W // n_col
    cells, pts, kept = [], [], []
    clipf = np.zeros((R, C)); nclip = 0
    t0 = time.time()
    for k, fr in enumerate(cont.decode(st)):
        if max_frames and k >= max_frames:
            break
        p = fr.planes[0]
        y = np.frombuffer(p, np.uint8).reshape(-1, p.line_size)[:H, :W]
        yc = y[:R * row_bin, :C * cw].reshape(R, row_bin, C, cw)
        cells.append(yc.mean(axis=(1, 3), dtype=np.float32))
        pts.append(float(fr.time) if fr.time is not None else np.nan)
        if k % clip_every == 0:
            clipf += ((yc >= clip_hi) | (yc <= clip_lo)).mean(axis=(1, 3)); nclip += 1
        if keep and keep[0] <= k < keep[0] + keep[1]:
            kept.append(y.copy())
        if verbose and k % 2000 == 0:
            print(f"  decoded {k} frames ({time.time()-t0:.0f}s)", flush=True)
    cont.close()
    meta = dict(H=H, W=W, row_bin=row_bin, n_col=n_col, n_frames=len(cells))
    return (np.stack(cells), np.array(pts), clipf / max(nclip, 1), meta,
            (np.stack(kept) if kept else None))


def regular_frame_times(pts):
    """Robust linear fit t_k = a + b k to PTS (PTS are often ms-quantised). Returns times
    (relative to first frame), fps estimate and residual stats."""
    k = np.arange(len(pts))
    ok = np.isfinite(pts)
    b, a = np.polyfit(k[ok], pts[ok], 1)
    for _ in range(3):  # re-fit without outliers
        res = pts - (a + b * k)
        ok = np.isfinite(pts) & (np.abs(res) < max(3 * np.nanstd(res), 1e-3))
        b, a = np.polyfit(k[ok], pts[ok], 1)
    res = pts - (a + b * k)
    d = np.diff(pts)
    info = dict(fps_fit=1 / b, pts_resid_ms_rms=float(np.nanstd(res) * 1e3),
                pts_resid_ms_maxabs=float(np.nanmax(np.abs(res)) * 1e3),
                dt_ms_mean=float(np.nanmean(d) * 1e3), dt_ms_std=float(np.nanstd(d) * 1e3),
                dt_ms_min=float(np.nanmin(d) * 1e3), dt_ms_max=float(np.nanmax(d) * 1e3))
    return b * k, 1 / b, info

# ----------------------------------------------------------------------------- signals


def static_mask(cells, clipf, lo=30, hi=225, max_clip=0.02):
    m = cells.mean(axis=0)
    return (m > lo) & (m < hi) & (clipf < max_clip)


def row_signals(cells, mask, fps, mean_win_s=60.0, min_cols=3):
    """Relative residual per cell, robust row signal s[K,R] and naive frame mean m[K]."""
    K = cells.shape[0]
    w = int(round(mean_win_s * fps))
    if w >= K:
        mu = cells.mean(axis=0, keepdims=True)
    else:
        mu = uniform_filter1d(cells, size=w, axis=0, mode="nearest")
    rel = cells / np.maximum(mu, 1.0) - 1.0
    relm = np.where(mask[None], rel, np.nan)
    s = np.empty((K, cells.shape[1]), np.float32)
    for i in range(0, K, 2000):
        s[i:i + 2000] = np.nanmedian(relm[i:i + 2000], axis=2)
    good_rows = mask.sum(axis=1) >= min_cols
    s[:, ~good_rows] = 0.0
    s = np.nan_to_num(s)
    # naive baseline: plain mean brightness of the static region per frame (relative)
    tot = (cells * mask[None]).sum(axis=(1, 2))
    mtot = uniform_filter1d(tot, size=min(w, K), mode="nearest") if w < K else tot.mean()
    naive = tot / mtot - 1.0
    # per-frame motion score: median absolute deviation across columns (diagnostic)
    motion = np.nanmedian(np.abs(relm - s[:, :, None]), axis=(1, 2))
    return s, naive, good_rows, motion


def heterodyne(s, t_frames, T_ro, H, row_bin, f0=100.0, rows=None):
    """z_k = mean_r s[k,r] * exp(-j 2 pi f0 (t_k + y_r T_ro / H)), y_r = centre row."""
    R = s.shape[1]
    y = (np.arange(R) * row_bin + (row_bin - 1) / 2.0)
    wr = np.ones(R) if rows is None else rows.astype(float)
    ph_r = np.exp(-2j * np.pi * f0 * y * T_ro / H) * wr
    zk = (s @ ph_r) / max(wr.sum(), 1)
    return zk * np.exp(-2j * np.pi * f0 * t_frames)


def peak_sharpness(z, fs, band=0.5, win_s=16.0, hop_s=4.0, exclude_dc=0.0):
    """Mean over STFT windows of (peak power in |f|<band) / (median power in |f|<fs/2)."""
    n = int(win_s * fs); hop = int(hop_s * fs)
    nfft = 1 << int(np.ceil(np.log2(n * 8)))
    f = np.fft.fftfreq(nfft, 1 / fs)
    sel = (np.abs(f) < band) & (np.abs(f) >= exclude_dc)
    win = np.hanning(n)
    vals = []
    for i in range(0, len(z) - n + 1, hop):
        seg = z[i:i + n] - z[i:i + n].mean() * (exclude_dc > 0)
        P = np.abs(np.fft.fft(seg * win, nfft)) ** 2
        vals.append(P[sel].max() / (np.median(P) + 1e-30))
    return float(np.mean(vals)) if vals else 0.0


def estimate_Tro(s, t_frames, fps, H, row_bin, f0=100.0, rows=None, grid=None, n_use=None,
                 exclude_dc=0.0, allow_negative=False):
    """Grid search of T_ro.  Default prior: top-to-bottom read-out (T_ro > 0).  With
    allow_negative the bottom-up direction is also searched -- but at degenerate frame rates
    (fps divides f0) +T_ro and -T_ro score identically and the ENF sign flips (see FAILURES.md)."""
    if grid is None:
        lo = -1 / fps if allow_negative else 0.5e-3
        grid = np.arange(lo, 1 / fps + 1e-9, 0.25e-3)
    n_use = n_use or len(t_frames)
    sc = np.array([peak_sharpness(heterodyne(s[:n_use], t_frames[:n_use], T, H, row_bin, f0, rows),
                                  fps, exclude_dc=exclude_dc) for T in grid])
    return float(grid[np.argmax(sc)]), grid, sc


def track(x, fs, f_lo, f_hi, win_s=16.0, hop_s=1.0, complex_in=True, remove_mean=False):
    """STFT peak tracking within [f_lo, f_hi] (Hz in the signal's own frequency axis).
    Returns window centre times (s, from first sample), peak freq, q (dB peak/median)."""
    n = int(round(win_s * fs)); hop = int(round(hop_s * fs))
    nfft = 1 << int(np.ceil(np.log2(max(n * 4, fs / 0.002))))  # <=2 mHz bins + quad. interp
    f = np.fft.fftfreq(nfft, 1 / fs)
    sel = np.where((f >= f_lo) & (f <= f_hi))[0]
    sel = sel[np.argsort(f[sel])]
    win = np.hanning(n)
    tc, fp, q = [], [], []
    for i in range(0, len(x) - n + 1, hop):
        seg = x[i:i + n]
        if remove_mean:
            seg = seg - seg.mean()
        P = np.abs(np.fft.fft(seg * win, nfft)) ** 2
        Ps = P[sel]; j = int(np.argmax(Ps))
        if 0 < j < len(Ps) - 1:
            a, b, c = np.log(Ps[j - 1] + 1e-30), np.log(Ps[j] + 1e-30), np.log(Ps[j + 1] + 1e-30)
            d = 0.5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) != 0 else 0.0
        else:
            d = 0.0
        df = f[sel[1]] - f[sel[0]]
        fp.append(f[sel[j]] + d * df)
        floor = np.median(P if complex_in else P[: nfft // 2])
        q.append(10 * np.log10(Ps[j] / (floor + 1e-30)))
        tc.append((i + n / 2) / fs)
    return np.array(tc), np.array(fp), np.array(q)


def rs_enf_trace(s, t_frames, fps, H, row_bin, T_ro, f_grid=50.0, rows=None, win_s=16.0,
                 hop_s=1.0, band=0.5, degenerate=None):
    """Heterodyne + track.  Only at degenerate frame rates (fps divides f0) does the static
    scene land on 0 Hz in baseband; there (and only there) the whole-clip mean of z is removed.
    (A 60 s moving-mean high-pass at 30 fps was measured to *cost* accuracy: synthetic
    fps30_tro25 RMSE 3.27 -> 0.34 mHz without it; see progress.md.)"""
    f0 = 2 * f_grid
    if degenerate is None:
        degenerate = abs(alias_of(f0, fps)[0]) < band
    z = heterodyne(s, t_frames, T_ro, H, row_bin, f0, rows)
    if degenerate:
        z = z - z.mean()
    tc, fb, q = track(z, fps, -band, band, win_s, hop_s, complex_in=True)
    return tc, (f0 + fb) / 2.0, q, z


def alias_of(f0, fps):
    n = int(round(f0 / fps))
    return f0 - n * fps, n  # signed alias, multiple


def naive_enf_trace(m, fps, f_grid=50.0, win_s=16.0, hop_s=1.0, band=0.5):
    """Per-frame-mean baseline. Tracks the real-valued alias of 2*f_grid."""
    f0 = 2 * f_grid
    a, n = alias_of(f0, fps)
    lo, hi = max(abs(a) - band, 0.0), min(abs(a) + band, fps / 2)
    tc, fo, q = track(m - m.mean(), fps, lo, hi, win_s, hop_s, complex_in=False, remove_mean=True)
    if a >= 0:
        fl = n * fps + fo
    else:
        fl = n * fps - fo
    return tc, fl / 2.0, q, dict(alias_hz=float(a), degenerate=bool(abs(a) < band))

def strip_alias_enf_trace(s, fps, f_grid=50.0, win_s=16.0, hop_s=1.0, band=0.5, n_strips=45,
                          rows=None):
    """Stronger frame-rate baseline: split rows into horizontal strips (each strip's mean is a
    nearly instantaneous sample, so no sinc(f0*T_ro) cancellation), track the temporal alias
    in each strip and sum the strips' power spectra incoherently (phases differ per strip).
    Still one sample per frame per strip -> still degenerate when fps divides f0."""
    f0 = 2 * f_grid
    a, nmul = alias_of(f0, fps)
    R = s.shape[1]
    use = np.ones(R, bool) if rows is None else rows
    edges = np.linspace(0, R, n_strips + 1).astype(int)
    X = np.stack([s[:, e0:e1][:, use[e0:e1]].mean(axis=1) for e0, e1 in zip(edges[:-1], edges[1:])
                  if use[e0:e1].any()], axis=1)
    X = X - X.mean(axis=0)
    n = int(round(win_s * fps)); hop = int(round(hop_s * fps))
    nfft = 1 << int(np.ceil(np.log2(max(n * 4, fps / 0.002))))
    f = np.fft.rfftfreq(nfft, 1 / fps)
    lo, hi = max(abs(a) - band, 0.0), min(abs(a) + band, fps / 2)
    sel = np.where((f >= lo) & (f <= hi))[0]
    win = np.hanning(n)[:, None]
    tc, fo, q = [], [], []
    for i in range(0, len(X) - n + 1, hop):
        seg = X[i:i + n] - X[i:i + n].mean(axis=0)
        P = (np.abs(np.fft.rfft(seg * win, nfft, axis=0)) ** 2).sum(axis=1)
        Ps = P[sel]; j = int(np.argmax(Ps))
        d = 0.0
        if 0 < j < len(Ps) - 1:
            la, lb, lc = np.log(Ps[j - 1:j + 2] + 1e-30)
            den = la - 2 * lb + lc
            d = 0.5 * (la - lc) / den if den != 0 else 0.0
        fo.append(f[sel[j]] + d * (f[1] - f[0])); tc.append((i + n / 2) / fps)
        q.append(10 * np.log10(Ps[j] / (np.median(P) + 1e-30)))
    fo = np.array(fo)
    fl = nmul * fps + fo if a >= 0 else nmul * fps - fo
    return np.array(tc), fl / 2.0, np.array(q)


# ----------------------------------------------------------------------------- reference


def reference_enf(wav_path, f_grid=50.0, win_s=16.0, hop_s=1.0, band=0.5):
    fs, x = wavfile.read(wav_path)
    x = x.astype(float)
    if x.ndim > 1:
        x = x[:, 0]
    dur = len(x) / fs
    from scipy.signal import decimate
    while fs > 400 and fs % 2 == 0:          # decimate (zero-phase FIR) for speed
        x = decimate(x, 2, ftype="fir", zero_phase=True); fs //= 2
    tc, f, q = track(x - x.mean(), fs, f_grid - band, f_grid + band, win_s, hop_s,
                     complex_in=False, remove_mean=True)
    return tc, f, q, fs, dur


def compare(t_est, f_est, t_ref, f_ref, lag, q=None, q_min=None):
    """Interpolate reference at t_est + lag; return metrics."""
    tr = t_est + lag
    ok = (tr >= t_ref[0]) & (tr <= t_ref[-1]) & np.isfinite(f_est)
    if q is not None and q_min is not None:
        ok &= q >= q_min
    if ok.sum() < 5:
        return dict(n=int(ok.sum()))
    fr = np.interp(tr[ok], t_ref, f_ref)
    fe = f_est[ok]
    err = fe - fr
    return dict(n=int(ok.sum()), corr=float(np.corrcoef(fe, fr)[0, 1]),
                rmse_mHz=float(np.sqrt(np.mean(err ** 2)) * 1e3),
                bias_mHz=float(err.mean() * 1e3),
                rmse_debiased_mHz=float(np.std(err) * 1e3),
                mae_mHz=float(np.mean(np.abs(err)) * 1e3))


def lag_search(t_est, f_est, t_ref, f_ref, lags, q=None, q_min=None):
    cs = []
    for L in lags:
        r = compare(t_est, f_est, t_ref, f_ref, L, q, q_min)
        cs.append(r.get("corr", np.nan))
    cs = np.array(cs)
    return float(lags[int(np.nanargmax(cs))]), cs

# ----------------------------------------------------------------------------- CLI


def run_video(path, f_grid=50.0, row_bin=4, n_col=16, max_frames=None, win_s=16.0,
              mean_win_s=60.0, Tro=None, keep=None, cache=None, tro_seconds=180.0,
              allow_negative=False):
    if cache and os.path.exists(cache):
        d = np.load(cache, allow_pickle=True)
        cells, pts, clipf, meta = d["cells"], d["pts"], d["clipf"], d["meta"].item()
        kept = d["kept"] if "kept" in d and d["kept"].ndim == 3 else None
    else:
        cells, pts, clipf, meta, kept = decode_cells(path, row_bin, n_col, max_frames, keep)
        if cache:
            np.savez(cache, cells=cells, pts=pts, clipf=clipf, meta=np.array(meta),
                     kept=kept if kept is not None else np.zeros(0))
    t, fps, tinfo = regular_frame_times(pts)
    mask = static_mask(cells, clipf)
    f0 = 2 * f_grid
    a, _ = alias_of(f0, fps)
    degenerate = bool(abs(a) < 0.5)
    # degenerate fps: flicker is (nearly) static in each cell -> only a whole-clip mean may be
    # removed (measured on synthetic fps25: r 0.948 -> 0.986).  Otherwise 60 s moving mean.
    s, naive, rows, motion = row_signals(cells, mask, fps, 1e9 if degenerate else mean_win_s)
    n_use = min(len(t), int(tro_seconds * fps))
    if Tro is None:
        Tro_hat, grid, sc = estimate_Tro(s, t, fps, meta["H"], row_bin, f0, rows, n_use=n_use,
                                         allow_negative=allow_negative)
    else:
        Tro_hat, grid, sc = Tro, np.array([Tro]), np.array([np.nan])
    tc, fe, q, z = rs_enf_trace(s, t, fps, meta["H"], row_bin, Tro_hat, f_grid, rows, win_s,
                                degenerate=degenerate)
    tn, fn, qn, ninfo = naive_enf_trace(naive, fps, f_grid, win_s)
    st = strip_alias_enf_trace(s, fps, f_grid, win_s, rows=rows)
    return dict(strip=st, cells=cells, t=t, fps=fps, tinfo=tinfo, mask=mask, s=s, naive=naive, rows=rows,
                motion=motion, Tro=float(Tro_hat), Tro_grid=grid, Tro_score=sc, rs=(tc, fe, q), z=z,
                nv=(tn, fn, qn), ninfo=ninfo, meta=meta, kept=kept, alias=float(a),
                degenerate=degenerate)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--grid", type=float, default=50.0)
    ap.add_argument("--tro-ms", type=float, default=None, help="fix T_ro instead of searching")
    ap.add_argument("--win", type=float, default=16.0)
    ap.add_argument("--max-frames", type=int, default=None)
    ap.add_argument("--out", required=True, help="output prefix for trace CSVs / json")
    ap.add_argument("--cache", default=None)
    ap.add_argument("--allow-negative-tro", action="store_true",
                    help="also search bottom-up read-out (sign-ambiguous at degenerate fps)")
    a = ap.parse_args()
    r = run_video(a.video, a.grid, max_frames=a.max_frames, win_s=a.win, cache=a.cache,
                  Tro=None if a.tro_ms is None else a.tro_ms / 1e3,
                  allow_negative=a.allow_negative_tro)
    tc, fe, q = r["rs"]
    np.savetxt(a.out + "_rs_trace.csv", np.c_[tc, fe, q], delimiter=",", header="t_s,enf_hz,q_db",
               comments="")
    tn, fn, qn = r["nv"]
    np.savetxt(a.out + "_naive_trace.csv", np.c_[tn, fn, qn], delimiter=",",
               header="t_s,enf_hz,q_db", comments="")
    info = dict(video=a.video, fps=r["fps"], timing=r["tinfo"], Tro_ms=r["Tro"] * 1e3,
                alias_hz=r["alias"], degenerate_for_naive=r["degenerate"],
                static_cells=int(r["mask"].sum()), rows_used=int(r["rows"].sum()),
                median_q_rs_db=float(np.median(q)), median_q_naive_db=float(np.median(qn)))
    json.dump(info, open(a.out + "_info.json", "w"), indent=1)
    print(json.dumps(info, indent=1))


if __name__ == "__main__":
    main()
