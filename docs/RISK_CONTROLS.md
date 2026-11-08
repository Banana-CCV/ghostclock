# Risk controls

GhostClock's safety rule: **code measures and gates, a human decides.** No language model produces, edits or overrides a number or a status. Every control below is enforced in code ([ghostclock/policy.py](../ghostclock/policy.py), [ghostclock/matcher.py](../ghostclock/matcher.py)) and can be inspected in an output record ([decision_records/](../results/decision_records/make_examples.py)).

## 1. Allowed outputs

| Status | Meaning | What happens next |
|---|---|---|
| `MATCH_SUPPORTED` | Every reliability gate passed, and the best alignment agrees with the claim within tolerance (or no claim was given) | The investigator may treat the timing as corroborated. This is one piece of evidence, not a decision. |
| `INCONCLUSIVE` | At least one gate failed: signal too short or flat, weak significance, not unique, and so on | Lists `what_would_change_this` (for example a longer recording, the original device file, or a 1 s reference). Never counted against the claimant. |
| `MATERIAL_DISCREPANCY_REVIEW` | Every gate passed and the blind best match differs from the claimed time by more than the tolerance (default 60 s) | **Escalated to a human specialist.** The reasons include benign explanations: a device clock offset, a generator or UPS, or a different grid. |

There is **no** reject, deny or fraud status, and no code path issues one. This follows the FCA fair-handling duty ([USE_CASE.md](USE_CASE.md)).

## 2. Blindness invariant

The claimed timestamp is removed from the configuration **before** the search (`claimed_start_utc = cfg.pop(...)` in `matcher.match`). It is compared only in `evaluate_policy`, after candidate ranking, null calibration and split-half checks are fixed. The claim therefore cannot steer the search towards itself.

## 3. Deterministic gates (frozen thresholds, set on dev data only)

From `PolicyThresholds` in [policy.py](../ghostclock/policy.py):

| Gate | Threshold | Failure it guards against |
|---|---|---|
| Duration / coverage | ≥ 25 s valid, ≥ 20 samples, ≥ 50% valid | Clips too short to be unique (on 15 s Elexon data a 2-min clip has only 8 samples) |
| Signal variance | 0.8 mHz ≤ std ≤ 200 mHz | A synthetic flat 50.000 Hz tone; noise that is not physical |
| Null significance | look-elsewhere-corrected p_emp ≤ 0.02 | "Lucky" correlations over 86,400 offsets (naive p = 1e-58 → calibrated p = 0.10) |
| Minimum score | NCC ≥ 0.45 and above the calibrated null threshold | Weak alignments |
| Uniqueness | margin over the second-best non-overlapping peak ≥ 0.04 and ratio ≥ 1.06 | Duplicated or periodic references (ENF-WHU 090/091: margin 0.000, so `INCONCLUSIVE`) |
| Amplitude fidelity | offset-adjusted RMSE ≤ 40 mHz | Shape matches with the wrong amplitude |
| Split-half consistency | for clips ≥ 90 s, both halves agree to within 15 s | Spliced or composite recordings |
| ENF presence (optional) | extractor presence score ≥ 0.35 | Hum that is not the grid |
| Claim tolerance | 60 s | Only applies after every gate above has passed |

The reference side is guarded too: flat-filled outages and 0.0 Hz placeholders are masked, and known timezone-shifted months are corrected ([DATA.md](DATA.md)).

## 4. Abstain or escalate when unsure

- **No-ENF inputs** abstain: 0/153 false matches on the unseen holdout (C1). The W10 policy gave 0/17 (grade B).
- **Measured weakness:** wrong-day references still produced a match in 10.4% of 5-min holdout trials. The required fix, not yet implemented, is a cross-day uniqueness gate that searches the claimed day ± N days and reports the runner-up day. Until it exists, any `MATCH_SUPPORTED` from a single-day search should be read with that rate in mind ([LIMITATIONS.md](LIMITATIONS.md)).
- **Speed and splice checks** never produce a finding. Their strongest output is `SPEED_ALTERED_REVIEW`, which means "refer to a human" ([C3](../experiments/c3_speed_and_splice/README.md)).

## 5. Explanations a person can act on

Every result carries:

- `status_reasons`: one machine-readable line per gate, with the measured value and threshold, for example `GATE_UNIQUENESS_FAILED: Margin ... 0.0232 ... below required margin 0.040`.
- `what_would_change_this`: counterfactuals, for example "If peak correlation dropped below 0.977 ... status would revert to INCONCLUSIVE".
- `diagnostics.policy_audit`: the full threshold set used, the claim, the tolerance, the discrepancy, and the number of gates passed and failed.

See the three SYNTHETIC example records: [corroborated](../results/decision_records/SYNTHETIC_claim_corroborated.json), [discrepancy](../results/decision_records/SYNTHETIC_claim_discrepancy_2h.json) and [no-ENF](../results/decision_records/SYNTHETIC_no_enf_inconclusive.json).

## 6. Logging and provenance

- Each decision is a self-contained JSON record holding inputs, the search window, the top-K candidates, the null statistics, every gate value, and the thresholds.
- Reference data carries sidecars with source URL, coverage and SHA-256 ([data_manifest/gb/](data_manifest/gb/neso_2026_09.json)). The reference loader records which files and time corrections it used (`df.attrs`).
- Media is hashed on arrival ([SHA256SUMS.txt](../experiments/team_recordings_venue/SHA256SUMS.txt)). `quick_check` writes a `report.json` per file.
- **Agent actions:** in the C5 Argon investigator, every Argon call, tool call and gate decision is written to `runs/<case>/trace.jsonl` with timestamp, actor, input summary, output, tokens and latency. Conflicts between Argon and the gate are logged ([case e](../experiments/c5_argon_agent/runs/case_e/trace.jsonl)).

## 7. Visible safeguards (demo)

**The agent is overruled by code.** In C5 case e, a false claimed start (+7200 s) is visible only to the gate. Argon, seeing the clean match, proposes `MATCH_SUPPORTED`. The gate returns `MATERIAL_DISCREPANCY_REVIEW` and logs "Argon proposed MATCH_SUPPORTED, gate decided MATERIAL_DISCREPANCY_REVIEW: gate wins" ([trace](../experiments/c5_argon_agent/runs/case_e/trace.jsonl)). The C5 gate uses C1's frozen per-length thresholds, a 60 s minimum duration, a 5 s agreement rule across configurations, and a 60 s claim tolerance.

**Calibrated statistics.**

A wrong-day or no-ENF clip goes in. Naive statistics would report "match, p = 1e-58"; GhostClock reports `INCONCLUSIVE`, names the failed gates, and lists the evidence that would change the result. The UI prototypes put this human-review gate on screen. They use labelled ILLUSTRATIVE fixtures ([prototypes/ui](../prototypes/ui/README.md)).

## 8. Process risk controls (how the work was built)

- Workers had scoped permissions: no git push, and writes only inside the project folder.
- The dev/holdout split was frozen before tuning, and the holdout was run once.
- The director re-derived the headline numbers with separate code ([reviews/](../reviews/README.md)).
- Every claim carries an evidence grade, and every dataset a REAL / SEMI-SYNTHETIC / SYNTHETIC / ILLUSTRATIVE label.
