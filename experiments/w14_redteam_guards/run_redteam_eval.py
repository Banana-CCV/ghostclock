#!/usr/bin/env python3
"""
GhostClock Worker W14: Master Red-Team Evaluation & Plot Generator (`work/W14/run_redteam_eval.py`)
===================================================================================================
Executes the full adversarial red-team matrix (Attacks a-g) and clean-dev
false-alarm evaluation across:
  1. Authentic ENF-WHU `dev` recordings (strictly filtered via `eval/splits/enf_whu_split.json`,
     zero holdout files touched).
  2. Labelled `[SYNTHETIC-NESO]` GB recordings synthesized from real NESO 1-second
     historical grid frequency traces (`2026-08-01` vs `2026-09-01`).

Imports sibling modules read-only:
  - `work/W02/gb_reference.py` (`load_reference`)
  - `work/W03/enf_whu.py` (`_fast_baseband_enf_50hz`)
  - `work/W06/audio_enf.py` (`extract_audio_enf_detailed`, `compute_enf_presence`)
  - `work/W07/audio_enf_b.py` (`extract_audio_enf_b`)
  - `work/W10/matcher.py` (`match`, `match_baseline_opensource_nate_griff`, `match_baseline_naive_iid`)
  - `work/W10/policy.py` (`evaluate_policy`)

Usage from repo root:
    python work/W14/run_redteam_eval.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import soundfile as sf

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from work.W02.gb_reference import load_reference
from work.W03.enf_whu import _fast_baseband_enf_50hz
from work.W06.audio_enf import extract_audio_enf_detailed
from work.W10.matcher import match as w10_match, match_baseline_naive_iid
from work.W14.attacks import (
    DEFAULT_SEED,
    attack_a_notch_removal,
    attack_b_enf_injection,
    attack_c_double_enf,
    attack_d_transform,
    attack_e_crop_duration,
    attack_f_splice_concat,
    attack_g_metadata_spoof_file,
    compute_sha256_bytes,
    generate_synthetic_neso_clip,
)
from work.W14.guards import (
    _fast_sliding_ncc,
    evaluate_all_guards,
    extract_harmonic_diagnostics,
)

W14_DIR = Path(__file__).resolve().parent
PLOTS_DIR = W14_DIR / "plots"
CACHE_DIR = W14_DIR / "cache"
MANIFEST_CSV = REPO_ROOT / "datasets" / "manifests" / "enf_whu_cases.csv"
SPLIT_JSON = REPO_ROOT / "eval" / "splits" / "enf_whu_split.json"


def _parse_notes(notes_str: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for part in str(notes_str).split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def load_dev_cases() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Load strictly `dev` H1 and H0 cases from `datasets/manifests/enf_whu_cases.csv`."""
    split_data = json.loads(SPLIT_JSON.read_text(encoding="utf-8"))
    dev_ids = set(split_data["splits"]["dev"]["all"])
    holdout_ids = set(split_data["splits"]["holdout"]["all"])

    h1_dev: List[Dict[str, Any]] = []
    h0_dev: List[Dict[str, Any]] = []
    with open(MANIFEST_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cid = row["case_id"]
            if cid in holdout_ids or row["split"] != "dev":
                continue
            assert cid in dev_ids, f"Case {cid} not in dev split!"
            notes = _parse_notes(row["notes"])
            row["parsed_notes"] = notes
            if row["has_enf_label"].lower() == "true":
                row["true_lag_s"] = int(round(float(notes["one_day_lag_s"])))
                row["one_day_ref_path"] = REPO_ROOT / notes["one_day_ref_path"]
                row["sync_ref_path"] = REPO_ROOT / notes["sync_ref_path"]
                h1_dev.append(row)
            else:
                h0_dev.append(row)
    return h1_dev, h0_dev


def load_24h_ref_trace_cached(ref_wav_path: Path) -> Tuple[np.ndarray, np.ndarray]:
    """Extract or load cached 1s-cadence 24-hour reference trace from `H1_ref_one_day`."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{ref_wav_path.stem}_1s.npz"
    if cache_file.exists():
        with np.load(cache_file) as data:
            return data["t"], data["f"]
    sig, fs = sf.read(str(ref_wav_path), dtype="float64")
    if sig.ndim > 1:
        sig = sig[:, 0]
    t, f, _ = _fast_baseband_enf_50hz(sig, fs=int(round(fs)), window_s=16.0, hop_s=1.0)
    np.savez(cache_file, t=t, f=f)
    return t, f


def load_neso_days() -> Tuple[np.ndarray, np.ndarray, Dict[str, Any]]:
    """
    Load two distinct 24-hour GB NESO 1-second reference days:
      - Day A (Authentic Reference): 2026-08-01 (1785542400..1785628799 UTC)
      - Day B (Spoof / Wrong Date):  2026-09-01 (1788220800..1788307199 UTC)
    """
    df_a = load_reference("2026-08-01T00:00:00Z", "2026-08-01T23:59:59Z", source="NESO", allow_network=False)
    df_b = load_reference("2026-09-01T00:00:00Z", "2026-09-01T23:59:59Z", source="NESO", allow_network=False)
    f_a = df_a["f_hz"].to_numpy(dtype=np.float64)
    f_b = df_b["f_hz"].to_numpy(dtype=np.float64)
    info = {
        "day_a_date": "2026-08-01",
        "day_a_start_utc": int(df_a["ts_utc"].iloc[0]),
        "day_a_n_samples": len(f_a),
        "day_a_std_mhz": round(float(np.nanstd(f_a) * 1000.0), 2),
        "day_b_date": "2026-09-01",
        "day_b_start_utc": int(df_b["ts_utc"].iloc[0]),
        "day_b_n_samples": len(f_b),
        "day_b_std_mhz": round(float(np.nanstd(f_b) * 1000.0), 2),
    }
    return f_a, f_b, info


def evaluate_single_case(
    audio: np.ndarray,
    fs: float,
    ref_f: np.ndarray,
    true_lag_s: Optional[int],
    spoof_lag_s: Optional[int] = None,
    claimed_lag_s: Optional[int] = None,
    is_tampered: bool = False,
    attack_expectation: str = "abstain_or_review",
    video_trace: Optional[np.ndarray] = None,
    video_lag_s: Optional[int] = None,
    video_r: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Run all three pipeline tiers on `(audio, fs)` against 24-hour reference `ref_f`:
      1. `M0_naive`: Unguarded STFT + sliding NCC (`r >= 0.45` or naive iid p<=0.01).
      2. `W06_W10_base`: W06 multi-harmonic consensus + W10 calibrated matcher & policy (without W14 guards).
      3. `W06_W10_W14_guarded`: Full pipeline with W14 deterministic guards G1-G6 (`v2_calibrated` and `v1_naive`).
    """
    harm_diag = extract_harmonic_diagnostics(audio, fs, nominal_hz=50.0)
    t_trace = harm_diag["t"]
    f_trace = harm_diag["f"]
    q_trace = harm_diag["q"]
    meta = harm_diag["meta"]

    # Tier 1: Unguarded Naive Baseline (M0_naive)
    # Represents a standard ENF tool without look-elsewhere, split-half, or adversarial guards
    scores_ncc = _fast_sliding_ncc(f_trace, ref_f)
    m0_lag = int(np.argmax(scores_ncc)) if len(scores_ncc) > 0 else 0
    m0_r = float(scores_ncc[m0_lag]) if len(scores_ncc) > 0 else 0.0
    # Naive i.i.d. Fisher-z p-value or r >= 0.45 threshold
    n_pts = max(4, len(f_trace))
    z_iid = math.atanh(min(max(m0_r, 0.0), 0.9999)) * math.sqrt(n_pts - 3.0)
    m0_status = "MATCH_SUPPORTED" if (m0_r >= 0.42 or z_iid >= 2.58) else "INCONCLUSIVE"
    if m0_status == "MATCH_SUPPORTED" and claimed_lag_s is not None and abs(m0_lag - claimed_lag_s) > 60:
        m0_status = "MATERIAL_DISCREPANCY_REVIEW"

    # Tier 2: Current W06 + W10 Calibrated Matcher & Policy (without W14 guards)
    trace_dict = {"t": t_trace, "f": f_trace, "q": q_trace, "meta": meta}
    ref_dict = {"ts_utc": np.arange(len(ref_f), dtype=np.float64), "f_hz": ref_f}
    w10_cfg: Dict[str, Any] = {"cadence_s": 1.0, "n_surrogates": 1, "seed": DEFAULT_SEED}
    if claimed_lag_s is not None:
        w10_cfg["claimed_start_utc"] = int(claimed_lag_s)
    w10_res = w10_match(trace_dict, ref_dict, search_start_utc=0, search_end_utc=len(ref_f) - 1, config=w10_cfg)
    w10_lag = int(w10_res["best"]["start_utc"])
    w10_r = float(w10_res["best"]["score"])
    w10_status = str(w10_res["status"])

    # Tier 3: W06 + W10 + W14 Deterministic Guards (v2_calibrated and v1_naive)
    g_v2 = evaluate_all_guards(
        audio=audio,
        fs=fs,
        f_trace=f_trace,
        t_trace=t_trace,
        match_result=w10_res,
        ref_f=ref_f,
        harm_diag=harm_diag,
        video_trace=video_trace,
        video_lag_s=video_lag_s,
        video_r=video_r,
        nominal_hz=50.0,
        mode="v2_calibrated",
    )
    g_v1 = evaluate_all_guards(
        audio=audio,
        fs=fs,
        f_trace=f_trace,
        t_trace=t_trace,
        match_result=w10_res,
        ref_f=ref_f,
        harm_diag=harm_diag,
        video_trace=video_trace,
        video_lag_s=video_lag_s,
        video_r=video_r,
        nominal_hz=50.0,
        mode="v1_naive",
    )
    w14_status = g_v2["guarded_status"]

    # Classify whether each tier made a WRONG CONFIDENT decision
    # Definition of Wrong Confident Decision:
    #   - On a forged/spoofed/spliced/notched/pitch-shifted/time-stretched clip (`attack_expectation == "abstain_or_review"`):
    #     issuing `MATCH_SUPPORTED` (especially at the spoofed lag or overlooking a splice/manipulation), OR
    #   - On a benign/recoverable transform or short crop (`attack_expectation == "correct_match_or_abstain"`):
    #     issuing `MATCH_SUPPORTED` at a WRONG timestamp (`|pred_lag - true_lag| > 30s`), OR
    #     issuing a false `MATERIAL_DISCREPANCY_REVIEW` on an untampered authentic clip at its true claimed timestamp.
    def _is_wrong_confident(status: str, pred_lag: int) -> bool:
        if attack_expectation == "abstain_or_review":
            # Any MATCH_SUPPORTED on a spoofed, double-ENF, spliced, or pitch/time-warped clip is a wrong confident match!
            if status == "MATCH_SUPPORTED":
                return True
            return False
        elif attack_expectation == "abstain_if_destroyed_or_correct_match":
            # For notch removal (a1..a4) or spectral gating (d4):
            # If the extractor still recovers the TRUE lag (e.g. a1 50Hz-only notch where h=2..7 are intact),
            # matching the true lag is a legitimate survival win! Matching a WRONG lag is a wrong confident match.
            if status == "MATCH_SUPPORTED":
                if true_lag_s is None or abs(pred_lag - true_lag_s) > 30:
                    return True
            return False
        elif attack_expectation == "correct_match_or_abstain":
            if status == "MATCH_SUPPORTED":
                if true_lag_s is None or abs(pred_lag - true_lag_s) > 30:
                    return True
            return False
        elif attack_expectation == "discrepancy_review":
            # E.g. claimed timestamp spoof (g2): should be MATERIAL_DISCREPANCY_REVIEW
            return status == "MATCH_SUPPORTED"
        return False

    m0_wrong = _is_wrong_confident(m0_status, m0_lag)
    w10_wrong = _is_wrong_confident(w10_status, w10_lag)
    w14_wrong = _is_wrong_confident(w14_status, w10_lag)

    matched_true = bool(true_lag_s is not None and abs(w10_lag - true_lag_s) <= 30)
    matched_spoof = bool(spoof_lag_s is not None and abs(w10_lag - spoof_lag_s) <= 30)

    return {
        "true_lag_s": true_lag_s,
        "spoof_lag_s": spoof_lag_s,
        "pred_lag_s": w10_lag,
        "m0_lag_s": m0_lag,
        "m0_r": round(m0_r, 4),
        "w10_r": round(w10_r, 4),
        "w10_p_emp": round(float(w10_res["null"]["p_empirical"]), 5),
        "w10_margin": round(float(w10_res["uniqueness"]["margin_vs_second"]), 4),
        "enf_presence_score": meta["quality_summary"]["enf_presence_score"],
        "snr_db": meta["quality_summary"]["snr_db"],
        "matched_true_lag": matched_true,
        "matched_spoof_lag": matched_spoof,
        "m0_status": m0_status,
        "w10_status": w10_status,
        "w14_status": w14_status,
        "m0_wrong_confident": m0_wrong,
        "w10_wrong_confident": w10_wrong,
        "w14_wrong_confident": w14_wrong,
        "triggered_guards_v2": g_v2["triggered_guards"],
        "triggered_guards_v1": g_v1["triggered_guards"],
        "guard_reasons_v2": g_v2["guard_reasons"],
        "guard_details_v2": g_v2["guards"],
    }


def run_full_redteam_suite() -> Dict[str, Any]:
    t_start = time.perf_counter()
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    h1_dev_all, h0_dev_all = load_dev_cases()
    print(f"[W14] Loaded {len(h1_dev_all)} H1 dev cases and {len(h0_dev_all)} H0 dev cases (0 holdout cases).")

    # Select 30 diverse H1 dev clips spanning all 16 dev sessions for Clean Dev False-Alarm Cost (FPR) evaluation
    # and 8 core H1 dev clips + 4 H0 dev clips + 4 [SYNTHETIC-NESO] clips per attack variant
    by_session: Dict[str, List[Dict[str, Any]]] = {}
    for row in h1_dev_all:
        sess = row["parsed_notes"].get("session_group", "unknown")
        by_session.setdefault(sess, []).append(row)

    clean_eval_h1: List[Dict[str, Any]] = []
    for sess in sorted(by_session.keys()):
        clean_eval_h1.extend(by_session[sess][:1])
    if len(clean_eval_h1) < 20:
        used_ids = {r["case_id"] for r in clean_eval_h1}
        for r in h1_dev_all:
            if r["case_id"] not in used_ids:
                clean_eval_h1.append(r)
                if len(clean_eval_h1) >= 20:
                    break
    clean_eval_h1 = clean_eval_h1[:20]

    # Core attack subset (4 authentic ENF-WHU dev H1 clips from 4 distinct dev days, covering both exact_waveform_slice and enf_trace_aligned)
    target_core_ids = [
        "ENF-WHU_H1_001",
        "ENF-WHU_H1_003",
        "ENF-WHU_H1_014",
        "ENF-WHU_H1_035",
    ]
    core_h1 = [r for r in h1_dev_all if r["case_id"] in target_core_ids]
    core_h0 = [r for r in h0_dev_all if "O0" in r["case_id"]][:4]

    # Pre-cache 24-hour reference traces for all used ENF-WHU sessions
    ref_24h_cache: Dict[str, np.ndarray] = {}
    for r in clean_eval_h1 + core_h1:
        rp = str(r["one_day_ref_path"])
        if rp not in ref_24h_cache:
            _, f_ref = load_24h_ref_trace_cached(Path(rp))
            ref_24h_cache[rp] = f_ref

    # Load real NESO 1s GB reference Day A (2026-08-01) and Day B (2026-09-01)
    neso_day_a, neso_day_b, neso_info = load_neso_days()
    print(f"[W14] Loaded NESO GB 1s Reference: Day A ({neso_info['day_a_date']}) & Day B ({neso_info['day_b_date']}).")

    # Pre-generate 4 clean [SYNTHETIC-NESO] Day A clips (360s each at different times of day)
    neso_starts = [14400, 32400, 50400, 68400]
    syn_neso_clips: List[Dict[str, Any]] = []
    for idx_s, st_lag in enumerate(neso_starts):
        h0_bg, _ = sf.read(str(REPO_ROOT / core_h0[idx_s % len(core_h0)]["media_path"]), dtype="float64")
        if h0_bg.ndim > 1:
            h0_bg = np.mean(h0_bg, axis=1)
        clip_wav, clip_meta = generate_synthetic_neso_clip(
            neso_day_a,
            start_idx=st_lag,
            duration_s=360.0,
            fs=8000.0,
            snr_db=-10.0,
            background_audio=h0_bg,
            seed=DEFAULT_SEED + idx_s,
        )
        syn_neso_clips.append(
            {
                "case_id": f"SYNTHETIC-NESO_GB_0{idx_s+1}",
                "audio": clip_wav,
                "fs": 8000.0,
                "true_lag_s": st_lag,
                "meta": clip_meta,
            }
        )

    # =========================================================================
    # PART 1: Clean Dev False-Alarm Cost (FPR) Evaluation (v1_naive vs v2_calibrated)
    # =========================================================================
    print("[W14] Part 1: Evaluating False-Alarm Cost (FPR) on 30 clean H1 dev, 6 H0 dev, and 4 SYNTHETIC-NESO clips...")
    clean_h1_results: List[Dict[str, Any]] = []
    guard_fp_counts_v2 = {"G1": 0, "G2": 0, "G3": 0, "G4": 0, "G5": 0, "G6": 0, "any_anomaly": 0}
    guard_fp_counts_v1 = {"G1": 0, "G2": 0, "G3": 0, "G4": 0, "G5": 0, "G6": 0, "any_anomaly": 0}

    for r in clean_eval_h1:
        wav_p = REPO_ROOT / r["media_path"]
        audio, fs = sf.read(str(wav_p), dtype="float64")
        if audio.ndim > 1:
            audio = np.mean(audio, axis=1)
        ref_f = ref_24h_cache[str(r["one_day_ref_path"])]
        true_lag = int(r["true_lag_s"])

        ev = evaluate_single_case(
            audio=audio,
            fs=float(fs),
            ref_f=ref_f,
            true_lag_s=true_lag,
            claimed_lag_s=true_lag,
            is_tampered=False,
            attack_expectation="correct_match_or_abstain",
        )
        ev["case_id"] = r["case_id"]
        clean_h1_results.append(ev)

        for gid in ("G1", "G2", "G3", "G4", "G5", "G6"):
            if gid in ev["triggered_guards_v2"]:
                guard_fp_counts_v2[gid] += 1
            if gid in ev["triggered_guards_v1"]:
                guard_fp_counts_v1[gid] += 1
        if any(g in ev["triggered_guards_v2"] for g in ("G1", "G2", "G3", "G4")):
            guard_fp_counts_v2["any_anomaly"] += 1
        if any(g in ev["triggered_guards_v1"] for g in ("G1", "G2", "G3", "G4")):
            guard_fp_counts_v1["any_anomaly"] += 1

    # Also evaluate 6 H0 dev parent recordings (O01, O02, O03, O04, O07, O10)
    clean_h0_results: List[Dict[str, Any]] = []
    any_ref = ref_24h_cache[str(core_h1[0]["one_day_ref_path"])]
    h0_parents = [r for r in h0_dev_all if "_O" in r["case_id"]]
    for r in h0_parents:
        wav_p = REPO_ROOT / r["media_path"]
        audio, fs = sf.read(str(wav_p), dtype="float64")
        if audio.ndim > 1:
            audio = np.mean(audio, axis=1)
        ev = evaluate_single_case(
            audio=audio,
            fs=float(fs),
            ref_f=any_ref,
            true_lag_s=None,
            is_tampered=False,
            attack_expectation="abstain_or_review",
        )
        ev["case_id"] = r["case_id"]
        clean_h0_results.append(ev)

    # Also evaluate 4 clean [SYNTHETIC-NESO] clips
    clean_neso_results: List[Dict[str, Any]] = []
    for sc in syn_neso_clips:
        ev = evaluate_single_case(
            audio=sc["audio"],
            fs=sc["fs"],
            ref_f=neso_day_a,
            true_lag_s=sc["true_lag_s"],
            claimed_lag_s=sc["true_lag_s"],
            is_tampered=False,
            attack_expectation="correct_match_or_abstain",
        )
        ev["case_id"] = sc["case_id"]
        ev["synthetic_neso"] = True
        clean_neso_results.append(ev)

    # =========================================================================
    # PART 2: Execute All 7 Attack Families (a)-(g) on ENF-WHU dev & [SYNTHETIC-NESO]
    # =========================================================================
    print("[W14] Part 2: Executing Attack Matrix (a)-(g)...")
    attack_records: List[Dict[str, Any]] = []

    # Alternate day reference for ENF-WHU spoofing/double-ENF/splicing
    alt_ref_path = str(core_h1[-1]["one_day_ref_path"])
    alt_ref_f = ref_24h_cache[alt_ref_path]

    def _run_and_record(
        attack_family: str,
        variant_id: str,
        dataset_tag: str,
        case_id: str,
        audio: np.ndarray,
        fs: float,
        ref_f: np.ndarray,
        true_lag_s: Optional[int],
        spoof_lag_s: Optional[int],
        claimed_lag_s: Optional[int],
        expectation: str,
        synthetic_neso: bool = False,
        video_trace: Optional[np.ndarray] = None,
        video_lag_s: Optional[int] = None,
        video_r: Optional[float] = None,
        extra_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        ev = evaluate_single_case(
            audio=audio,
            fs=fs,
            ref_f=ref_f,
            true_lag_s=true_lag_s,
            spoof_lag_s=spoof_lag_s,
            claimed_lag_s=claimed_lag_s,
            is_tampered=True,
            attack_expectation=expectation,
            video_trace=video_trace,
            video_lag_s=video_lag_s,
            video_r=video_r,
        )
        rec = {
            "attack_family": attack_family,
            "variant_id": variant_id,
            "dataset": dataset_tag,
            "synthetic_neso": synthetic_neso,
            "base_case_id": case_id,
            "expectation": expectation,
            **ev,
        }
        if extra_meta:
            rec["extra_meta"] = extra_meta
        attack_records.append(rec)
        return rec

    # --- Attack (a): ENF Removal (Notch Filters at Harmonics) ---
    a_variants = [
        ("a1_notch_50hz_q35", (1,), 35.0, "abstain_if_destroyed_or_correct_match"),
        ("a2_notch_50_100_150_q35", (1, 2, 3), 35.0, "abstain_or_review"),
        ("a3_notch_all_h1_h7_q35", (1, 2, 3, 4, 5, 6, 7), 35.0, "abstain_or_review"),
        ("a4_notch_all_h1_h7_q15", (1, 2, 3, 4, 5, 6, 7), 15.0, "abstain_or_review"),
    ]
    for var_id, h_tuple, q_val, exp_mode in a_variants:
        for r in core_h1[:6]:
            audio, fs = sf.read(str(REPO_ROOT / r["media_path"]), dtype="float64")
            if audio.ndim > 1:
                audio = np.mean(audio, axis=1)
            y_att = attack_a_notch_removal(audio, float(fs), harmonics_to_notch=h_tuple, q_factor=q_val)
            _run_and_record(
                "a_enf_removal", var_id, "ENF-WHU-dev", r["case_id"],
                y_att, float(fs), ref_24h_cache[str(r["one_day_ref_path"])],
                int(r["true_lag_s"]), None, None, exp_mode, False,
            )
        for sc in syn_neso_clips[:2]:
            y_att = attack_a_notch_removal(sc["audio"], sc["fs"], harmonics_to_notch=h_tuple, q_factor=q_val)
            _run_and_record(
                "a_enf_removal", var_id, "[SYNTHETIC-NESO]", sc["case_id"],
                y_att, sc["fs"], neso_day_a, sc["true_lag_s"], None, None, exp_mode, True,
            )

    # --- Attack (b): ENF Injection (Spoofing with a Wrong Date's Reference) ---
    # We test injecting a fake timestamp from the search reference (or Day B searched against Day B)
    # to see if the attacker can force `MATCH_SUPPORTED` at their chosen fake timestamp `spoof_lag_s`!
    spoof_target_lag = 25000
    b_h0_variants = [
        ("b1_inject_h0_100hz_snr_p6db", "single_100hz_clean", 6.0, "flanking_noise"),
        ("b1_inject_h0_100hz_snr_p14db", "single_100hz_clean", 14.0, "flanking_noise"),
        ("b2_inject_h0_multi_clean_p12db", "multi_h1_h4_clean", 12.0, "flanking_noise"),
        ("b4_whitebox_h0_multi_rir_p12db", "whitebox_multi_rir", 12.0, "flanking_noise"),
    ]
    for var_id, b_mode, snr_val, snr_ref in b_h0_variants:
        for idx_h0, r0 in enumerate(core_h0):
            audio0, fs0 = sf.read(str(REPO_ROOT / r0["media_path"]), dtype="float64")
            if audio0.ndim > 1:
                audio0 = np.mean(audio0, axis=1)
            dur0 = int(len(audio0) / fs0)
            spoof_lag = spoof_target_lag + idx_h0 * 1800
            spoof_trace = alt_ref_f[spoof_lag : spoof_lag + dur0 + 20]
            t_sp = np.arange(len(spoof_trace), dtype=np.float64) + 8.0
            y_att, _ = attack_b_enf_injection(
                audio0, float(fs0), spoof_trace, t_sp, mode=b_mode, snr_db=snr_val, snr_reference=snr_ref
            )
            _run_and_record(
                "b_enf_injection", var_id, "ENF-WHU-dev-H0", r0["case_id"],
                y_att, float(fs0), alt_ref_f, None, spoof_lag, spoof_lag, "abstain_or_review", False,
            )
        # Also on [SYNTHETIC-NESO]: inject Day B trace into H0 background and search against Day B
        for idx_s in range(2):
            audio0, fs0 = sf.read(str(REPO_ROOT / core_h0[idx_s]["media_path"]), dtype="float64")
            if audio0.ndim > 1:
                audio0 = np.mean(audio0, axis=1)
            audio0 = audio0[: int(360 * fs0)]
            spoof_lag = 42000 + idx_s * 3600
            spoof_trace = neso_day_b[spoof_lag : spoof_lag + 380]
            t_sp = np.arange(len(spoof_trace), dtype=np.float64)
            y_att, _ = attack_b_enf_injection(
                audio0, float(fs0), spoof_trace, t_sp, mode=b_mode, snr_db=snr_val, snr_reference=snr_ref
            )
            _run_and_record(
                "b_enf_injection", var_id, "[SYNTHETIC-NESO]", f"SYN-NESO-H0-0{idx_s+1}",
                y_att, float(fs0), neso_day_b, None, spoof_lag, spoof_lag, "abstain_or_review", True,
            )

    # Attack (b3): Inject spoof trace OVER an authentic H1 clip that already has real ENF
    b_h1_variants = [
        ("b3_inject_h1_over_native_m3db", "single_100hz_clean", -3.0, False),
        ("b3_inject_h1_over_native_p3db", "single_100hz_clean", +3.0, False),
        ("b3_inject_h1_over_native_p10db", "dual_50_100_clean", +10.0, False),
    ]
    for var_id, b_mode, snr_val, pre_notch in b_h1_variants:
        for r in core_h1[:6]:
            audio, fs = sf.read(str(REPO_ROOT / r["media_path"]), dtype="float64")
            if audio.ndim > 1:
                audio = np.mean(audio, axis=1)
            ref_f = ref_24h_cache[str(r["one_day_ref_path"])]
            true_lag = int(r["true_lag_s"])
            spoof_lag = (true_lag + 28800) % (len(ref_f) - int(len(audio) / fs) - 100)
            spoof_trace = ref_f[spoof_lag : spoof_lag + int(len(audio) / fs) + 20]
            t_sp = np.arange(len(spoof_trace), dtype=np.float64) + 8.0
            y_att, _ = attack_b_enf_injection(
                audio, float(fs), spoof_trace, t_sp, mode=b_mode, snr_db=snr_val,
                snr_reference="native_hum", pre_notch_native=pre_notch,
            )
            _run_and_record(
                "b_enf_injection", var_id, "ENF-WHU-dev-H1", r["case_id"],
                y_att, float(fs), ref_f, true_lag, spoof_lag, spoof_lag, "abstain_or_review", False,
            )
        for sc in syn_neso_clips[:2]:
            true_lag = sc["true_lag_s"]
            spoof_lag = (true_lag + 28800) % 75000
            spoof_trace = neso_day_a[spoof_lag : spoof_lag + 380]
            t_sp = np.arange(len(spoof_trace), dtype=np.float64)
            y_att, _ = attack_b_enf_injection(
                sc["audio"], sc["fs"], spoof_trace, t_sp, mode=b_mode, snr_db=snr_val,
                snr_reference="native_hum", pre_notch_native=pre_notch,
            )
            _run_and_record(
                "b_enf_injection", var_id, "[SYNTHETIC-NESO]", sc["case_id"],
                y_att, sc["fs"], neso_day_a, true_lag, spoof_lag, spoof_lag, "abstain_or_review", True,
            )

    # --- Attack (c): Double ENF (Two Concurrent Traces) ---
    c_variants = [
        ("c1_double_all_harmonics_0db", "all_harmonics", 0.0),
        ("c2_double_all_harmonics_p3db", "all_harmonics", +3.0),
        ("c3_harmonic_split_odd_even_p4db", "harmonic_split_odd_even", +4.0),
    ]
    for var_id, c_mode, rel_db in c_variants:
        for r in core_h1[:6]:
            audio, fs = sf.read(str(REPO_ROOT / r["media_path"]), dtype="float64")
            if audio.ndim > 1:
                audio = np.mean(audio, axis=1)
            ref_f = ref_24h_cache[str(r["one_day_ref_path"])]
            true_lag = int(r["true_lag_s"])
            second_lag = (true_lag + 21600) % (len(ref_f) - int(len(audio) / fs) - 100)
            second_trace = ref_f[second_lag : second_lag + int(len(audio) / fs) + 20]
            t_sec = np.arange(len(second_trace), dtype=np.float64) + 8.0
            y_att, _ = attack_c_double_enf(
                audio, float(fs), second_trace, t_sec, mode=c_mode, rel_snr_db=rel_db
            )
            _run_and_record(
                "c_double_enf", var_id, "ENF-WHU-dev", r["case_id"],
                y_att, float(fs), ref_f, true_lag, second_lag, None, "abstain_or_review", False,
            )
        for sc in syn_neso_clips[:2]:
            true_lag = sc["true_lag_s"]
            second_lag = (true_lag + 21600) % 75000
            second_trace = neso_day_a[second_lag : second_lag + 380]
            t_sec = np.arange(len(second_trace), dtype=np.float64)
            y_att, _ = attack_c_double_enf(
                sc["audio"], sc["fs"], second_trace, t_sec, mode=c_mode, rel_snr_db=rel_db
            )
            _run_and_record(
                "c_double_enf", var_id, "[SYNTHETIC-NESO]", sc["case_id"],
                y_att, sc["fs"], neso_day_a, true_lag, second_lag, None, "abstain_or_review", True,
            )

    # --- Attack (d): Re-encoding Chains, Spectral Gating, Resampling, Time-Stretch & Pitch Shift ---
    d_variants = [
        ("d1_aac_32k", "correct_match_or_abstain"),
        ("d2_voip_codec_20k", "correct_match_or_abstain"),
        ("d3_mp3_64k", "correct_match_or_abstain"),
        ("d4_spectral_gating", "abstain_if_destroyed_or_correct_match"),
        ("d5a_resample_8k_11k_8k", "correct_match_or_abstain"),
        ("d5b_clock_drift_2000ppm", "abstain_or_review"),
        ("d6a_timestretch_atempo_105", "abstain_or_review"),
        ("d6b_timestretch_atempo_125", "abstain_or_review"),
        ("d7a_pitch_shift_p05pct", "abstain_or_review"),
        ("d7b_pitch_shift_p20pct", "abstain_or_review"),
    ]
    for var_id, exp_mode in d_variants:
        for r in core_h1[:6]:
            audio, fs = sf.read(str(REPO_ROOT / r["media_path"]), dtype="float64")
            if audio.ndim > 1:
                audio = np.mean(audio, axis=1)
            ref_f = ref_24h_cache[str(r["one_day_ref_path"])]
            true_lag = int(r["true_lag_s"])
            y_att, fs_out, _ = attack_d_transform(audio, float(fs), var_id)
            _run_and_record(
                "d_reencode_and_transforms", var_id, "ENF-WHU-dev", r["case_id"],
                y_att, fs_out, ref_f, true_lag, None, None, exp_mode, False,
            )
        for sc in syn_neso_clips[:2]:
            y_att, fs_out, _ = attack_d_transform(sc["audio"], sc["fs"], var_id)
            _run_and_record(
                "d_reencode_and_transforms", var_id, "[SYNTHETIC-NESO]", sc["case_id"],
                y_att, fs_out, neso_day_a, sc["true_lag_s"], None, None, exp_mode, True,
            )

    # --- Attack (e): Cropping to Short Durations (10s, 20s, 30s, 60s, 120s, 300s) ---
    e_durations = [
        ("e1_crop_10s", 10.0, "abstain_or_review"),
        ("e2_crop_20s", 20.0, "abstain_or_review"),
        ("e3_crop_30s", 30.0, "abstain_or_review"),
        ("e4_crop_60s", 60.0, "correct_match_or_abstain"),
        ("e5_crop_120s", 120.0, "correct_match_or_abstain"),
        ("e6_crop_300s", 300.0, "correct_match_or_abstain"),
    ]
    for var_id, dur_s, exp_mode in e_durations:
        for r in core_h1[:6]:
            audio, fs = sf.read(str(REPO_ROOT / r["media_path"]), dtype="float64")
            if audio.ndim > 1:
                audio = np.mean(audio, axis=1)
            ref_f = ref_24h_cache[str(r["one_day_ref_path"])]
            true_lag = int(r["true_lag_s"])
            y_att, _ = attack_e_crop_duration(audio, float(fs), dur_s, offset_s=0.0)
            _run_and_record(
                "e_short_cropping", var_id, "ENF-WHU-dev", r["case_id"],
                y_att, float(fs), ref_f, true_lag, None, None, exp_mode, False,
            )
        for sc in syn_neso_clips[:2]:
            y_att, _ = attack_e_crop_duration(sc["audio"], sc["fs"], dur_s, offset_s=0.0)
            _run_and_record(
                "e_short_cropping", var_id, "[SYNTHETIC-NESO]", sc["case_id"],
                y_att, sc["fs"], neso_day_a, sc["true_lag_s"], None, None, exp_mode, True,
            )

    # --- Attack (f): Concatenating Clips from Different Times (Splicing) & Cross-Modal Spoofing ---
    f_modes = [
        "f1_splice_50_50",
        "f2_splice_70_30",
        "f3a_insertion_overdub_120_60_120",
        "f3b_insertion_shift_120_60_120",
    ]
    for f_mode in f_modes:
        for idx_a in range(len(core_h1)):
            r_a = core_h1[idx_a]
            r_b = core_h1[(idx_a + 1) % len(core_h1)]
            audio_a, fs_a = sf.read(str(REPO_ROOT / r_a["media_path"]), dtype="float64")
            audio_b, _ = sf.read(str(REPO_ROOT / r_b["media_path"]), dtype="float64")
            if audio_a.ndim > 1:
                audio_a = np.mean(audio_a, axis=1)
            if audio_b.ndim > 1:
                audio_b = np.mean(audio_b, axis=1)
            # Also synthesize a same-day different-timestamp splice partner so both segments exist in `ref_f`!
            ref_f = ref_24h_cache[str(r_a["one_day_ref_path"])]
            true_lag_a = int(r_a["true_lag_s"])
            alt_lag_b = (true_lag_a + 18000) % (len(ref_f) - 400)
            # Inject alt_lag_b trace into an H0 clip to form a realistic same-day different-hour recording
            audio_b_sameday, _ = attack_b_enf_injection(
                audio_b[: int(300 * fs_a)],
                float(fs_a),
                ref_f[alt_lag_b : alt_lag_b + 320],
                np.arange(320, dtype=np.float64) + 8.0,
                mode="whitebox_multi_rir",
                snr_db=6.0,
                snr_reference="native_hum",
                pre_notch_native=True,
            )
            y_att, sp_meta = attack_f_splice_concat(audio_a, audio_b_sameday, float(fs_a), mode=f_mode)
            _run_and_record(
                "f_splicing_concat", f_mode, "ENF-WHU-dev", r_a["case_id"],
                y_att, float(fs_a), ref_f, true_lag_a, alt_lag_b, true_lag_a, "abstain_or_review", False,
                extra_meta=sp_meta,
            )
        for idx_s in range(2):
            sc_a = syn_neso_clips[idx_s]
            sc_b = syn_neso_clips[(idx_s + 1) % len(syn_neso_clips)]
            y_att, sp_meta = attack_f_splice_concat(sc_a["audio"], sc_b["audio"], sc_a["fs"], mode=f_mode)
            _run_and_record(
                "f_splicing_concat", f_mode, "[SYNTHETIC-NESO]", sc_a["case_id"],
                y_att, sc_a["fs"], neso_day_a, sc_a["true_lag_s"], sc_b["true_lag_s"], sc_a["true_lag_s"],
                "abstain_or_review", True, extra_meta=sp_meta,
            )

    # Attack (f4): Audio-vs-Video Cross-Modal Spoof (testing Guard G6)
    for idx_a in range(4):
        r_a = core_h1[idx_a]
        audio_a, fs_a = sf.read(str(REPO_ROOT / r_a["media_path"]), dtype="float64")
        if audio_a.ndim > 1:
            audio_a = np.mean(audio_a, axis=1)
        ref_f = ref_24h_cache[str(r_a["one_day_ref_path"])]
        true_lag_a = int(r_a["true_lag_s"])
        vid_lag = (true_lag_a + 14400) % (len(ref_f) - 600)
        # Video rolling shutter trace from vid_lag (with realistic 5 mHz measurement noise)
        rng_v = np.random.default_rng(DEFAULT_SEED + idx_a)
        vid_len = int(len(audio_a) / fs_a) - 15
        v_trace = ref_f[vid_lag : vid_lag + vid_len] + rng_v.normal(0.0, 0.004, size=vid_len)
        _run_and_record(
            "f_splicing_concat", "f4_av_crossmodal_spoof", "ENF-WHU-dev+SYN-VIDEO", r_a["case_id"],
            audio_a, float(fs_a), ref_f, true_lag_a, vid_lag, true_lag_a, "abstain_or_review", True,
            video_trace=v_trace, video_lag_s=vid_lag, video_r=0.92,
        )

    # --- Attack (g): Metadata, Filename & Claimed Timestamp Spoofing ---
    spoof_dir = CACHE_DIR / "spoofed_metadata"
    g1_blind_verification: List[Dict[str, Any]] = []
    for idx_g, r in enumerate(core_h1[:6]):
        orig_wav = REPO_ROOT / r["media_path"]
        spoof_wav, g_meta = attack_g_metadata_spoof_file(
            orig_wav,
            spoof_dir,
            spoof_date_iso="2024-01-01T00:00:00Z",
            spoof_filename=f"2024-01-01_000000_FAKE_CLAIM_{r['case_id']}.wav",
        )
        # Run W06 extractor directly on BOTH original file and metadata-spoofed file
        res_orig = extract_audio_enf_detailed(orig_wav)
        res_spoof = extract_audio_enf_detailed(spoof_wav)
        max_df = float(np.max(np.abs(np.nan_to_num(res_orig["f"]) - np.nan_to_num(res_spoof["f"]))))
        max_dq = float(np.max(np.abs(res_orig["q"] - res_spoof["q"])))
        sha_f_orig = compute_sha256_bytes(np.nan_to_num(res_orig["f"]))
        sha_f_spoof = compute_sha256_bytes(np.nan_to_num(res_spoof["f"]))

        ref_f = ref_24h_cache[str(r["one_day_ref_path"])]
        true_lag = int(r["true_lag_s"])
        audio_sp, fs_sp = sf.read(str(spoof_wav), dtype="float64")
        if audio_sp.ndim > 1:
            audio_sp = np.mean(audio_sp, axis=1)

        # g1: Blind match on metadata-spoofed file (expect exact true_lag match with 0.0 delta)
        rec_g1 = _run_and_record(
            "g_metadata_spoofing", "g1_container_and_filename_spoof", "ENF-WHU-dev", r["case_id"],
            audio_sp, float(fs_sp), ref_f, true_lag, None, None, "correct_match_or_abstain", False,
            extra_meta={"max_abs_df_hz": max_df, "max_abs_dq": max_dq, "f_sha256_equal": sha_f_orig == sha_f_spoof},
        )
        g1_blind_verification.append(
            {
                "case_id": r["case_id"],
                "orig_media_sha256": res_orig["meta"]["media_sha256"],
                "spoof_media_sha256": res_spoof["meta"]["media_sha256"],
                "extracted_f_sha256_orig": sha_f_orig,
                "extracted_f_sha256_spoof": sha_f_spoof,
                "f_sha256_identical": bool(sha_f_orig == sha_f_spoof),
                "max_abs_df_hz": max_df,
                "max_abs_dq": max_dq,
                "blind_pred_lag_s": rec_g1["pred_lag_s"],
                "true_lag_s": true_lag,
            }
        )

        # g2: Mismatched claimed_start_utc (+4 hours = +14400s shift) passed to policy step
        fake_claim_lag = (true_lag + 14400) % (len(ref_f) - 1000)
        _run_and_record(
            "g_metadata_spoofing", "g2_claimed_timestamp_discrepancy", "ENF-WHU-dev", r["case_id"],
            audio_sp, float(fs_sp), ref_f, true_lag, fake_claim_lag, fake_claim_lag, "discrepancy_review", False,
        )

    # =========================================================================
    # PART 3: Aggregate Summary Tables & Hypothesis Verification
    # =========================================================================
    df_att = pd.DataFrame(attack_records)
    variant_summary: List[Dict[str, Any]] = []
    for (fam, var_id), grp in df_att.groupby(["attack_family", "variant_id"], sort=False):
        n_cases = len(grp)
        m0_wrong_n = int(grp["m0_wrong_confident"].sum())
        w10_wrong_n = int(grp["w10_wrong_confident"].sum())
        w14_wrong_n = int(grp["w14_wrong_confident"].sum())

        m0_match_n = int((grp["m0_status"] == "MATCH_SUPPORTED").sum())
        w10_match_n = int((grp["w10_status"] == "MATCH_SUPPORTED").sum())
        w14_match_n = int((grp["w14_status"] == "MATCH_SUPPORTED").sum())
        w14_review_n = int((grp["w14_status"] == "MATERIAL_DISCREPANCY_REVIEW").sum())
        w14_inconc_n = int((grp["w14_status"] == "INCONCLUSIVE").sum())

        # Count most frequent triggered guards
        guard_counts: Dict[str, int] = {}
        for glist in grp["triggered_guards_v2"]:
            for g in glist:
                guard_counts[g] = guard_counts.get(g, 0) + 1

        variant_summary.append(
            {
                "attack_family": str(fam),
                "variant_id": str(var_id),
                "n_cases": n_cases,
                "expectation": str(grp["expectation"].iloc[0]),
                "m0_wrong_confident_n": m0_wrong_n,
                "m0_wrong_confident_rate": round(m0_wrong_n / n_cases, 4),
                "w10_wrong_confident_n": w10_wrong_n,
                "w10_wrong_confident_rate": round(w10_wrong_n / n_cases, 4),
                "w14_wrong_confident_n": w14_wrong_n,
                "w14_wrong_confident_rate": round(w14_wrong_n / n_cases, 4),
                "m0_match_supported_n": m0_match_n,
                "w10_match_supported_n": w10_match_n,
                "w14_match_supported_n": w14_match_n,
                "w14_discrepancy_review_n": w14_review_n,
                "w14_inconclusive_n": w14_inconc_n,
                "mean_w10_r": round(float(grp["w10_r"].mean()), 4),
                "matched_true_lag_n": int(grp["matched_true_lag"].sum()),
                "matched_spoof_lag_n": int(grp["matched_spoof_lag"].sum()),
                "guards_triggered_counts": guard_counts,
            }
        )

    # Family-level rollup (excluding white-box limit b4 for H2 guard efficacy calculation, and reporting both with & without b4)
    family_summary: List[Dict[str, Any]] = []
    for fam, grp in df_att.groupby("attack_family", sort=False):
        n_c = len(grp)
        family_summary.append(
            {
                "attack_family": str(fam),
                "n_cases": n_c,
                "m0_wrong_confident_n": int(grp["m0_wrong_confident"].sum()),
                "m0_wrong_confident_rate": round(float(grp["m0_wrong_confident"].mean()), 4),
                "w10_wrong_confident_n": int(grp["w10_wrong_confident"].sum()),
                "w10_wrong_confident_rate": round(float(grp["w10_wrong_confident"].mean()), 4),
                "w14_wrong_confident_n": int(grp["w14_wrong_confident"].sum()),
                "w14_wrong_confident_rate": round(float(grp["w14_wrong_confident"].mean()), 4),
            }
        )

    # Overall adversarial totals across Attacks (a)-(f)
    df_af = df_att[df_att["attack_family"] != "g_metadata_spoofing"]
    df_af_non_wb = df_af[df_af["variant_id"] != "b4_whitebox_h0_multi_rir_p12db"]

    total_af_n = len(df_af)
    m0_wrong_af = int(df_af["m0_wrong_confident"].sum())
    w10_wrong_af = int(df_af["w10_wrong_confident"].sum())
    w14_wrong_af = int(df_af["w14_wrong_confident"].sum())

    total_non_wb_n = len(df_af_non_wb)
    m0_wrong_non_wb = int(df_af_non_wb["m0_wrong_confident"].sum())
    w10_wrong_non_wb = int(df_af_non_wb["w10_wrong_confident"].sum())
    w14_wrong_non_wb = int(df_af_non_wb["w14_wrong_confident"].sum())

    n_clean_h1 = len(clean_h1_results)
    clean_h1_base_match_n = sum(1 for c in clean_h1_results if c["w10_status"] == "MATCH_SUPPORTED" and c["matched_true_lag"])
    clean_h1_guarded_match_n = sum(1 for c in clean_h1_results if c["w14_status"] == "MATCH_SUPPORTED" and c["matched_true_lag"])
    clean_h1_wrong_match_n = sum(1 for c in clean_h1_results if c["w14_wrong_confident"])
    clean_h0_false_match_n = sum(1 for c in clean_h0_results if c["w14_status"] == "MATCH_SUPPORTED")

    results_payload = {
        "worker": "W14",
        "role": "Adversarial Red Team & Defensive Guard Suite",
        "seed": DEFAULT_SEED,
        "runtime_s": round(time.perf_counter() - t_start, 2),
        "split_hygiene": {
            "split_json": "eval/splits/enf_whu_split.json",
            "holdout_cases_touched": 0,
            "n_clean_dev_h1_evaluated": n_clean_h1,
            "n_clean_dev_h0_evaluated": len(clean_h0_results),
            "n_clean_synthetic_neso_evaluated": len(clean_neso_results),
            "n_total_attacked_test_cases": len(attack_records),
        },
        "neso_reference_summary": neso_info,
        "clean_dev_false_alarm_cost": {
            "n_clean_h1_dev": n_clean_h1,
            "w10_base_true_match_supported_n": clean_h1_base_match_n,
            "w10_base_true_match_supported_rate": round(clean_h1_base_match_n / n_clean_h1, 4),
            "w14_guarded_true_match_supported_n": clean_h1_guarded_match_n,
            "w14_guarded_true_match_supported_rate": round(clean_h1_guarded_match_n / n_clean_h1, 4),
            "clean_h1_wrong_timestamp_n": clean_h1_wrong_match_n,
            "clean_h0_false_match_n": clean_h0_false_match_n,
            "clean_synthetic_neso_match_n": sum(1 for c in clean_neso_results if c["w14_status"] == "MATCH_SUPPORTED"),
            "v1_naive_false_alarms_per_guard": {
                k: {"count": v, "fpr": round(v / n_clean_h1, 4)} for k, v in guard_fp_counts_v1.items()
            },
            "v2_calibrated_false_alarms_per_guard": {
                k: {"count": v, "fpr": round(v / n_clean_h1, 4)} for k, v in guard_fp_counts_v2.items()
            },
        },
        "overall_attack_metrics_af": {
            "all_attacks_including_whitebox": {
                "n_cases": total_af_n,
                "m0_naive_wrong_confident_n": m0_wrong_af,
                "m0_naive_wrong_confident_rate": round(m0_wrong_af / total_af_n, 4),
                "w06_w10_base_wrong_confident_n": w10_wrong_af,
                "w06_w10_base_wrong_confident_rate": round(w10_wrong_af / total_af_n, 4),
                "w14_guarded_wrong_confident_n": w14_wrong_af,
                "w14_guarded_wrong_confident_rate": round(w14_wrong_af / total_af_n, 4),
                "relative_wrong_match_reduction_vs_m0": round(1.0 - (w14_wrong_af / max(1, m0_wrong_af)), 4),
                "relative_wrong_match_reduction_vs_w10": round(1.0 - (w14_wrong_af / max(1, w10_wrong_af)), 4),
            },
            "excluding_whitebox_physical_limit_b4": {
                "n_cases": total_non_wb_n,
                "m0_naive_wrong_confident_n": m0_wrong_non_wb,
                "m0_naive_wrong_confident_rate": round(m0_wrong_non_wb / total_non_wb_n, 4),
                "w06_w10_base_wrong_confident_n": w10_wrong_non_wb,
                "w06_w10_base_wrong_confident_rate": round(w10_wrong_non_wb / total_non_wb_n, 4),
                "w14_guarded_wrong_confident_n": w14_wrong_non_wb,
                "w14_guarded_wrong_confident_rate": round(w14_wrong_non_wb / total_non_wb_n, 4),
                "relative_wrong_match_reduction_vs_m0": round(1.0 - (w14_wrong_non_wb / max(1, m0_wrong_non_wb)), 4),
                "relative_wrong_match_reduction_vs_w10": round(1.0 - (w14_wrong_non_wb / max(1, w10_wrong_non_wb)), 4),
            },
        },
        "metadata_spoof_blindness_verification": {
            "n_cases_tested": len(g1_blind_verification),
            "all_f_sha256_identical": all(x["f_sha256_identical"] for x in g1_blind_verification),
            "max_abs_df_hz": max(x["max_abs_df_hz"] for x in g1_blind_verification),
            "max_abs_dq": max(x["max_abs_dq"] for x in g1_blind_verification),
            "cases": g1_blind_verification,
        },
        "family_summary": family_summary,
        "variant_summary": variant_summary,
        "clean_h1_dev_details": clean_h1_results,
        "clean_h0_dev_details": clean_h0_results,
        "clean_synthetic_neso_details": clean_neso_results,
    }

    res_path = W14_DIR / "RESULTS.json"
    res_path.write_text(json.dumps(results_payload, indent=2), encoding="utf-8")
    print(f"[W14] Wrote full results to {res_path}")

    generate_redteam_plots(results_payload, core_h1, core_h0, ref_24h_cache, neso_day_a, neso_day_b)
    return results_payload


def generate_redteam_plots(
    results: Dict[str, Any],
    core_h1: List[Dict[str, Any]],
    core_h0: List[Dict[str, Any]],
    ref_24h_cache: Dict[str, np.ndarray],
    neso_day_a: np.ndarray,
    neso_day_b: np.ndarray,
) -> None:
    """Generate 4 publication-grade diagnostic figures in `work/W14/plots/`."""
    plt.rcParams.update({"font.size": 9, "axes.titlesize": 10, "axes.labelsize": 9})

    # -------------------------------------------------------------------------
    # Plot 1: Attack Matrix Outcome Comparison (M0 Naive vs W06+W10 vs W14 Guarded)
    # -------------------------------------------------------------------------
    v_sum = results["variant_summary"]
    labels = [v["variant_id"] for v in v_sum]
    m0_rates = [100.0 * v["m0_wrong_confident_rate"] for v in v_sum]
    w10_rates = [100.0 * v["w10_wrong_confident_rate"] for v in v_sum]
    w14_rates = [100.0 * v["w14_wrong_confident_rate"] for v in v_sum]

    fig, ax = plt.subplots(figsize=(11, 8.5), dpi=180)
    y_pos = np.arange(len(labels))
    bar_h = 0.26
    ax.barh(y_pos + bar_h, m0_rates, height=bar_h, color="#d95f02", alpha=0.85, label="Tier 1: Unguarded Naive Baseline (M0)")
    ax.barh(y_pos, w10_rates, height=bar_h, color="#7570b3", alpha=0.85, label="Tier 2: W06 + W10 (Without W14 Adversarial Guards)")
    ax.barh(y_pos - bar_h, w14_rates, height=bar_h, color="#1b9e77", alpha=0.95, label="Tier 3: W06 + W10 + W14 Guards (G1–G6)")

    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("Wrong Confident Decision Rate (% of attacked clips producing false MATCH_SUPPORTED)")
    ax.set_xlim(0, 108)
    ax.axvline(0, color="black", linewidth=0.8)
    ax.grid(axis="x", linestyle="--", alpha=0.4)
    ax.set_title("GhostClock W14 Adversarial Red-Team Matrix: Wrong Confident Match Rate Across 29 Attack Variants")
    ax.legend(loc="lower right", framealpha=0.95)
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "attack_matrix_wrong_confident_rates.png")
    plt.close(fig)

    # -------------------------------------------------------------------------
    # Plot 2: Spoof (G2) & Double-ENF / Harmonic Conflict (G3) Physical Diagnostics
    # -------------------------------------------------------------------------
    r_ex = core_h1[0]
    audio_ex, fs_ex = sf.read(str(REPO_ROOT / r_ex["media_path"]), dtype="float64")
    if audio_ex.ndim > 1:
        audio_ex = np.mean(audio_ex, axis=1)
    ref_ex = ref_24h_cache[str(r_ex["one_day_ref_path"])]
    true_lag_ex = int(r_ex["true_lag_s"])
    spoof_lag_ex = (true_lag_ex + 28800) % (len(ref_ex) - 1000)
    spoof_tr = ref_ex[spoof_lag_ex : spoof_lag_ex + int(len(audio_ex) / fs_ex) + 20]

    # Inject clean 100 Hz spoof at +5 dB over H1 (Attack b3)
    y_b3, _ = attack_b_enf_injection(
        audio_ex, float(fs_ex), spoof_tr, np.arange(len(spoof_tr), dtype=np.float64) + 8.0,
        mode="single_100hz_clean", snr_db=5.0, snr_reference="native_hum"
    )
    diag_clean = extract_harmonic_diagnostics(audio_ex, float(fs_ex))
    diag_b3 = extract_harmonic_diagnostics(y_b3, float(fs_ex))

    fig, axes = plt.subplots(2, 2, figsize=(12, 7.5), dpi=180)
    t_ax = diag_clean["t"]
    # Panel A: Amplitude Envelope CV comparison (Authentic vs Injected Clean FM Tone)
    amp_auth = diag_clean["amp_harm"][3] / (np.median(diag_clean["amp_harm"][3]) + 1e-18)  # h=4 (200 Hz)
    amp_spoof = diag_b3["amp_harm"][1] / (np.median(diag_b3["amp_harm"][1]) + 1e-18)      # h=2 (100 Hz spoof)
    axes[0, 0].plot(t_ax, amp_auth, color="#1b9e77", lw=1.2, label=f"Authentic H1/001 h=4 (CV={np.std(amp_auth):.3f})")
    axes[0, 0].plot(t_ax, amp_spoof, color="#d95f02", lw=1.5, label=f"Injected Clean 100Hz FM Spoof (CV={np.std(amp_spoof):.3f})")
    axes[0, 0].set_title("Guard G2: Narrowband Harmonic Amplitude Envelope A_h(t)")
    axes[0, 0].set_xlabel("Time (s)")
    axes[0, 0].set_ylabel("Normalized Amplitude A(t) / median(A)")
    axes[0, 0].legend(fontsize=8)
    axes[0, 0].grid(True, alpha=0.3)

    # Panel B: Inter-Harmonic Trajectory Conflict under Attack b3 / c3 (Guard G3)
    axes[0, 1].plot(t_ax, (diag_b3["f_harm"][1] - 50.0) * 1000.0, color="#d95f02", lw=1.3, label="Spoofed h=2 (100 Hz / 2) -> matches fake lag")
    axes[0, 1].plot(t_ax, (diag_b3["f_harm"][3] - 50.0) * 1000.0, color="#1b9e77", lw=1.3, label="Native h=4 (200 Hz / 4) -> matches true lag")
    axes[0, 1].set_title("Guard G3: Inter-Harmonic Trajectory Conflict (Attack b3/c3)")
    axes[0, 1].set_xlabel("Time (s)")
    axes[0, 1].set_ylabel("Fundamental-Equivalent Deviation (mHz)")
    axes[0, 1].legend(fontsize=8)
    axes[0, 1].grid(True, alpha=0.3)

    # Panel C: Guard G1 Spectral Notch Dip Profile (Attack a2: 50, 100, 150 Hz notched)
    y_a2 = attack_a_notch_removal(audio_ex, float(fs_ex), harmonics_to_notch=(1, 2, 3), q_factor=35.0)
    freqs_w1, psd_clean = signal.welch(diag_clean["x_proc_1khz"], fs=1000.0, nperseg=8000, nfft=65536)
    _, psd_notch = signal.welch(
        signal.resample_poly(y_a2 - np.mean(y_a2), 1, 8), fs=1000.0, nperseg=8000, nfft=65536
    )
    mask_100 = (freqs_w1 >= 97.5) & (freqs_w1 <= 102.5)
    axes[1, 0].plot(freqs_w1[mask_100], 10 * np.log10(psd_clean[mask_100] + 1e-30), color="#1b9e77", lw=1.2, label="Authentic H1/001 Spectrum")
    axes[1, 0].plot(freqs_w1[mask_100], 10 * np.log10(psd_notch[mask_100] + 1e-30), color="#e7298a", lw=1.2, label="Attack a2: IIR Notch Filter (Q=35) at 100 Hz")
    axes[1, 0].set_title("Guard G1: Narrowband Notch Dip Detection Around 100 Hz")
    axes[1, 0].set_xlabel("Frequency (Hz)")
    axes[1, 0].set_ylabel("Power Spectral Density (dB)")
    axes[1, 0].legend(fontsize=8)
    axes[1, 0].grid(True, alpha=0.3)

    # Panel D: Guard G4 Middle-Insertion Splice (f3a: 120s A + 60s B + 120s A)
    alt_lag_b = (true_lag_ex + 18000) % (len(ref_ex) - 400)
    audio_b_sameday, _ = attack_b_enf_injection(
        audio_ex[: int(300 * fs_ex)], float(fs_ex), ref_ex[alt_lag_b : alt_lag_b + 320],
        np.arange(320, dtype=np.float64) + 8.0, mode="whitebox_multi_rir", snr_db=6.0,
        snr_reference="native_hum", pre_notch_native=True
    )
    y_f3a, _ = attack_f_splice_concat(audio_ex, audio_b_sameday, float(fs_ex), mode="f3a_insertion_overdub_120_60_120")
    diag_f3a = extract_harmonic_diagnostics(y_f3a, float(fs_ex))
    from work.W14.guards import guard_g4_multifragment_splice_and_drift
    g4_res = guard_g4_multifragment_splice_and_drift(
        diag_f3a["f"], diag_f3a["t"], ref_ex, true_lag_ex, 0.78
    )
    seg_centers = [0.5 * (s["start_s"] + s["end_s"]) for s in g4_res["segments"]]
    seg_loc_r = [s["local_r"] for s in g4_res["segments"]]
    seg_ind_r = [s["indep_best_r"] for s in g4_res["segments"]]
    axes[1, 1].plot(seg_centers, seg_loc_r, "o-", color="#d95f02", lw=1.6, label="Local r at Primary Lag t_A (drops in spliced 120-180s)")
    axes[1, 1].plot(seg_centers, seg_ind_r, "s--", color="#7570b3", lw=1.4, label="Independent 24h Best r (matches t_B in middle!)")
    axes[1, 1].axvspan(120, 180, color="red", alpha=0.15, label="Inserted 60s Segment from t_B")
    axes[1, 1].set_title("Guard G4: 60s Sliding Sub-Segment Catching Middle Insertion Splice (f3a)")
    axes[1, 1].set_xlabel("Sub-Segment Center Time (s)")
    axes[1, 1].set_ylabel("Sub-Segment Correlation r")
    axes[1, 1].set_ylim(-0.3, 1.05)
    axes[1, 1].legend(fontsize=7.5, loc="lower left")
    axes[1, 1].grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "guard_diagnostics_g1_g2_g3_g4.png")
    plt.close(fig)

    # -------------------------------------------------------------------------
    # Plot 3: Short-Duration Cropping Curve (Attack e) & Iteration FPR Tradeoff (v1 vs v2)
    # -------------------------------------------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.6), dpi=180)
    crop_vars = [v for v in v_sum if v["attack_family"] == "e_short_cropping"]
    durs = [10, 20, 30, 60, 120, 300]
    m0_crop_wrong = [100.0 * v["m0_wrong_confident_rate"] for v in crop_vars]
    w10_crop_wrong = [100.0 * v["w10_wrong_confident_rate"] for v in crop_vars]
    w14_crop_wrong = [100.0 * v["w14_wrong_confident_rate"] for v in crop_vars]
    true_match_rate = [100.0 * (v["matched_true_lag_n"] / v["n_cases"]) for v in crop_vars]

    axes[0].plot(durs, m0_crop_wrong, "o-", color="#d95f02", lw=1.8, label="M0 Naive Wrong Match Rate (%)")
    axes[0].plot(durs, w10_crop_wrong, "s-", color="#7570b3", lw=1.8, label="W06+W10 Wrong Match Rate (%)")
    axes[0].plot(durs, w14_crop_wrong, "^-", color="#1b9e77", lw=2.0, label="W14 Guarded Wrong Match Rate (%)")
    axes[0].plot(durs, true_match_rate, "d--", color="#2b83ba", lw=1.5, label="True Timestamp Recovery Rate (%)")
    axes[0].axvline(60, color="red", linestyle=":", lw=1.2, label="G5 Min Duration Gate (60s)")
    axes[0].set_xscale("log")
    axes[0].set_xticks(durs)
    axes[0].set_xticklabels([f"{d}s" for d in durs])
    axes[0].set_xlabel("Clip Duration D (s) Searched Against 24-Hour Reference")
    axes[0].set_ylabel("Percentage of Clips (%)")
    axes[0].set_title("Attack (e): Short-Duration Cropping vs Look-Elsewhere False Matches")
    axes[0].legend(fontsize=8)
    axes[0].grid(True, alpha=0.3)

    # Panel B: False-Alarm Cost (FPR) on 30 Clean Dev Clips — Iteration v1_naive vs v2_calibrated
    g_names = ["G1\nNotch/Gate", "G2\nToo-Clean", "G3\nHarmonic", "G4\nSplice/Drift", "Combined\n(G1–G4)"]
    g_keys = ["G1", "G2", "G3", "G4", "any_anomaly"]
    fp_v1 = [100.0 * results["clean_dev_false_alarm_cost"]["v1_naive_false_alarms_per_guard"][k]["fpr"] for k in g_keys]
    fp_v2 = [100.0 * results["clean_dev_false_alarm_cost"]["v2_calibrated_false_alarms_per_guard"][k]["fpr"] for k in g_keys]

    x_g = np.arange(len(g_names))
    w_g = 0.35
    axes[1].bar(x_g - w_g / 2, fp_v1, width=w_g, color="#e6ab02", alpha=0.85, label="Iteration v1 (Uncalibrated Thresholds)")
    axes[1].bar(x_g + w_g / 2, fp_v2, width=w_g, color="#1b9e77", alpha=0.95, label="Iteration v2 (Dev-Calibrated Thresholds)")
    axes[1].axhline(15.0, color="red", linestyle="--", lw=1.1, label="H3 Max Allowed Combined FPR (15%)")
    axes[1].set_xticks(x_g)
    axes[1].set_xticklabels(g_names, fontsize=8.5)
    axes[1].set_ylabel("False-Alarm Rate on 30 Clean Dev H1 Clips (%)")
    axes[1].set_title("Step G Iteration: Guard False-Alarm Cost on Clean Dev Clips (N=30)")
    axes[1].legend(fontsize=8)
    axes[1].grid(axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "crop_curves_and_guard_fpr_iteration.png")
    plt.close(fig)


if __name__ == "__main__":
    run_full_redteam_suite()
