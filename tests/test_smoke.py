"""Smoke test on SYNTHETIC data (no downloads needed): the matcher + policy run end-to-end.

A smooth random-walk "grid" reference (6 h at 1 s) stands in for NESO. A 10-min excerpt with
noise and a 40 s gap must be found at the right offset; a pure-noise trace must NOT be reported
as MATCH_SUPPORTED. These are plumbing checks only and feed no reported metric.
Run:  python -m pytest tests -q     (or: python tests/test_smoke.py)
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ghostclock.matcher import match  # noqa: E402

T0 = 1_780_000_000


def _reference(seed=7, n=6 * 3600):
    rng = np.random.default_rng(seed)
    x = np.zeros(n)
    for i in range(1, n):  # mean-reverting random walk, ~tens of mHz wander
        x[i] = 0.995 * x[i - 1] + rng.normal(0, 0.0015)
    return pd.DataFrame({"ts_utc": T0 + np.arange(n, dtype="int64"), "f_hz": 50.0 + x})


def test_true_offset_found():
    ref = _reference()
    off, dur = 9_000, 600
    rng = np.random.default_rng(1)
    f = ref.f_hz.to_numpy()[off:off + dur] + 0.002 + rng.normal(0, 0.002, dur)
    q = np.ones(dur)
    f[200:240] = np.nan
    q[200:240] = 0.0
    res = match({"t": np.arange(dur, dtype=float), "f": f, "q": q}, ref,
                search_start_utc=T0, search_end_utc=T0 + len(ref) - 1)
    err = res["best"]["start_utc"] - (T0 + off)
    assert abs(err) <= 2, err
    assert res["status"] in {"MATCH_SUPPORTED", "INCONCLUSIVE", "MATERIAL_DISCREPANCY_REVIEW"}


def test_noise_not_supported():
    ref = _reference()
    rng = np.random.default_rng(2)
    dur = 600
    f = 50.0 + rng.normal(0, 0.01, dur)
    res = match({"t": np.arange(dur, dtype=float), "f": f, "q": np.ones(dur)}, ref,
                search_start_utc=T0, search_end_utc=T0 + len(ref) - 1)
    status = res["status"]
    assert status != "MATCH_SUPPORTED", status


if __name__ == "__main__":
    test_true_offset_found()
    test_noise_not_supported()
    print("smoke tests passed")
