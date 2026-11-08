# GhostClock Worker `W10` Failures & Operational Boundary Post-Mortem (`FAILURES.md`)

As GhostClock's Forensic Statistician and Independent Critical Authority, `W10` documents both (a) internal hypotheses/models that failed during development and were replaced, and (b) hard physical/statistical failure boundaries where ENF corroboration **must abstain (`INCONCLUSIVE`)**.

---

## 1. Internal Model Failure & Fix: Heavy-Tailed Student-$t(\nu)$ Extreme-Value Extrapolation

- **What failed**: In our initial implementation of `calibrate_null_and_pvalue()` (`matcher.py` v0), we transformed the sample correlation $r$ into a Student-$t$ statistic $t = r\sqrt{\nu / (1 - r^2)}$ using Bartlett's effective degrees of freedom $\nu = N_{\text{eff}} - 2$, and evaluated the look-elsewhere threshold by inverting the polynomial Student-$t$ tail at $\alpha_{\text{local}} \approx \alpha / M_{\text{eff}} \approx 10^{-5}$.
- **Symptom**: For a 300 s real GB NESO trace where Bartlett's effective degrees of freedom was $\nu \approx 4.2$, the Student-$t(\nu = 4.2)$ inverse survival function at $10^{-5}$ mapped to `score_threshold = 0.9987`, rejecting clean real-world matches with $r = 0.93$!
- **Root cause**: Sample correlation coefficients $r \in [-1, 1]$ between smooth band-limited processes have **bounded support** and sub-Gaussian tails in Fisher-$z$ space ($\text{atanh}(r)$ has measured excess kurtosis $-0.78$ on time-reversed reference surrogates), whereas a Student-$t$ distribution with $\nu = 4.2$ has heavy polynomial tails ($t^{-\nu}$) that wildly overestimate extreme quantiles when extrapolated across $M_{\text{eff}} \approx 2,500$ trials.
- **How we fixed it**: Replaced the polynomial Student-$t$ tail with a variance-stabilized Fisher-$z$ (`z = atanh(r)`) tail calibrated directly to the **95th and 99th percentiles of the empirical time-reversed reference null distribution** (`z_tail_95`, `z_tail_99`, `z_bulk_std`), combined conservatively with Bartlett's $N_{\text{eff}}$. This restored `score_threshold` to the true empirical 99th-percentile extreme-value envelope ($\approx 0.65\text{–}0.78$ for 300 s clips over 24 hours).

---

## 2. Hard Physical & Statistical Failure Modes (Where GhostClock Must Abstain)

### Failure Mode A: Short Clips ($D \le 60\,\text{s}$) Under Moderate Noise ($\sigma \ge 5\,\text{mHz}$) in 24-Hour Search Windows
- **Measured Evidence ([`work/W10/RESULTS.json`](RESULTS.json) Experiment 1A)**:
  - At $D = 30\,\text{s}$ ($N = 30$ samples at 1 s cadence), a 24-hour reference contains $M_{\text{eff}} \approx 5,400$ independent candidate shifts, and Bartlett's $N_{\text{eff}}$ is only $\approx 2.8\text{–}3.5$. Even at $\sigma = 5\,\text{mHz}$, raw top-1 accuracy drops to `2/10 (20.0%)` and W10's policy abstains on `10/10 (100.0%)` trials (`coverage = 0.0%`).
  - At $D = 60\,\text{s}$ and $\sigma = 5\,\text{mHz}$, raw top-1 accuracy is `6/10 (60.0%)` and W10 supports only `1/10 (10.0%)` (`selective_acc = 1/1 = 100.0%`).
- **Operational Rule**: For 24-hour blind searches on 1 s NESO data, reliable high-coverage corroboration requires **$D \ge 120\text{–}300\,\text{s}$** (or a narrower claimed search window, e.g., $\pm 1\,\text{hour}$).

