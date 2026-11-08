> **Release note.** Study by Gemini worker W10. **Not independently re-verified** (grade B). The path-portable copies of `matcher.py` and `policy.py` are in [`ghostclock/`](../../ghostclock/README.md). Paths written `<WORKSPACE>` refer to the original pre-test workspace.

# GhostClock Worker `W10`: Forensic Matcher, Empirical Calibration & Evaluation Protocol (Auditor)

## Overview
Worker `W10` owns the **forensic statistical matching engine, empirical look-elsewhere calibration, deterministic decision policy, project evaluation protocol, and independent critical auditing** for GhostClock:
- **Matcher (`work/W10/matcher.py`)**: Implements `match(trace, reference, search_start_utc, search_end_utc, config) -> dict` per [`integration/interfaces.md`](../../docs/INTERFACES.md) §3. Features common-cadence resampling, per-window weighted mean removal, $O(R \log R)$ FFT-based Sliding Weighted Normalized Cross-Correlation (`score`) and offset-adjusted Weighted RMSE in mHz (`rmse_mhz`), top-$K$ non-maximum suppression (NMS), log-parabolic sub-sample refinement, optional $\pm 0.5\%$ clock-drift search, split-half consistency verification, and mandatory flat-outage / `bad_intervals` masking (`NaN`).
- **Statistical Calibration (`work/W10/matcher.py`)**: Replaces invalid i.i.d. Student-$t$ / Fisher-$z$ correlation tests and ad-hoc white-noise multipliers (`*4` in Hua et al. 2021 MATLAB code) with **Bartlett's (1946) autocorrelated effective sample size $N_{\text{eff}}$**, empirical time-reversed reference surrogates in Fisher-$z$ space, and **look-elsewhere trial-count correction $M_{\text{eff}}$** across the full search window.
- **Deterministic Decision Policy (`work/W10/policy.py`)**: Maps blind search outputs (and optional post-search `claimed_start_utc`) into `MATCH_SUPPORTED`, `INCONCLUSIVE`, or `MATERIAL_DISCREPANCY_REVIEW` with machine-readable `status_reasons` and actionable `what_would_change_this` recommendations.
- **Project Evaluation Protocol (`eval/protocol.md`)**: Defines primary metrics with 95% Wilson confidence intervals, session-grouped Dev/Holdout split rules, anti-leakage rules, $\pm 5\,\text{s}$ primary ENF-WHU timestamp tolerance (and per-file refined ground truth for $\pm 1\,\text{s}$ claims per `C1`'s audit), NESO flat-outage masking rules (per `C2`'s audit), baselines, and multimodal non-independence rules.
- **Independent Critical Audit (`agents/reviews/W10_audit_summary.md`)**: Documents statistical audits and vetoes of open-source baselines (`W05`), `C1`'s harmonic summation vs inter-harmonic trajectory consensus (`W06`), `C2`'s grid reference traps, and `W17`'s synthetic rubric simulation.

---

## Reproducible Commands (Run from Repository Root `<WORKSPACE>`)

### 1. Run Unit & Forensic Smoke Tests (< 2 seconds)
Verifies exact alignment across 40 s interior `NaN` gaps (where `nate-griff/enf` misses by $-30,907\,\text{s}$), clock-drift recovery ($\pm 3000\,\text{ppm}$), flat $50\,\text{Hz}$ tone rejection, wrong-day negative control abstention ($r_{\max}=0.7607 \to p_{\text{emp}}=0.0987 \to \text{INCONCLUSIVE}$ vs naive i.i.d. $p=6.65 \times 10^{-58}$), and post-search claim verification:
```powershell
python work/W10/test_matcher_unit.py
```

### 2. Run Matcher & Policy CLI Smoke Tests (< 1 second)
```powershell
python work/W10/matcher.py --self-test
python work/W10/policy.py --self-test
```

### 3. Reproduce Full Experimental Suite, Calibration & Plots (~25 seconds)
Runs Experiment 1 (GB NESO 1-second Dev Aug 2026 & Holdout Sep 2026 duration $\times$ noise grid, 1 s NESO vs 15 s Elexon cadence comparison, 7-day search window, interior `NaN` dropout ablation, 3-family empirical null calibration, and `2026-09-15` 3.1-hour flat-outage masking verification) and Experiment 2 (ENF-WHU real audio Dev `v1 -> v2` and frozen Holdout `v2` benchmark against Open-Source Baseline M1 `nate-griff/enf` and Naive i.i.d. Fisher-$z$ Baseline M2), writing [`work/W10/RESULTS.json`](RESULTS.json) and 4 PNG figures in [`work/W10/plots/`](plots):
```powershell
python work/W10/run_experiments.py
```

### 4. Verify Pre-Computed Trace Loader & Independent Harmonic Consensus Extractor
```powershell
python work/W10/test_c1_cache_loader.py
python work/W10/fast_consensus_extractor.py
```

---

## Key Files Owned by `W10`
- [`work/W10/matcher.py`](matcher.py): Production FFT Weighted NCC + RMSE matcher, Bartlett + surrogate look-elsewhere calibration, flat-outage masker, and open-source/naive baselines.
- [`work/W10/policy.py`](policy.py): Deterministic 8-gate forensic decision policy (`PolicyThresholds`, `evaluate_policy`, `wilson_ci`).
- [`eval/protocol.md`](../../docs/source/eval_protocol.md): Project-wide evaluation protocol.
- [`agents/reviews/W10_audit_summary.md`](../../reviews/W10_audit_summary.md): Independent statistical audit of sibling workers and baselines.
- [`work/W10/RESULTS.json`](RESULTS.json): All measured metrics with exact denominators and 95% Wilson CIs.
- [`work/W10/FINDINGS.md`](FINDINGS.md): Detailed empirical findings and literature citations.
- [`work/W10/FAILURES.md`](FAILURES.md): Honest post-mortem of failure modes and operational boundaries.
- [`work/W10/HANDOFF.md`](HANDOFF.md): Integration guide and deck-ready figure captions with epistemic tags (`REAL-MEASURED`, `SEMI-SYNTHETIC`).
