"""Demo visualiser: makes the invisible mains flicker visible (director tool).

usage: python -m ghostclock.tools.make_demo_video <video> --start 30 --dur 15 [--trace out/quick/<stem>/video_rs_trace.csv]
                                                [--gain 40] [--zoom x0,y0,x1,y1 (fractions)] [--out file.mp4]
Panels: LEFT = what the camera saw (auto-brightened for viewing), RIGHT = the flicker alone
(frame minus a ~1 s running mean, amplified, false colour), BOTTOM = the extracted ENF trace
drawing in sync (if --trace is given). Every pixel is derived from the original file; the only
processing is brightening, temporal high-pass, gain and colour mapping, as stated on screen.
"""
import argparse, subprocess, glob, os, shutil
from collections import deque
from pathlib import Path
import sys
import numpy as np, cv2

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from ghostclock._paths import OUT_DIR, find_tool  # noqa: E402


def tool(name):
    p = find_tool(name)
    if not p:
        raise FileNotFoundError(f"{name} not found: put it on PATH or set GHOSTCLOCK_FFMPEG_DIR")
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video"); ap.add_argument("--start", type=float, default=0); ap.add_argument("--dur", type=float, default=15)
    ap.add_argument("--gain", type=float, default=40); ap.add_argument("--zoom", default=None)
    ap.add_argument("--trace", default=None); ap.add_argument("--out", default=None); ap.add_argument("--width", type=int, default=960)
    ap.add_argument("--band-axis", choices=["rows", "cols"], default="rows",
                    help="direction the bands run in the DISPLAYED frame (portrait phone video: cols)")
    a = ap.parse_args()
    cap = cv2.VideoCapture(a.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    cap.set(cv2.CAP_PROP_POS_MSEC, a.start * 1000)
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if a.zoom:
        x0, y0, x1, y1 = [float(v) for v in a.zoom.split(",")]
        crop = (int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H))
    else:
        crop = (0, 0, W, H)
    cw, ch = crop[2] - crop[0], crop[3] - crop[1]
    pw = a.width // 2; ph = int(ch * pw / cw) // 2 * 2
    trace = np.loadtxt(a.trace, delimiter=",", skiprows=1) if a.trace else None
    th = 220 if trace is not None else 0
    out = a.out or str(OUT_DIR / "quick" / f"{Path(a.video).stem}_flicker_demo.mp4")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    tmp = out + ".raw.avi"
    vw = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*"MJPG"), fps, (pw * 2, ph + th))
    buf = deque(maxlen=max(3, int(round(fps))))   # ~1 s running mean
    acc = None
    n = int(a.dur * fps)
    font = cv2.FONT_HERSHEY_SIMPLEX
    # brightening: global gain from the first frames' 99th percentile
    lum_ref = None
    for i in range(n):
        ok, fr = cap.read()
        if not ok:
            break
        fr = fr[crop[1]:crop[3], crop[0]:crop[2]]
        if fr.shape[1] > 1280:                                      # 4K: downscale early for speed
            fr = cv2.resize(fr, (fr.shape[1] // 3, fr.shape[0] // 3), interpolation=cv2.INTER_AREA)
        y = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY).astype(np.float32)
        if lum_ref is None:
            lum_ref = max(np.percentile(y, 99), 8.0)
        bright = np.clip(fr.astype(np.float32) * (235.0 / lum_ref), 0, 255)
        bright = (255 * (bright / 255) ** 0.6).astype(np.uint8)   # gamma lift for viewing only
        buf.append(y)
        acc = y.copy() if acc is None else acc
        mean = np.mean(buf, axis=0)
        resid = y - mean
        resid[y >= 250] = 0                                         # saturated lamp pixels carry no flicker
        # average ALONG the bands (sensor rows): kills pixel noise, keeps the rolling stripes
        k = max(3, (resid.shape[1] if a.band_axis == "rows" else resid.shape[0]) // 3) | 1
        resid = cv2.blur(resid, (k, 3) if a.band_axis == "rows" else (3, k))
        vis = np.clip(128 + a.gain * resid, 0, 255).astype(np.uint8)
        vis = cv2.applyColorMap(vis, cv2.COLORMAP_TWILIGHT_SHIFTED)
        L = cv2.resize(bright, (pw, ph)); R = cv2.resize(vis, (pw, ph))
        cv2.putText(L, "what the camera saw (brightened)", (10, 24), font, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(R, f"flicker only: frame - 1 s mean, x{a.gain:g}", (10, 24), font, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
        canvas = np.zeros((ph + th, pw * 2, 3), np.uint8)
        canvas[:ph, :pw] = L; canvas[:ph, pw:] = R
        if trace is not None:
            t_now = a.start + i / fps
            sel = trace[:, 0] <= t_now
            tt, ff = trace[:, 0], trace[:, 1]
            fmin, fmax = np.nanpercentile(ff, 1) - 0.005, np.nanpercentile(ff, 99) + 0.005
            tx = lambda t: int(10 + (t - tt.min()) / (tt.max() - tt.min() + 1e-9) * (pw * 2 - 20))
            fy = lambda f: int(ph + th - 20 - (f - fmin) / (fmax - fmin + 1e-9) * (th - 50))
            pts_all = np.array([[tx(t), fy(f)] for t, f in zip(tt, ff) if np.isfinite(f)], np.int32)
            cv2.polylines(canvas, [pts_all], False, (70, 70, 70), 1, cv2.LINE_AA)
            pts = np.array([[tx(t), fy(f)] for t, f in zip(tt[sel], ff[sel]) if np.isfinite(f)], np.int32)
            if len(pts) > 1:
                cv2.polylines(canvas, [pts], False, (80, 200, 255), 2, cv2.LINE_AA)
            cv2.line(canvas, (tx(min(t_now, tt.max())), ph + 5), (tx(min(t_now, tt.max())), ph + th - 5), (255, 255, 255), 1)
            cv2.putText(canvas, f"grid frequency recovered from the flicker: {fmin+0.005:.3f}-{fmax-0.005:.3f} Hz",
                        (10, ph + 22), font, 0.55, (220, 220, 220), 1, cv2.LINE_AA)
        vw.write(canvas)
    vw.release(); cap.release()
    subprocess.run([tool("ffmpeg"), "-y", "-v", "error", "-i", tmp, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", out], check=True)
    os.remove(tmp)
    print("wrote", out)


if __name__ == "__main__":
    main()