### Failure Mode B: Elexon 15-Second Rolling Reference on Clips Shorter Than 5 Minutes ($D < 300\,\text{s}$)
- **Measured Evidence (Experiment 1B, `cadence_1s_vs_15s_comparison`)**:
  - At 15 s cadence, a $60\,\text{s}$ clip has only $N = 4$ samples and a $120\,\text{s}$ clip has only $N = 8$ samples. Furthermore, `C2` proved that 2026 Elexon spot measurements exhibit ~3.9–6.3 mHz of additional scatter relative to NESO 1 s data.
  - At $D = 60\,\text{s}$ and $120\,\text{s}$, W10's `GATE_DURATION_OR_COVERAGE_FAILED` (`min_valid_samples = 20`) forces `0/12 (0.0%)` coverage (`INCONCLUSIVE`). At $D = 300\,\text{s}$ ($N = 20$) coverage rises to `4/12 (33.3%)`, and at $D = 600\,\text{s}$ ($N = 40$) coverage reaches `8/12 (66.7%)`, with `100.0%` selective accuracy on all supported matches.
- **Operational Rule**: Never claim that Elexon's 15 s live/rolling feed can date 30–120 s voice notes over a 24-hour window; 15 s Elexon requires **$D \ge 5\text{–}10\,\text{minutes}$**.

### Failure Mode C: Duplicate / Periodic Reference Windows (`ENF-WHU 089-107_ref.wav`, Clips `090` & `091`)
- **Measured Evidence (`dev_v2_iterated["per_case_h1"]`)**:
  - In `ENF-WHU`, the 24-hour reference file `089-107_ref.wav` contains a dataset packaging bug where 42 ten-minute blocks are duplicated exactly $3600\,\text{s}$ (1 hour) apart.
  - For `H1/090.wav` ($r = 0.9975, \text{RMSE} = 1.40\,\text{mHz}, p_{\text{emp}} = 9.08 \times 10^{-35}$) and `H1/091.wav` ($r = 0.9911, \text{RMSE} = 1.24\,\text{mHz}, p_{\text{emp}} = 1.79 \times 10^{-20}$), the top-1 peak and second-best peak (3600 s away) have identical correlation, yielding `margin_vs_second = 0.0000 < 0.05`.
  - W10's uniqueness gate (`GATE_UNIQUENESS_FAILED`) correctly overrides the high correlation and returns `INCONCLUSIVE`.

### Failure Mode D: Flat-Filled Grid Outages (`NESO 2026-09-15 07:30:03..10:35:59 UTC`)
- **Measured Evidence (`c2_flat_outage_masking_verification`)**:
  - During a 3.1-hour telemetry outage on `2026-09-15`, NESO filled `11,158` consecutive 1-second rows with a constant `49.895 Hz`.
  - Without flat-run masking, any zero-variance or step-artifact trace could spuriously align against the outage boundary. [`work/W10/matcher.py`](matcher.py) masks both `.json` sidecar `bad_intervals` and any flat stretch ($\ge 15$ consecutive constant samples), ensuring `0` candidates ever land in the outage and rejecting flat queries via `GATE_FLAT_SIGNAL_FAILED`.

### Failure Mode E: Single-Harmonic Acoustic Interferers in `work/C1/enf.py` (Holdout Coverage Drop)
- **Measured Evidence (`holdout_v2_frozen` & [`work/W10/fast_consensus_extractor.py`](fast_consensus_extractor.py))**:
  - On the ENF-WHU Holdout split (`45 H1` clips), only `14/45` clips in `work/C1/cache/w16/` had clean extracted traces (`rec_ref_r_at_d >= 0.85`), because `C1/enf.py` sums harmonic spectra linearly by `snr_frame` before peak picking (`H1/003.wav` drops to $r = -0.140$, `H1/005.wav` drops to $r = +0.076$).
  - When fed those corrupted traces, W10 **safely abstained (`INCONCLUSIVE`) on all 31 corrupted Holdout clips**, maintaining **`10/10 (100.0%)` selective accuracy** (`9/14 = 64.3%` coverage on the clean-extractor subset, `0.0%` false contradictions). Furthermore, [`work/W10/fast_consensus_extractor.py`](fast_consensus_extractor.py) proved that picking harmonic peaks independently and weighting by inter-harmonic trajectory correlation consensus restores `003.wav` to $r = 0.9985$ and `005.wav` to $r = 0.9937$.
