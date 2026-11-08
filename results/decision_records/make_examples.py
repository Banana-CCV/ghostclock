"""Write three example decision records (SYNTHETIC reference, see tests/test_smoke.py) showing the full audit trail.

Run from the repo root:  python results/decision_records/make_examples.py
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from ghostclock.matcher import match  # noqa: E402
from test_smoke import T0, _reference  # noqa: E402

OUT = Path(__file__).resolve().parent
ref = _reference()
win = dict(search_start_utc=T0, search_end_utc=T0 + len(ref) - 1)
off, dur = 9_000, 600
rng = np.random.default_rng(1)
f = ref.f_hz.to_numpy()[off:off + dur] + 0.002 + rng.normal(0, 0.002, dur)
q = np.ones(dur)
f[200:240] = np.nan
q[200:240] = 0.0
trace = {"t": np.arange(dur, dtype=float), "f": f, "q": q}
noise = {"t": np.arange(dur, dtype=float), "f": 50.0 + np.random.default_rng(2).normal(0, 0.01, dur), "q": np.ones(dur)}
cases = {
    "SYNTHETIC_claim_corroborated.json": (trace, {"claimed_start_utc": T0 + off + 20}),
    "SYNTHETIC_claim_discrepancy_2h.json": (trace, {"claimed_start_utc": T0 + off + 7200}),
    "SYNTHETIC_no_enf_inconclusive.json": (noise, {"claimed_start_utc": T0 + off}),
}
for name, (tr, cfg) in cases.items():
    res = match(tr, ref, config=cfg, **win)
    (OUT / name).write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")
    print(name, res["status"])
