# GhostClock Worker `W10` Handoff Guide (`HANDOFF.md`)

## 1. Production Components to Promote to Final Build (`ghostclock/`)

| Component & File Path | Target Integration Path | Public API / Contract | Why Keep It |
| :--- | :--- | :--- | :--- |
| **Forensic Matcher & Calibration Engine** ([`work/W10/matcher.py`](matcher.py)) | `ghostclock/matcher.py` | `match(trace, reference, search_start_utc=None, search_end_utc=None, config=None) -> dict` | Exact drop-in implementation of `integration/interfaces.md` §3. Runs 24-hour 1 s Weighted NCC + offset-adjusted RMSE in ~50 ms via `scipy.fft`, handles interior `NaN` gaps without timestamp shift, masks NESO flat-filled outages (`bad_intervals` + `_mask_flat_runs`), and computes Bartlett + time-reversed surrogate look-elsewhere $p$-values (`p_empirical`). |
| **Deterministic Decision Policy & Wilson CIs** ([`work/W10/policy.py`](policy.py)) | `ghostclock/policy.py` | `evaluate_policy(match_result, claimed_start_utc=None, tolerance_s=None, thresholds=None) -> dict`, `wilson_ci(k, n)` | Enforces 8 deterministic, auditable numerical gates (`MATCH_SUPPORTED`, `INCONCLUSIVE`, `MATERIAL_DISCREPANCY_REVIEW`), evaluates `claimed_start_utc` strictly *after* blind search, and populates human- and LLM-readable `status_reasons` and `what_would_change_this`. |
| **Independent Harmonic Consensus Extractor** ([`work/W10/fast_consensus_extractor.py`](fast_consensus_extractor.py)) | `ghostclock/audio_enf.py` (alongside `W06`) | `extract_independent_harmonics_consensus(wav_path, ...) -> dict` | Fixes single-harmonic interferer contamination in `C1/enf.py` (restoring `H1/003.wav` from $r = -0.140$ to $r = 0.9985$ and `H1/005.wav` from $r = +0.076$ to $r = 0.9937$) using vectorized `1000 Hz` STFT + inter-harmonic trajectory correlation consensus. |
| **Project Evaluation Protocol** ([`eval/protocol.md`](../../docs/source/eval_protocol.md)) | `eval/protocol.md` (already in place) | Canonical project evaluation rules | Governs all worker benchmarks, Wilson CIs, session-grouped Dev/Holdout splits, C1's $\pm 5\,\text{s}$ primary ENF-WHU tolerance vs per-file refined GT for $\pm 1\,\text{s}$, C2's flat-outage masking rules, and multimodal non-independence rules. |

---

## 2. Deck-Worthy Numbers (All Verified in [`work/W10/RESULTS.json`](RESULTS.json))

1. **`100.0%` Selective Accuracy (`51 / 51` combined across ENF-WHU Dev + Holdout) with `0.0%` False Contradiction Rate (`0 / 130`)** [`REAL-MEASURED`]:
   - On `ENF-WHU` **Dev** (`85 H1` positive clips, `33 H0` no-ENF clips, `85` wrong-day 24h searches, `85` surrogate 24h searches): W10 Policy v2 achieves **`41 / 41 (100.0%, 95% Wilson CI [91.4%, 100.0%])` selective accuracy** within $\pm 5\,\text{s}$ of README ground truth (and **`41 / 41 (100.0%)` within $\pm 1.0\,\text{s}$ of per-file refined ground truth**), **`73.2% (41 / 56)` coverage** on clean-extractor clips, **`0 / 33 (0.0%)` FPR on `H0`**, **`2 / 85 (2.4%)` FPR on wrong-day 24h references**, **`0 / 85 (0.0%)` FPR on surrogate references**, and **`0 / 85 (0.0%)` False Contradiction Rate (`FCR`)** on truthful timestamp claims.
   - On `ENF-WHU` **Unseen Holdout** (`45 H1`, `17 H0`, `45` wrong-day, `45` surrogate): Frozen Policy v2 achieves **`10 / 10 (100.0%, 95% CI [72.3%, 100.0%])` selective accuracy** (both at $\pm 5\,\text{s}$ README GT and $\pm 1.0\,\text{s}$ per-file refined GT), **`0 / 17 (0.0%)` FPR on `H0`**, **`0 / 45 (0.0%)` FPR on surrogates**, and **`0 / 45 (0.0%)` FCR**.
