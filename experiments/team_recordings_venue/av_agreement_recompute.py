"""Release-engineer recompute of audio-vs-video ENF agreement on the 49 s test clip A001_11081103_C002.
Simple method: interpolate the video trace onto the audio trace's window centres, Pearson r + mean difference.
Run from the repo root: python experiments/team_recordings_venue/av_agreement_recompute.py"""
from pathlib import Path
import numpy as np
D = Path(__file__).resolve().parent / "A001_11081103_C002"
a = np.loadtxt(D / "audio_trace.csv", delimiter=",", skiprows=1)
v = np.loadtxt(D / "video_rs_trace_dark.csv", delimiter=",", skiprows=1)
vi = np.interp(a[:, 0], v[:, 0], v[:, 1], left=np.nan, right=np.nan)
m = np.isfinite(vi)
print(f"n={m.sum()} r={np.corrcoef(a[m, 1], vi[m])[0, 1]:.3f} mean(audio-video)={1e3 * np.mean(a[m, 1] - vi[m]):+.2f} mHz")
