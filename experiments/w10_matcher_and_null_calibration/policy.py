"""
work/W10/policy.py — Deterministic Forensic Decision Policy & Counterfactual Engine
Owner: W10 (Forensic Statistician & Independent Critical Authority)

Enforces deterministic numerical gates (fixed on development data only; never
overridden by an LLM) to map a blind ENF match result into one of the three
allowed statuses:
  - MATCH_SUPPORTED
  - INCONCLUSIVE
  - MATERIAL_DISCREPANCY_REVIEW

Crucial Blindness Invariant (integration/interfaces.md §3):
  `claimed_start_utc` is NEVER passed to the candidate search in `matcher.py`.
  It is evaluated exclusively inside `evaluate_policy(...)` AFTER the blind
  search, candidate ranking, null calibration, and split-half checks are frozen.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Optional


@dataclass(frozen=True)
class PolicyThresholds:
    """
    Frozen deterministic decision thresholds tuned exclusively on Dev data.
    Never tune or alter these parameters on Holdout data.
    """
    # 1. Signal completeness & duration gates
    min_valid_duration_s: float = 25.0
    min_valid_samples: int = 20
    min_valid_fraction: float = 0.50

    # 2. Physical frequency variability gates (in mHz)
    # Guards against flat 50.000 Hz synthetic tones (std < 0.8 mHz) and
    # wild unphysical noise/random walks (std > 200 mHz).
    min_trace_std_mhz: float = 0.80
    max_trace_std_mhz: float = 200.0

    # 3. Statistical significance gate (look-elsewhere corrected p-value)
    max_p_empirical: float = 0.02

    # 4. Absolute & adaptive correlation score floor
    min_abs_score: float = 0.45
    require_above_null_threshold: bool = True

    # 5. Uniqueness margin vs second-best non-overlapping peak
    min_margin_vs_second: float = 0.04
    min_ratio_vs_second: float = 1.06

    # 6. Amplitude fidelity gate (offset-adjusted weighted RMSE in mHz)
    max_rmse_mhz: float = 40.0

    # 7. Split-half internal consistency gate
    min_duration_for_strict_split_half_s: float = 90.0
    max_split_half_lag_diff_s: float = 15.0
    min_split_half_local_corr: float = 0.25

    # 8. Claimed timestamp comparison tolerance (seconds)
    default_claim_tolerance_s: float = 60.0

    # 9. Optional upstream extractor quality / ENF-presence gate (when present in trace meta)
    min_enf_presence_score: float = 0.35


DEFAULT_THRESHOLDS = PolicyThresholds()


def wilson_ci(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """
    Compute 95% Wilson score confidence interval for a binomial proportion k / n.
    Follows eval/protocol.md §2.3.
    """
    if n <= 0:
        return (0.0, 1.0)
    p = float(k) / float(n)
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denom
    half_width = (z * math.sqrt((p * (1.0 - p) / n) + (z2 / (4.0 * n * n)))) / denom
    return (max(0.0, center - half_width), min(1.0, center + half_width))


def evaluate_policy(
    match_result: dict[str, Any],
    claimed_start_utc: Optional[int] = None,
    tolerance_s: Optional[float] = None,
    thresholds: Optional[PolicyThresholds | dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Deterministic decision policy evaluating a blind `match_result` dictionary.

    Parameters
    ----------
    match_result : dict
        Output dictionary from `matcher.match(...)` (per integration/interfaces.md §3).
    claimed_start_utc : int, optional
        Claimed recording start timestamp (UTC epoch seconds or relative reference offset).
        Evaluated ONLY after blind search is complete.
    tolerance_s : float, optional
        Allowed discrepancy (in seconds) between `best.start_utc` and `claimed_start_utc`
        before triggering `MATERIAL_DISCREPANCY_REVIEW`. Defaults to 60.0 s.
    thresholds : PolicyThresholds or dict, optional
        Custom dev-frozen thresholds.

    Returns
    -------
    dict
        Updated `match_result` with `"status"`, `"status_reasons"`,
        `"what_would_change_this"`, and `"policy_audit"` populated.
    """
    if thresholds is None:
        cfg = DEFAULT_THRESHOLDS
    elif isinstance(thresholds, dict):
        valid_keys = {f.name for f in PolicyThresholds.__dataclass_fields__.values()}
        filtered = {k: v for k, v in thresholds.items() if k in valid_keys}
        cfg = PolicyThresholds(**filtered)
    else:
        cfg = thresholds

    tol_s = float(cfg.default_claim_tolerance_s if tolerance_s is None else tolerance_s)

    best = match_result.get("best") or {}
    null_info = match_result.get("null") or {}
    uniq = match_result.get("uniqueness") or {}
    diag = match_result.get("diagnostics") or {}

    score = float(best.get("score", float("nan")))
    rmse_mhz = float(best.get("rmse_mhz", float("inf")))
    best_start_utc = int(best.get("start_utc", -1))

    p_emp = float(null_info.get("p_empirical", 1.0))
    score_thresh = float(null_info.get("score_threshold", cfg.min_abs_score))

    margin = float(uniq.get("margin_vs_second", 0.0))
    second_score = score - margin if math.isfinite(score) and math.isfinite(margin) else 0.0
    ratio_vs_second = (
        score / max(second_score, 1e-6)
        if (math.isfinite(score) and second_score > 0)
        else (999.0 if math.isfinite(score) and score > 0 else 0.0)
    )

    valid_dur_s = float(diag.get("valid_duration_s", 0.0))
    n_valid = int(diag.get("n_valid_samples", 0))
    valid_frac = float(diag.get("valid_fraction", 0.0))
    trace_std_mhz = float(diag.get("trace_std_mhz", 0.0))
    ref_std_mhz = float(diag.get("best_ref_std_mhz", 0.0))

    split_half_diff_s = float(diag.get("split_half_agreement_s", float("inf")))
    split_half_r1 = float(diag.get("split_half_r1_at_best", 0.0))
    split_half_r2 = float(diag.get("split_half_r2_at_best", 0.0))
    enf_presence_score = diag.get("enf_presence_score", None)

    failed_gates: list[str] = []
    passed_gates: list[str] = []
    counterfactuals: list[str] = []

    # Gate 0 (when extractor provides enf_presence_score): Upstream ENF-presence check
    if (
        enf_presence_score is not None
        and cfg.min_enf_presence_score > 0.0
        and float(enf_presence_score) < cfg.min_enf_presence_score
    ):
        failed_gates.append(
            f"GATE_ENF_PRESENCE_FAILED: Upstream harmonic ENF-presence score is "
            f"{float(enf_presence_score):.3f} (< {cfg.min_enf_presence_score:.3f} threshold), "
            f"indicating absence of coherent mains hum/flicker in the recording."
        )
        counterfactuals.append(
            f"Recording requires coherent narrowband harmonic energy with ENF-presence score >= "
            f"{cfg.min_enf_presence_score:.2f} (currently {float(enf_presence_score):.2f})."
        )
    elif enf_presence_score is not None and cfg.min_enf_presence_score > 0.0:
        passed_gates.append(
            f"GATE_ENF_PRESENCE_PASSED: Upstream ENF-presence score = {float(enf_presence_score):.3f} "
            f">= {cfg.min_enf_presence_score:.3f}."
        )

    # Gate 1: Valid duration and sample completeness
    if (
        valid_dur_s < cfg.min_valid_duration_s
        or n_valid < cfg.min_valid_samples
        or valid_frac < cfg.min_valid_fraction
    ):
        failed_gates.append(
            f"GATE_DURATION_QUALITY_FAILED: Valid ENF duration is {valid_dur_s:.1f}s "
            f"({n_valid} samples, {valid_frac*100:.1f}% valid), below minimum required "
            f"{cfg.min_valid_duration_s:.1f}s ({cfg.min_valid_samples} samples, "
            f"{cfg.min_valid_fraction*100:.0f}% valid)."
        )
        counterfactuals.append(
            f"A longer or cleaner recording with >= {cfg.min_valid_duration_s:.0f}s of usable "
            f"ENF signal (>= {cfg.min_valid_fraction*100:.0f}% valid windows) is needed to "
            f"attempt time corroboration."
        )
    else:
        passed_gates.append(
            f"GATE_DURATION_QUALITY_PASSED: {valid_dur_s:.1f}s valid ({valid_frac*100:.1f}% coverage)."
        )

    # Gate 2: Physical frequency variation (flat-tone / extreme-noise check)
    if not math.isfinite(trace_std_mhz) or trace_std_mhz < cfg.min_trace_std_mhz:
        failed_gates.append(
            f"GATE_FLAT_SIGNAL_FAILED: Extracted trace standard deviation is {trace_std_mhz:.3f} mHz "
            f"(< {cfg.min_trace_std_mhz:.2f} mHz floor); a flat nominal tone cannot date a recording."
        )
        counterfactuals.append(
            f"Observe genuine mains frequency fluctuations with standard deviation >= "
            f"{cfg.min_trace_std_mhz:.2f} mHz rather than an unmodulated or crystal-locked tone."
        )
    elif trace_std_mhz > cfg.max_trace_std_mhz:
        failed_gates.append(
            f"GATE_EXCESS_NOISE_FAILED: Extracted trace standard deviation is {trace_std_mhz:.1f} mHz "
            f"(> {cfg.max_trace_std_mhz:.1f} mHz ceiling), indicating severe non-ENF interference."
        )
        counterfactuals.append(
            f"Reduce estimation noise so extracted frequency std falls below {cfg.max_trace_std_mhz:.0f} mHz."
        )
    else:
        passed_gates.append(
            f"GATE_SIGNAL_VARIANCE_PASSED: Trace std = {trace_std_mhz:.2f} mHz (ref std = {ref_std_mhz:.2f} mHz)."
        )

    # Gate 3: Look-elsewhere calibrated p-value
    if not math.isfinite(p_emp) or p_emp > cfg.max_p_empirical:
        failed_gates.append(
            f"GATE_NULL_SIGNIFICANCE_FAILED: Look-elsewhere corrected p_empirical = {p_emp:.4g} "
            f"exceeds threshold alpha = {cfg.max_p_empirical:.3g} across M_eff = "
            f"{diag.get('m_eff', 1.0):.1f} effective candidate shifts (N_eff = {diag.get('n_eff', 0.0):.1f})."
        )
        counterfactuals.append(
            f"Achieve a peak correlation score >= {max(score_thresh, cfg.min_abs_score):.3f} "
            f"(currently {score:.3f}) so that look-elsewhere p_empirical <= {cfg.max_p_empirical:.3g}."
        )
    else:
        passed_gates.append(
            f"GATE_NULL_SIGNIFICANCE_PASSED: Look-elsewhere p_empirical = {p_emp:.4g} <= {cfg.max_p_empirical:.3g}."
        )

    # Gate 4: Minimum correlation score
    effective_min_score = (
        max(cfg.min_abs_score, score_thresh)
        if cfg.require_above_null_threshold and math.isfinite(score_thresh)
        else cfg.min_abs_score
    )
    if not math.isfinite(score) or score < effective_min_score:
        failed_gates.append(
            f"GATE_MIN_SCORE_FAILED: Best weighted NCC score {score:.4f} is below required "
            f"threshold {effective_min_score:.4f} (null threshold = {score_thresh:.4f}, "
            f"abs floor = {cfg.min_abs_score:.4f})."
        )
        if not any("peak correlation score" in c for c in counterfactuals):
            counterfactuals.append(
                f"Increase weighted NCC peak score by +{effective_min_score - (score if math.isfinite(score) else 0.0):.3f} "
                f"to reach >= {effective_min_score:.3f}."
            )
    else:
        passed_gates.append(
            f"GATE_MIN_SCORE_PASSED: Best score {score:.4f} >= {effective_min_score:.4f}."
        )

    # Gate 5: Uniqueness margin vs second-best non-overlapping peak
    uniq_passed = (margin >= cfg.min_margin_vs_second) or (ratio_vs_second >= cfg.min_ratio_vs_second and margin >= 0.025)
    if not uniq_passed:
        failed_gates.append(
            f"GATE_UNIQUENESS_FAILED: Margin over second-best non-overlapping candidate is "
            f"{margin:.4f} (ratio {ratio_vs_second:.3f}x, second-best score = {second_score:.4f} at "
            f"distance {uniq.get('second_best_distance_s', 0)}s), below required margin "
            f"{cfg.min_margin_vs_second:.3f}."
        )
        counterfactuals.append(
            f"Resolve ambiguity against competing candidate at offset {uniq.get('second_best_distance_s', 0)}s: "
            f"need peak margin >= {cfg.min_margin_vs_second:.3f} (currently {margin:.4f}), e.g. via a longer clip "
            f"or narrower search window."
        )
    else:
        passed_gates.append(
            f"GATE_UNIQUENESS_PASSED: Margin vs second-best peak = +{margin:.4f} ({ratio_vs_second:.2f}x)."
        )

    # Gate 6: Offset-adjusted RMSE in mHz
    if not math.isfinite(rmse_mhz) or rmse_mhz > cfg.max_rmse_mhz:
        failed_gates.append(
            f"GATE_RMSE_FAILED: Offset-adjusted RMSE is {rmse_mhz:.2f} mHz, exceeding maximum "
            f"allowed {cfg.max_rmse_mhz:.1f} mHz."
        )
        counterfactuals.append(
            f"Reduce frequency tracking error so offset-adjusted RMSE is <= {cfg.max_rmse_mhz:.1f} mHz "
            f"(currently {rmse_mhz:.2f} mHz)."
        )
    else:
        passed_gates.append(
            f"GATE_RMSE_PASSED: Offset-adjusted RMSE = {rmse_mhz:.2f} mHz <= {cfg.max_rmse_mhz:.1f} mHz."
        )

    # Gate 7: Split-half temporal consistency
    # Both halves at the best alignment should correlate positively with the reference,
    # OR for longer clips (>= 90s), independent half searches should agree within max_split_half_lag_diff_s
    both_halves_correlate = (
        split_half_r1 >= cfg.min_split_half_local_corr
        and split_half_r2 >= cfg.min_split_half_local_corr
    )
    independent_halves_agree = split_half_diff_s <= cfg.max_split_half_lag_diff_s

    if valid_dur_s >= cfg.min_duration_for_strict_split_half_s:
        # Pass if independent halves locate the same offset OR both halves exhibit strong local correlation (>= 0.45)
        split_ok = independent_halves_agree or (
            split_half_r1 >= 0.45 and split_half_r2 >= 0.45
        )
    else:
        split_ok = both_halves_correlate or independent_halves_agree

    if not split_ok:
        failed_gates.append(
            f"GATE_SPLIT_HALF_FAILED: First-half and second-half consistency failed "
            f"(independent half lag difference = {split_half_diff_s:.1f}s vs {cfg.max_split_half_lag_diff_s:.1f}s max; "
            f"local half correlations at best lag: r1 = {split_half_r1:.3f}, r2 = {split_half_r2:.3f})."
        )
        counterfactuals.append(
            f"Both halves of the recording must consistently support the same grid alignment "
            f"(local half correlations >= {cfg.min_split_half_local_corr:.2f} and/or independent half lag "
            f"agreement within +/-{cfg.max_split_half_lag_diff_s:.0f}s); current mismatch suggests transient "
            f"interference, splicing, or a spurious peak."
        )
    else:
        passed_gates.append(
            f"GATE_SPLIT_HALF_PASSED: Half correlations r1={split_half_r1:.3f}, r2={split_half_r2:.3f} "
            f"(independent lag diff = {split_half_diff_s:.1f}s)."
        )

    # Final Status Determination
    reasons: list[str] = []
    if len(failed_gates) > 0:
        status = "INCONCLUSIVE"
        reasons.extend(failed_gates)
        if claimed_start_utc is not None:
            reasons.append(
                f"CLAIM_NOT_EVALUATED: Because blind ENF match evidence did not pass all statistical "
                f"reliability gates ({len(failed_gates)} gate(s) failed), the claimed timestamp "
                f"({int(claimed_start_utc)}) can neither be corroborated nor contradicted."
            )
    else:
        # All 7 blind reliability gates passed!
        reasons.extend(passed_gates)
        if claimed_start_utc is None:
            status = "MATCH_SUPPORTED"
            reasons.append(
                f"BLIND_MATCH_SUPPORTED: Best alignment at start_utc={best_start_utc} "
                f"(score={score:.4f}, rmse={rmse_mhz:.2f} mHz, p_empirical={p_emp:.4g}) passed all 7 "
                f"forensic calibration gates."
            )
            counterfactuals.append(
                f"If a claimed timestamp were provided outside [{best_start_utc - int(tol_s)}, "
                f"{best_start_utc + int(tol_s)}] UTC (tolerance +/-{tol_s:.0f}s), status would shift to "
                f"MATERIAL_DISCREPANCY_REVIEW."
            )
            counterfactuals.append(
                f"If peak correlation dropped below {effective_min_score:.3f} or uniqueness margin "
                f"dropped below {cfg.min_margin_vs_second:.3f}, status would revert to INCONCLUSIVE."
            )
        else:
            claim_int = int(claimed_start_utc)
            claim_diff_s = abs(best_start_utc - claim_int)
            if claim_diff_s <= tol_s:
                status = "MATCH_SUPPORTED"
                reasons.append(
                    f"CLAIM_CORROBORATED: Blind ENF match start_utc={best_start_utc} agrees with "
                    f"claimed_start_utc={claim_int} within {claim_diff_s}s (<= tolerance {tol_s:.0f}s)."
                )
                counterfactuals.append(
                    f"If claimed_start_utc differed from {best_start_utc} by more than {tol_s:.0f}s "
                    f"(currently {claim_diff_s}s), status would change to MATERIAL_DISCREPANCY_REVIEW."
                )
                counterfactuals.append(
                    f"If look-elsewhere p_empirical exceeded {cfg.max_p_empirical:.3g} (currently {p_emp:.4g}), "
                    f"status would change to INCONCLUSIVE."
                )
            else:
                status = "MATERIAL_DISCREPANCY_REVIEW"
                reasons.append(
                    f"MATERIAL_DISCREPANCY_DETECTED: Blind ENF match strongly supports start_utc={best_start_utc} "
                    f"(score={score:.4f}, p_empirical={p_emp:.4g}, margin=+{margin:.4f}), which differs from "
                    f"claimed_start_utc={claim_int} by {claim_diff_s}s ({claim_diff_s/3600.0:.2f} hours), "
                    f"exceeding the {tol_s:.0f}s tolerance. Human specialist review is required."
                )
                counterfactuals.append(
                    f"Verification that recording device clock or timezone metadata had a documented "
                    f"offset of {best_start_utc - claim_int:+d}s ({(best_start_utc - claim_int)/3600.0:+.2f}h) "
                    f"would reconcile the discrepancy."
                )
                counterfactuals.append(
                    f"Evidence that the recording occurred on an isolated generator, UPS/inverter, or "
                    f"a different regional power grid would invalidate the reference comparison and "
                    f"change the conclusion to INCONCLUSIVE."
                )

    match_result["status"] = status
    match_result["status_reasons"] = reasons
    match_result["what_would_change_this"] = counterfactuals
    match_result.setdefault("diagnostics", {})["policy_audit"] = {
        "thresholds": asdict(cfg),
        "claimed_start_utc": int(claimed_start_utc) if claimed_start_utc is not None else None,
        "claim_tolerance_s": tol_s,
        "claim_discrepancy_s": (
            abs(best_start_utc - int(claimed_start_utc))
            if (claimed_start_utc is not None and best_start_utc >= 0)
            else None
        ),
        "n_gates_passed": len(passed_gates),
        "n_gates_failed": len(failed_gates),
    }
    return match_result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate deterministic GhostClock forensic decision policy on a match JSON."
    )
    parser.add_argument("--in", dest="in_path", required=True, help="Input match result JSON path")
    parser.add_argument("--out", dest="out_path", required=True, help="Output updated JSON path")
    parser.add_argument(
        "--claimed-start-utc",
        type=int,
        default=None,
        help="Optional claimed start UTC epoch seconds (compared ONLY after blind search)",
    )
    parser.add_argument(
        "--tolerance-s",
        type=float,
        default=60.0,
        help="Allowed tolerance in seconds between blind match and claimed start time",
    )
    args = parser.parse_args()

    in_file = Path(args.in_path)
    data = json.loads(in_file.read_text(encoding="utf-8"))
    updated = evaluate_policy(
        data,
        claimed_start_utc=args.claimed_start_utc,
        tolerance_s=args.tolerance_s,
    )
    out_file = Path(args.out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(updated, indent=2), encoding="utf-8")
    print(
        f"[W10 policy] status={updated['status']} | "
        f"score={updated.get('best', {}).get('score', float('nan')):.4f} | "
        f"p_emp={updated.get('null', {}).get('p_empirical', 1.0):.4g}"
    )


if __name__ == "__main__":
    main()
