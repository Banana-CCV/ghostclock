"""assemble_results.py -- build RESULTS.json from real_MOV2_results.json + synth/*_eval.json."""
import glob
import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
real = json.load(open(os.path.join(HERE, "real_MOV2_results.json")))
d = np.load(os.path.join(HERE, "real_MOV2_results.npz"))
g, sb = d["gb"], d["sb"]
i = int(np.argmax(sb)); j = int(np.argmin(np.abs(g + g[i])))
real_out = {k: v for k, v in real.items() if not k.endswith("_curve")}
real_out["readout_direction_mirror_score_ratio"] = float(sb[j] / sb[i])
real_out["note"] = ("REAL data. Metrics at the filename-implied lag (70 s) and at the lag maximising "
                    "correlation (searched over 10-130 s, 0.5 s steps; one free parameter). n = number "
                    "of 16 s windows at 1 s hop (overlapping, so not independent samples).")
synth = {}
for f in sorted(glob.glob(os.path.join(HERE, "synth", "SYNTH_*_eval.json"))):
    e = json.load(open(f))
    synth[e["case"]] = e
for name in ("fps25_tro25_alias_degenerate+bidir",):
    dg = np.load(os.path.join(HERE, "synth", "SYNTH_fps25_tro25_alias_degenerate_bidir_diag.npz"))
    gg, ss = dg["Tro_grid"], dg["Tro_score"]; a = int(np.argmax(ss)); b = int(np.argmin(np.abs(gg + gg[a])))
    if name in synth:
        synth[name]["readout_direction_mirror_score_ratio"] = float(ss[b] / ss[a])
        synth[name]["note"] = ("+/-T_ro tie (ratio ~1): direction unidentifiable at 25 fps; this run "
                               "happened to pick +T_ro. Archived run 1 (synth/old_pm_search_hp/) picked "
                               "-25.25 ms and got r = -0.949.")
out = dict(
    agent="C4", date="2026-11-08",
    method="rolling-shutter row-time heterodyne (rs_enf.py); baselines: naive whole-frame mean, "
           "strip-wise alias (per-row-band frame-rate sampling)",
    window_s=16.0, hop_s=1.0,
    real_MOV2=real_out,
    SYNTHETIC_cases=synth,
    synthetic_note="ALL entries under SYNTHETIC_cases are synthetic videos from synth_rs.py "
                   "(OU random-walk ENF, 640x360, 240 s, libx264). Truth = Hann-window-averaged ENF.",
)
json.dump(out, open(os.path.join(HERE, "RESULTS.json"), "w"), indent=1, default=float)
print("RESULTS.json written;", len(synth), "synthetic cases")