2. **Defeating the Look-Elsewhere Hallucination (`0.0%–2.4%` FPR vs `100.0%` Naive i.i.d. FPR)** [`REAL-MEASURED`]:
   - On a 300 s real GB NESO trace searched across the **wrong day** ($86,400\,\text{s}$), the peak spurious correlation is $r_{\max} = 0.7607$. A naive i.i.d. Fisher-$z$ test (`Baseline M2`) hallucinates $p_{\text{iid}} = 6.65 \times 10^{-58}$ (`100.0%` FPR across `203 / 203` Dev and `107 / 107` Holdout negative trials), whereas W10's Bartlett + time-reversed surrogate calibration yields $p_{\text{emp}} = 0.0987 \to \text{INCONCLUSIVE}$.
3. **Interior `NaN` Gap Robustness (`100.0%` W10 vs `0.0%` Open-Source `nate-griff/enf`)** [`SEMI-SYNTHETIC` on Real GB NESO Data]:
   - On 300 s GB NESO clips with a 20% (`60 s`) interior dropout gap, open-source baseline `nate-griff/enf` drops from `12 / 12 (100.0%)` to **`0 / 12 (0.0%)`** accuracy (missing by $-30,907\,\text{s}$ due to `.dropna()`), while W10's FFT masked Weighted NCC achieves **`12 / 12 (100.0%, CI [75.8%, 100.0%])`**.
4. **Reference Cadence Binding Limit (NESO `1 s` vs Elexon `15 s`)** [`SEMI-SYNTHETIC` on Real GB NESO Data]:
   - At $D = 300\,\text{s}$ ($\sigma = 3\,\text{mHz}$), 1-second NESO supports **`11 / 12 (91.7%)`** of clips at **`100.0%` selective accuracy**, whereas 15-second Elexon (+3.9 mHz scatter) supports `0 / 12 (0.0%)` at $60\text{–}120\,\text{s}$, `4 / 12 (33.3%)` at $300\,\text{s}$, and `8 / 12 (66.7%)` at $600\,\text{s}$ (with `100.0%` selective accuracy on all supported matches).

---

## 3. Deck-Ready Figures in `work/W10/plots/` (with Mandatory One-Line Epistemic Captions)

1. **[`work/W10/plots/fig1_null_calibration_and_look_elsewhere.png`](plots/fig1_null_calibration_and_look_elsewhere.png)**:
   - `REAL-MEASURED: 24-hour peak correlation distributions on ENF-WHU Dev (85 H1 positive vs 33 H0 no-ENF, 85 wrong-day, and 85 surrogate negative controls) and empirical look-elsewhere p-value calibration curve showing W10's conservative type-I error control versus naive i.i.d. Fisher-z failure (100% FPR).`
2. **[`work/W10/plots/fig2_neso_feasibility_and_cadence.png`](plots/fig2_neso_feasibility_and_cadence.png)**:
   - `SEMI-SYNTHETIC: GB NESO August 2026 1-second blind 24-hour matching support coverage and selective accuracy across clip durations (30s-600s) and noise levels (1-50 mHz), plus head-to-head comparison against 15-second Elexon cadence.`
3. **[`work/W10/plots/fig3_enf_whu_dev_vs_holdout_comparison.png`](plots/fig3_enf_whu_dev_vs_holdout_comparison.png)**:
   - `REAL-MEASURED: Head-to-head comparison of W10 Policy v1, W10 Policy v2, Open-Source Baseline M1 (nate-griff/enf), and Naive i.i.d. Baseline M2 on ENF-WHU Dev (85 H1, 33 H0, 85 Wrong-Day) and Unseen Holdout (45 H1, 17 H0, 45 Wrong-Day) with 95% Wilson confidence intervals.`
4. **[`work/W10/plots/fig4_forensic_case_traces_and_failure.png`](plots/fig4_forensic_case_traces_and_failure.png)**:
   - `REAL-MEASURED: Four-panel forensic case audit on ENF-WHU showing (a-b) blind 24-hour search peak and aligned waveform overlay, (c) wrong-day negative control abstention against a spurious r=0.60 peak, and (d) honest INCONCLUSIVE gating on an acoustically corrupted recording (H1/086.wav).`
