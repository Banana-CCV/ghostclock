> **Release note.** Study by Gemini worker W11. **Not independently re-verified**: the director grades it B, despite the self-assessment below. The NESO raw data (`data/`) is excluded. Treat the settlement-boundary volatility result as a lead, not a claim.

# GhostClock W11 — Uniqueness & Feasibility Mathematics (NESO-Based)

**Worker ID:** `W11`  
**Role:** Deterministic-Math Lead — ENF Uniqueness, Stochastic Modeling, Feasibility Surface, Minimum-Duration Rule, and Calibrated Look-Elsewhere Correction  
**Status:** Complete (Evidence Grade **A** on real GB NESO 1-second grid history; **B** on semi-synthetic noise/drift/dropout stress suite)

---

## 1. Core Questions Answered

1. **How much recording duration $D$ do we need, at what reference resolution $R \in \{1\text{ s}, 15\text{ s}\}$, to identify the recording timestamp uniquely across a search window $W \in \{1\text{ h}, 6\text{ h}, 1\text{ day}, 1\text{ week}, 1\text{ month}\}$?**
2. **How likely is a false match ($P_f$), and how does the best wrong-candidate correlation $r_{\max,\text{null}}$ scale with $D$, $W$, and extractor estimation noise $\sigma \in \{0, 1, 2, 5, 10\}\text{ mHz}$?**
3. **Can we model the Great Britain (GB) grid frequency process analytically (Ornstein–Uhlenbeck / $\text{AR}(2)$ + Karhunen–Loève Subspace Projection) to predict top-1 identification accuracy and extreme-value null thresholds on unseen months?**
4. **Are there times of day or hour (e.g., Elexon 30-minute settlement boundaries at `:00` and `:30`) when ENF is significantly more distinctive?**
5. **Is a same-day live demo using Elexon $15\text{ s}$ reference data viable, and what minimum duration and resampling method (`15s_avg` vs. `15s_point`) does it require?**

---

## 2. Exact Reproducible Run Commands (from Repo Root)

All scripts are self-contained, fix random seeds (`numpy.random.default_rng`), and run from the repository root (`<WORKSPACE>`):

```powershell
# 1. Download and standardize real GB NESO 1-second system frequency data (Aug 2026 Dev + Sep 2026 Holdout)
python work\W11\fetch_neso.py --out-dir work\W11\data

# 2. Execute the full W11 experimental suite (OU/AR theory, settlement structure, Monte Carlo grid,
#    extractor error stress tests, Step G AR-whitened iteration, W10 calibration JSON, and 6 plots)
python work\W11\run_experiments.py --data-dir work\W11\data --out-dir work\W11 --n-trials-dev 60 --n-trials-holdout 60

# 3. Run pilot theory vs. empirical null tail verification
python work\W11\inspect_null_tail.py
python work\W11\test_kl_and_whitening.py
```

No additional `pip` packages beyond the shared Python 3.12 virtual environment (`numpy`, `scipy`, `pandas`, `pyarrow`, `matplotlib`, `requests`) are required.

---

## 3. Dataset Manifest & Strict Temporal Split

All reference frequency series are **100% authentic Great Britain 1-second measurements** from the National Energy System Operator (NESO) System Frequency Data Portal (`https://www.neso.energy/data-portal/system-frequency-data`, NESO Open Data Licence). All query segments with injected Gaussian noise ($\sigma$), clock drift, burst dropouts, or outliers are explicitly labelled **`semi-synthetic`** throughout `RESULTS.json`, plots, and documentation.

| Split | File | Coverage (UTC) | Regular 1 s Samples | Raw Gaps | Mean Frequency | Global Std $\sigma_f$ | Parquet SHA-256 |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **Dev** | `work/W11/data/fnew-2026-8.parquet` | `2026-08-01T00:00:00Z` – `2026-08-31T23:59:59Z` | $2,678,400$ | $0$ | $49.99998\text{ Hz}$ | $75.53\text{ mHz}$ | `71790853965987e6f3b69458b950830dd5c20ae08d0f915c6f2681a3e92a59c2` |
| **Holdout** | `work/W11/data/fnew-2026-9.parquet` | `2026-09-01T00:00:00Z` – `2026-09-30T23:59:59Z` | $2,592,000$ | $0$ | $49.99838\text{ Hz}$ | $81.70\text{ mHz}$ | `e8732a2f45a3b7a68136aef083e0fd34dd492a0f4ff6a9daf86dbad33a768e72` |

---

## 4. Artifact Inventory in `work/W11/`

- **`PLAN.md`**: Pre-execution experimental plan, primary literature synthesis, physical constraints, and falsifiable thresholds.
- **`FINDINGS.md`**: Full scientific and mathematical report with derivations, empirical tables, and literature citations.
- **`RESULTS.json`**: Machine-readable results across all $300$ $(D, \sigma, W, R)$ Dev + Holdout cells, OU/AR process fits, settlement boundary tests, extractor stress suite, Step G iteration, and null false-positive audits.
- **`FAILURES.md`**: Forensic critique of failure modes ($D = 30\text{ s}$ ramp ambiguity, $R = 15\text{ s}$ point-sampling aliasing, uncompensated $1000\text{ ppm}$ clock drift, and floating-point `cumsum` cancellation near $50.0\text{ Hz}$).
- **`HANDOFF.md`**: Frozen integration guide for `W10` (matcher/auditor), `W12` (live reference feed), `W15` (demo UX), and `W17` (pitch deck).
- **`look_elsewhere.py`** & **`look_elsewhere_calibration.json`**: Importable Python API and calibrated lookup tables for look-elsewhere corrected $p$-values, score thresholds, and minimum-duration gates.
- **`model_theory.py`**: Ornstein–Uhlenbeck, $\text{AR}(2)$, Karhunen–Loève spectrum, and Subspace Projection analytic model implementation.
- **`plots/`**:
  1. `plots/feasibility_surface.png` — 15-panel $(D \times \sigma \to \text{accuracy})$ heatmap across all $R$ and $W$ on unseen Holdout.
  2. `plots/theory_vs_mc.png` — Empirical vs. analytic accuracy and $95\text{th}$-percentile wrong-candidate score calibration.
  3. `plots/daily_hourly_structure.png` — Elexon 30-minute settlement boundary spikes (`:00` and `:30`) and stratified identification accuracy.
  4. `plots/wrong_score_distributions.png` — True match vs. best wrong-candidate score distributions across duration $D$.
  5. `plots/extractor_errors_stress.png` — Stress test under clock drift ($100\text{ ppm}$ vs. $1000\text{ ppm}$), $30\%$ burst dropouts, and impulse outliers.
  6. `plots/iteration_whitened_vs_raw.png` — Step G Iteration comparing Hybrid AR-Innovation Whitened correlation against Raw Pearson correlation.
