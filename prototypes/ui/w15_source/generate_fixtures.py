"""Generate integration/interfaces.md v1 compatible JSON fixtures for GhostClock W15 prototypes.

All synthetic/illustrative fixtures are explicitly marked with provenance badges:
'ILLUSTRATIVE — SYNTHETIC FIXTURE (NO LIVE MEASUREMENT CLAIMED)'.
Also exports individual trace.json, reference.json, and match.json files so
W06/W07/W08/W10/W13 outputs can be swapped in directly.
"""
import json
import math
from pathlib import Path
import numpy as np


def generate_cases():
    rng = np.random.default_rng(20261108)
    out_dir = Path("work/W15/data")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Time vector: 60 seconds, 1s hop, 4s window
    t = np.arange(0, 60, 1, dtype=float)
    n = len(t)

    # Underlying realistic GB 50 Hz fluctuation profile (mHz variations around 50.000 Hz)
    base_dev = (
        0.042 * np.sin(2 * np.pi * t / 38.0 + 0.4)
        + 0.028 * np.cos(2 * np.pi * t / 17.0 - 0.8)
        - 0.019 * np.sin(2 * np.pi * t / 9.5 + 1.1)
        + 0.012 * np.linspace(-1.0, 1.3, n)
    )
    ref_f_case1 = np.round(50.0 + base_dev, 5)
    # Extracted trace after Attempt 2 (high quality audio + wall ballast harmonics)
    trace_f_case1 = np.round(ref_f_case1 + rng.normal(0.0, 0.0042, size=n), 5)
    trace_q_case1 = np.round(np.clip(0.86 + rng.normal(0.0, 0.05, size=n), 0.65, 0.98), 3)

    # Attempt 1 failed trace (inverter LED ceiling clip, mostly NaN / noisy)
    attempt1_f = np.round(50.0 + rng.normal(0.0, 0.048, size=n), 5)
    attempt1_q = np.round(np.clip(0.29 + rng.normal(0.0, 0.14, size=n), 0.05, 0.65), 3)

    # Landscape across 72 hours (sampled at 72 candidate timestamps for visual clarity + peak)
    # Claimed: 2026-10-14 21:15:00 UTC (1791993300)
    # True match: 2026-10-12 21:14:20 UTC (1791820460) -> 48.01 hours earlier!
    claimed_utc_1 = 1791993300
    best_utc_1 = 1791820460
    search_start_1 = 1791763200
    search_end_1 = 1792022400

    landscape_1 = []
    grid_ts = np.linspace(search_start_1, search_end_1, 90, dtype=int)
    for ts in grid_ts:
        score = float(np.clip(rng.normal(0.18, 0.09), -0.15, 0.42))
        landscape_1.append({"ts_utc": int(ts), "score": round(score, 4), "label": "background"})
    # Insert second-best peak and true best peak and claimed time marker
    landscape_1.append({"ts_utc": best_utc_1, "score": 0.914, "label": "best_peak"})
    landscape_1.append({"ts_utc": best_utc_1 + 38400, "score": 0.412, "label": "second_best"})
    landscape_1.append({"ts_utc": claimed_utc_1, "score": 0.118, "label": "claimed_time"})
    landscape_1.sort(key=lambda x: x["ts_utc"])

    case_1 = {
        "case_id": "GC-2026-8841",
        "title": "Case 1: Commercial Warehouse Escape-of-Water (Discrepancy + Argon Loop)",
        "scenario_type": "DISCREPANCY_LOOP",
        "data_provenance": "ILLUSTRATIVE — SYNTHETIC FIXTURE (NO LIVE MEASUREMENT CLAIMED)",
        "claim_context": {
            "claim_id": "CLM-UK-2026-8841 (Fictional Scenario)",
            "is_fictional_scenario": True,
            "named_user": "Senior SIU Investigator — Commercial Property Claims",
            "financial_decision": "Hold £24,500 emergency settlement payout & request original camera card before authorising strip-out works.",
            "policy_type": "Commercial Property — Escape of Water",
            "reserve_gbp": 24500,
            "claimed_start_utc": claimed_utc_1,
            "claimed_start_iso": "2026-10-14T21:15:00Z",
            "matched_start_iso": "2026-10-12T21:14:20Z",
            "search_window_utc": [search_start_1, search_end_1],
            "search_window_label": "72-hour window (2026-10-12 00:00Z to 2026-10-15 00:00Z)",
            "discrepancy_hours": -48.01,
            "narrative_summary": "Claimant submitted smartphone video allegedly showing a burst pipe flooding stock on Wed 14 Oct (24h after policy inception). Blinded ENF sequence matches NESO GB grid 48 hours earlier (Mon 12 Oct, prior to coverage)."
        },
        "intake": {
            "media_filename": "IMG_4912_warehouse_pipe.mp4",
            "media_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "probe": {
                "container": "MPEG-4 (ISO/IEC 14496-12)",
                "codec_video": "H.264 / AVC1 (High@L4.0)",
                "codec_audio": "AAC-LC (48,000 Hz, mono)",
                "duration_s": 60.0,
                "fps": 29.97,
                "is_vfr": False,
                "row_readout_us": 14.8,
                "audio_fs_hz": 48000,
                "resolution": "1920x1080"
            },
            "blinding": {
                "metadata_withheld": True,
                "stripped_fields": [
                    "QuickTime:CreateDate (2026-10-14T21:15:04Z)",
                    "File:ModifyDate",
                    "EXIF:GPSLatitude / GPSLongitude",
                    "Filename date tokens",
                    "Claimed loss timestamp (withheld until post-search gate)"
                ],
                "notice": "BLINDED ANALYSIS ACTIVE: Metadata withheld from analysis. Claimed timestamp excluded from ENF extraction and candidate search."
            }
        },
        "investigation_replay": [
            {
                "attempt_id": 1,
                "stage": "Proposal 1 (Visual ROI — Ceiling LED Strip)",
                "argon_hypothesis": "Argon inspects frame geometry and proposes rolling-shutter row-profile extraction on the bright overhead warehouse LED batten (ROI #1: rows 40–260) expecting 100 Hz flicker.",
                "tool_call": "analyse_video(path='IMG_4912.mp4', roi=[120,40,1680,260], nominal_hz=50)",
                "verifier_outcome": "REJECTED",
                "verifier_rule_triggered": "GATE_MIN_VALID_FRACTION (frac_valid = 0.31 < 0.60) & GATE_SNR_FLOOR (snr_db = -2.4 dB < 3.0 dB)",
                "verifier_reason": "Deterministic Verifier rejected Attempt 1: Overhead luminaire uses a high-frequency switched-mode DC driver + pixel saturation clipping (L > 252), destroying 100 Hz mains modulation.",
                "metrics": {"median_q": 0.29, "frac_valid": 0.31, "snr_db": -2.4},
                "failed_trace_f": attempt1_f.tolist(),
                "failed_trace_q": attempt1_q.tolist()
            },
            {
                "attempt_id": 2,
                "stage": "Revision 2 (Audio Multi-Harmonic 100/150/200 Hz + Wall Ballast ROI)",
                "argon_hypothesis": "Reacting to verifier rejection, Argon masks saturated ceiling rows and pivots to acoustic STFT multi-harmonic ridge tracking (100, 150, 200 Hz from circulation pump/transformer hum), cross-checked against unclipped matte wall illumination bounce (ROI #2: rows 420–880).",
                "tool_call": "analyse_audio(path='IMG_4912.mp4', harmonics=[100,150,200], window_s=4.0, hop_s=1.0)",
                "verifier_outcome": "ACCEPTED",
                "verifier_rule_triggered": "ALL_QUALITY_GATES_PASSED (frac_valid = 0.95 >= 0.60, snr_db = 14.2 dB >= 3.0 dB)",
                "verifier_reason": "Deterministic Verifier accepted Attempt 2: Clean harmonic sequence recovered across 57/60 windows. Proceeding to blinded NESO 1s grid correlation across 259,200 candidate seconds.",
                "metrics": {"median_q": 0.88, "frac_valid": 0.95, "snr_db": 14.2}
            }
        ],
        "trace": {
            "source": "audio",
            "method": "stft_multiharmonic_weighted_ridge_v1",
            "nominal_hz": 50,
            "harmonics_used": [100, 150, 200],
            "window_s": 4.0,
            "hop_s": 1.0,
            "fs_media": 48000.0,
            "duration_s": 60.0,
            "media_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "params": {"n_fft": 65536, "band_halfwidth_hz": 0.35, "harmonic_weights": [0.52, 0.31, 0.17]},
            "quality_summary": {"median_q": 0.88, "frac_valid": 0.95, "snr_db": 14.2},
            "provenance": {"code": "work/W06/extract.py", "version": "0.2.0-illustrative"},
            "t": t.tolist(),
            "f": trace_f_case1.tolist(),
            "q": trace_q_case1.tolist(),
            "visual_corroboration_note": "Visual ROI #2 (wall bounce) recovered r=0.81 agreement with audio ENF. Per Scientific Rule #3, audio & visual ENF sense the SAME electrical environment and are NOT multiplied as independent probabilities."
        },
        "reference": {
            "source": "NESO",
            "cadence_s": 1,
            "grid": "GB",
            "coverage": [search_start_1, search_end_1],
            "url": "https://api.neso.energy/dataset/system-frequency-data",
            "sha256": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
            "aligned_f": ref_f_case1.tolist()
        },
        "match": {
            "best": {
                "start_utc": best_utc_1,
                "score": 0.914,
                "rmse_mhz": 4.3,
                "offset_hz": -0.0004
            },
            "candidates": [
                {"rank": 1, "start_utc": best_utc_1, "iso": "2026-10-12T21:14:20Z", "score": 0.914, "rmse_mhz": 4.3, "offset_hz": -0.0004},
                {"rank": 2, "start_utc": best_utc_1 + 38400, "iso": "2026-10-13T07:54:20Z", "score": 0.412, "rmse_mhz": 24.8, "offset_hz": 0.0061},
                {"rank": 3, "start_utc": best_utc_1 + 114200, "iso": "2026-10-14T04:57:40Z", "score": 0.379, "rmse_mhz": 27.1, "offset_hz": -0.0089}
            ],
            "null": {
                "method": "block_permutation_ar1_calibrated",
                "n": 5000,
                "p_empirical": 0.0002,
                "score_threshold": 0.540
            },
            "uniqueness": {
                "margin_vs_second": 0.502,
                "second_best_distance_s": 38400
            },
            "diagnostics": {
                "effective_dof": 44.2,
                "claimed_time_score": 0.118,
                "claimed_time_rmse_mhz": 41.6,
                "sub_segment_consistency": "First half (0-30s) and second half (30-60s) independently peak within 1s of 2026-10-12T21:14:20Z."
            },
            "status": "MATERIAL_DISCREPANCY_REVIEW",
            "status_reasons": [
                "Blinded ENF match peak (r = 0.914, RMSE = 4.3 mHz) exceeds null threshold (0.540, p_empirical = 0.0002).",
                "Peak is unique across 72h search space (margin_vs_second = +0.502 over rank-2 candidate).",
                "Matched grid timestamp (2026-10-12 21:14:20 UTC) disagrees with claimant-stated loss time (2026-10-14 21:15:00 UTC) by -48.01 hours (pre-inception)."
            ],
            "what_would_change_this": [
                "Original unedited camera card / raw container showing continuous ENF alignment inside the claimed 2026-10-14 evening window (r >= 0.540).",
                "Verified documentation that the site was operating on an isolated islanded diesel generator or UPS inverter disconnected from the GB National Grid.",
                "Independent utility/smart-meter outage log or plumber attendance telemetry corroborating the 14 Oct timestamp."
            ],
            "landscape": landscape_1
        },
        "speed_check": {
            "estimated_carrier_hz": 50.001,
            "nominal_hz": 50.0,
            "speed_ratio_alpha": 1.00002,
            "apparent_duration_s": 60.0,
            "true_duration_s": 60.0,
            "splice_detected": False,
            "splice_time_s": None,
            "phase_jump_deg": 4.2,
            "verdict": "NOMINAL_SPEED_CONSISTENT (No speed tampering or temporal splice detected)"
        }
    }

    # CASE 2: Negative / Safeguard Triggered -> INCONCLUSIVE (Judge Upload / Outdoor Dashcam)
    trace_f_case2 = np.round(50.0 + rng.normal(0.0, 0.036, size=n), 5)
    ref_f_case2 = np.round(50.0 + 0.025 * np.sin(2 * np.pi * t / 29.0), 5)
    trace_q_case2 = np.round(np.clip(0.38 + rng.normal(0.0, 0.11, size=n), 0.12, 0.58), 3)

    landscape_2 = []
    for ts in grid_ts:
        score = float(np.clip(rng.normal(0.21, 0.08), -0.05, 0.43))
        landscape_2.append({"ts_utc": int(ts), "score": round(score, 4), "label": "background"})
    landscape_2.append({"ts_utc": search_start_1 + 61200, "score": 0.438, "label": "best_peak"})
    landscape_2.append({"ts_utc": search_start_1 + 148000, "score": 0.411, "label": "second_best"})
    landscape_2.append({"ts_utc": claimed_utc_1, "score": 0.294, "label": "claimed_time"})
    landscape_2.sort(key=lambda x: x["ts_utc"])

    case_2 = {
        "case_id": "GC-2026-9104",
        "title": "Case 2: Outdoor Dashcam Clip — Code Safeguard Blocks Escalation (INCONCLUSIVE)",
        "scenario_type": "SAFEGUARD_ABSTENTION",
        "data_provenance": "ILLUSTRATIVE — SYNTHETIC FIXTURE (NO LIVE MEASUREMENT CLAIMED)",
        "claim_context": {
            "claim_id": "CLM-UK-2026-9104 / Live Judge Upload Safeguard",
            "is_fictional_scenario": True,
            "named_user": "Motor Claims Handler / Live Judge Challenge",
            "financial_decision": "Do NOT flag claim for time discrepancy; route to standard non-ENF corroboration because signal falls below deterministic evidentiary threshold.",
            "policy_type": "Commercial Motor — Rear-End Collision",
            "reserve_gbp": 8200,
            "claimed_start_utc": claimed_utc_1,
            "claimed_start_iso": "2026-10-14T21:15:00Z",
            "matched_start_iso": "ABSTAINED (Below Null Threshold)",
            "search_window_utc": [search_start_1, search_end_1],
            "search_window_label": "72-hour window (2026-10-12 00:00Z to 2026-10-15 00:00Z)",
            "discrepancy_hours": None,
            "narrative_summary": "18-second outdoor battery-powered dashcam clip with DC automotive electronics and wind noise. Argon attempts both audio and streetlamp rolling-shutter extraction; code-enforced gate blocks any timestamp claim and issues a rigorous INCONCLUSIVE abstention."
        },
        "intake": {
            "media_filename": "DASH_20261014_outdoor_clip.mp4",
            "media_sha256": "7d865e959b2466918c9863afca942d0fb89d7c9ac0c99bafc3749504ded97730",
            "probe": {
                "container": "MPEG-4",
                "codec_video": "H.264 (Variable Frame Rate detected: 24.1–30.2 fps)",
                "codec_audio": "AAC-LC (44,100 Hz, heavy AGC / noise suppression)",
                "duration_s": 18.0,
                "fps": 29.97,
                "is_vfr": True,
                "row_readout_us": 16.2,
                "audio_fs_hz": 44100,
                "resolution": "1280x720"
            },
            "blinding": {
                "metadata_withheld": True,
                "stripped_fields": ["EXIF:CreateDate", "OSD Burnt-in Timestamp (masked from ROI)", "Filename tokens"],
                "notice": "BLINDED ANALYSIS ACTIVE: Metadata and burnt-in dashboard clock withheld from ENF extraction and search."
            }
        },
        "investigation_replay": [
            {
                "attempt_id": 1,
                "stage": "Proposal 1 (Audio 50/100 Hz Extraction)",
                "argon_hypothesis": "Argon probes audio track for 50 Hz / 100 Hz mains hum inside vehicle cabin.",
                "tool_call": "analyse_audio(path='DASH_20261014.mp4', harmonics=[50,100], window_s=4.0, hop_s=1.0)",
                "verifier_outcome": "REJECTED",
                "verifier_rule_triggered": "GATE_NO_HARMONIC_CARRIER (snr_db = -6.8 dB < 3.0 dB)",
                "verifier_reason": "Vehicle cabin is DC battery/alternator powered; acoustic spectrum dominated by engine RPM harmonic and wind noise.",
                "metrics": {"median_q": 0.19, "frac_valid": 0.17, "snr_db": -6.8},
                "failed_trace_f": trace_f_case2.tolist(),
                "failed_trace_q": trace_q_case2.tolist()
            },
            {
                "attempt_id": 2,
                "stage": "Revision 2 (Visual ROI — Distant Roadside Streetlamp)",
                "argon_hypothesis": "Argon identifies a stationary roadside lamp in upper-right quadrant and attempts rolling-shutter row demodulation.",
                "tool_call": "analyse_video(path='DASH_20261014.mp4', roi=[940,80,1220,290], nominal_hz=50)",
                "verifier_outcome": "SAFEGUARD_TRIGGERED",
                "verifier_rule_triggered": "SAFEGUARD_NULL_CALIBRATION_GATE (score = 0.438 < threshold 0.540; p_empirical = 0.184 > 0.01; margin = 0.027 < 0.15)",
                "verifier_reason": "CODE SAFEGUARD FIRED: 18s VFR clip yields weak correlation (0.438) indistinguishable from chance across a 72h search window. Deterministic gate blocks timestamp output and forces INCONCLUSIVE.",
                "metrics": {"median_q": 0.41, "frac_valid": 0.52, "snr_db": 1.8}
            }
        ],
        "trace": {
            "source": "video",
            "method": "rolling_shutter_row_demod_v1",
            "nominal_hz": 50,
            "harmonics_used": [100],
            "window_s": 4.0,
            "hop_s": 1.0,
            "fs_media": 29.97,
            "duration_s": 18.0,
            "media_sha256": "7d865e959b2466918c9863afca942d0fb89d7c9ac0c99bafc3749504ded97730",
            "params": {"roi": [940, 80, 1220, 290], "vfr_compensation": True},
            "quality_summary": {"median_q": 0.41, "frac_valid": 0.52, "snr_db": 1.8},
            "provenance": {"code": "work/W08/extract_video.py", "version": "0.2.0-illustrative"},
            "t": t.tolist(),
            "f": trace_f_case2.tolist(),
            "q": trace_q_case2.tolist(),
            "visual_corroboration_note": "Neither audio nor visual channel passes null calibration. Code-enforced policy prevents LLM speculation."
        },
        "reference": {
            "source": "NESO",
            "cadence_s": 1,
            "grid": "GB",
            "coverage": [search_start_1, search_end_1],
            "url": "https://api.neso.energy/dataset/system-frequency-data",
            "sha256": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
            "aligned_f": ref_f_case2.tolist()
        },
        "match": {
            "best": {
                "start_utc": search_start_1 + 61200,
                "score": 0.438,
                "rmse_mhz": 33.4,
                "offset_hz": 0.0112
            },
            "candidates": [
                {"rank": 1, "start_utc": search_start_1 + 61200, "iso": "2026-10-12T17:00:00Z", "score": 0.438, "rmse_mhz": 33.4, "offset_hz": 0.0112},
                {"rank": 2, "start_utc": search_start_1 + 148000, "iso": "2026-10-13T17:06:40Z", "score": 0.411, "rmse_mhz": 34.1, "offset_hz": -0.0085},
                {"rank": 3, "start_utc": search_start_1 + 201900, "iso": "2026-10-14T08:05:00Z", "score": 0.399, "rmse_mhz": 35.0, "offset_hz": 0.0041}
            ],
            "null": {
                "method": "block_permutation_ar1_calibrated",
                "n": 5000,
                "p_empirical": 0.1840,
                "score_threshold": 0.540
            },
            "uniqueness": {
                "margin_vs_second": 0.027,
                "second_best_distance_s": 86800
            },
            "diagnostics": {
                "effective_dof": 11.4,
                "claimed_time_score": 0.294,
                "claimed_time_rmse_mhz": 38.9,
                "sub_segment_consistency": "FAILED: Split halves peak 61,400 seconds apart."
            },
            "status": "INCONCLUSIVE",
            "status_reasons": [
                "SAFEGUARD TRIGGERED: Best candidate correlation (0.438) is BELOW the code-enforced null threshold (0.540; p_empirical = 0.184 > 0.01).",
                "Uniqueness margin fails threshold (margin_vs_second = 0.027 < 0.15 required); top 3 candidates are statistically indistinguishable.",
                "Short clip duration (18.0 s) + Variable Frame Rate (VFR) + outdoor DC environment provide insufficient ENF degrees of freedom."
            ],
            "what_would_change_this": [
                "A stationary indoor recording of >= 120 seconds captured near mains-powered lighting (100 Hz optical flicker) or AC appliances.",
                "Narrowing the candidate search window via independent telematics / ANPR / cell-tower bounds before running null calibration.",
                "Original constant-frame-rate (CFR) uncompressed or lightly compressed source footage."
            ],
            "landscape": landscape_2
        },
        "speed_check": {
            "estimated_carrier_hz": 50.012,
            "nominal_hz": 50.0,
            "speed_ratio_alpha": 1.00024,
            "apparent_duration_s": 18.0,
            "true_duration_s": 18.0,
            "splice_detected": False,
            "splice_time_s": None,
            "phase_jump_deg": 18.5,
            "verdict": "INCONCLUSIVE_CARRIER (SNR too low for high-confidence speed/splice audit)"
        }
    }

    # CASE 3: W13 Speed-Change & Splice Tampering Detection
    # Carrier shifted to 53.12 Hz (alpha = +1.0624x speed-up) + splice at t=28s
    trace_f_case3 = np.round(53.120 + base_dev * 1.0624 + rng.normal(0.0, 0.005, size=n), 5)
    trace_q_case3 = np.round(np.clip(0.91 + rng.normal(0.0, 0.04, size=n), 0.72, 0.99), 3)
    # Introduce a sharp anomaly at splice t=28s
    trace_q_case3[27:30] = [0.31, 0.22, 0.35]

    case_3 = {
        "case_id": "GC-2026-9310",
        "title": "Case 3: Loading-Bay CCTV — W13 Speed-Alteration (1.0624x) & Splice Detected",
        "scenario_type": "SPEED_SPLICE_TAMPERING",
        "data_provenance": "ILLUSTRATIVE — SYNTHETIC FIXTURE (NO LIVE MEASUREMENT CLAIMED)",
        "claim_context": {
            "claim_id": "CLM-UK-2026-9310 (Fictional Scenario)",
            "is_fictional_scenario": True,
            "named_user": "SIU Forensic Analyst — Workplace Liability & Cargo Loss",
            "financial_decision": "Escalate to SIU human review & request native DVR export; do not rely on re-encoded clip for Forklift impact speed or timeline.",
            "policy_type": "Commercial Liability & Goods in Transit",
            "reserve_gbp": 41000,
            "claimed_start_utc": claimed_utc_1,
            "claimed_start_iso": "2026-10-14T21:15:00Z",
            "matched_start_iso": "TAMPERED CARRIER (53.120 Hz / +6.24% Speed Shift)",
            "search_window_utc": [search_start_1, search_end_1],
            "search_window_label": "72-hour window (2026-10-12 00:00Z to 2026-10-15 00:00Z)",
            "discrepancy_hours": 0.0,
            "narrative_summary": "Submitted CCTV clip appears to show a rapid safety-gate closure and missing 12-second inspection interval. W13 deterministic carrier tracker finds the nominal 50.000 Hz GB grid hum shifted uniformly to 53.120 Hz (alpha = 1.0624x playback speed-up) plus a 142 deg ENF phase discontinuity at t = 28.0 s."
        },
        "intake": {
            "media_filename": "CCTV_Bay4_Export_Reencoded.mp4",
            "media_sha256": "4b227777d4dd1fc61c6f884f48641d02b4d121d3fd328cb08b5531fcacdabf8a",
            "probe": {
                "container": "MPEG-4 (Lavf60.16.100 re-encode signature)",
                "codec_video": "H.264 (30.00 fps constant)",
                "codec_audio": "AAC-LC (48,000 Hz, unpitched resample artifact)",
                "duration_s": 56.5,
                "fps": 30.0,
                "is_vfr": False,
                "row_readout_us": 13.9,
                "audio_fs_hz": 48000,
                "resolution": "1920x1080"
            },
            "blinding": {
                "metadata_withheld": True,
                "stripped_fields": ["Lavf encoder tags", "File timestamps", "Claimed incident time"],
                "notice": "BLINDED ANALYSIS ACTIVE: Metadata withheld from W13 carrier & phase-continuity analysis."
            }
        },
        "investigation_replay": [
            {
                "attempt_id": 1,
                "stage": "Proposal 1 (Standard 50.000 Hz Narrowband Filter)",
                "argon_hypothesis": "Argon runs standard 50.0 ± 0.25 Hz narrowband extraction on DVR audio track.",
                "tool_call": "analyse_audio(path='CCTV_Bay4.mp4', nominal_hz=50, band_halfwidth_hz=0.25)",
                "verifier_outcome": "REJECTED",
                "verifier_rule_triggered": "GATE_CARRIER_OFFSET_ANOMALY (in-band energy at 50.0 Hz < -8 dB; strong harmonic ridge detected at +6.24% offset)",
                "verifier_reason": "Standard 50.0 Hz band is empty, but wideband harmonic comb scanner detects coherent mains hum + 2nd/3rd harmonics shifted to 53.120 / 106.240 / 159.360 Hz.",
                "metrics": {"median_q": 0.14, "frac_valid": 0.12, "snr_db": -8.1},
                "failed_trace_f": attempt1_f.tolist(),
                "failed_trace_q": attempt1_q.tolist()
            },
            {
                "attempt_id": 2,
                "stage": "Revision 2 (W13 Speed-Factor Estimation + Phase-Continuity Splice Audit)",
                "argon_hypothesis": "Argon invokes W13 speed & splice detector to estimate playback stretch ratio alpha = f_est / 50.0 and test phase continuity across the clip.",
                "tool_call": "detect_speed_and_splice(path='CCTV_Bay4.mp4', nominal_hz=50.0)",
                "verifier_outcome": "ACCEPTED",
                "verifier_rule_triggered": "W13_SPEED_ANOMALY_CONFIRMED (alpha = 1.0624 ± 0.0003) & W13_SPLICE_PHASE_JUMP (Δφ = 142.4° at t = 28.0 s)",
                "verifier_reason": "After de-warping by alpha = 1.0624x and splitting at t = 28.0 s, both sub-segments match NESO GB reference with a 12.0 s excised gap between t=28s and t=29s.",
                "metrics": {"median_q": 0.91, "frac_valid": 0.95, "snr_db": 16.4}
            }
        ],
        "trace": {
            "source": "audio",
            "method": "w13_dewarped_harmonic_ridge_v1",
            "nominal_hz": 50,
            "harmonics_used": [50, 100, 150],
            "window_s": 4.0,
            "hop_s": 1.0,
            "fs_media": 48000.0,
            "duration_s": 56.5,
            "media_sha256": "4b227777d4dd1fc61c6f884f48641d02b4d121d3fd328cb08b5531fcacdabf8a",
            "params": {"estimated_alpha": 1.0624, "raw_carrier_hz": 53.120, "splice_split_s": 28.0},
            "quality_summary": {"median_q": 0.91, "frac_valid": 0.95, "snr_db": 16.4},
            "provenance": {"code": "work/W13/speed_splice.py", "version": "0.2.0-illustrative"},
            "t": t.tolist(),
            "f": trace_f_case1.tolist(),
            "raw_shifted_f": trace_f_case3.tolist(),
            "q": trace_q_case3.tolist(),
            "visual_corroboration_note": "Visual rolling-shutter flicker also appears at 106.24 Hz instead of 100.00 Hz, confirming media-wide playback speed alteration rather than audio pitch drift."
        },
        "reference": {
            "source": "NESO",
            "cadence_s": 1,
            "grid": "GB",
            "coverage": [search_start_1, search_end_1],
            "url": "https://api.neso.energy/dataset/system-frequency-data",
            "sha256": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
            "aligned_f": ref_f_case1.tolist()
        },
        "match": {
            "best": {
                "start_utc": claimed_utc_1,
                "score": 0.889,
                "rmse_mhz": 5.1,
                "offset_hz": 3.120
            },
            "candidates": [
                {"rank": 1, "start_utc": claimed_utc_1, "iso": "2026-10-14T21:15:00Z (De-warped)", "score": 0.889, "rmse_mhz": 5.1, "offset_hz": 3.120},
                {"rank": 2, "start_utc": claimed_utc_1 - 91200, "iso": "2026-10-13T19:55:00Z", "score": 0.388, "rmse_mhz": 26.4, "offset_hz": 3.118}
            ],
            "null": {
                "method": "block_permutation_ar1_calibrated",
                "n": 5000,
                "p_empirical": 0.0006,
                "score_threshold": 0.540
            },
            "uniqueness": {
                "margin_vs_second": 0.501,
                "second_best_distance_s": 91200
            },
            "diagnostics": {
                "effective_dof": 41.0,
                "claimed_time_score": 0.889,
                "claimed_time_rmse_mhz": 5.1,
                "sub_segment_consistency": "DISCONTINUOUS: Segment A (0-28s) and Segment B (28-56.5s) exhibit a 12.0s missing grid interval and Δφ = 142.4° phase jump."
            },
            "status": "MATERIAL_DISCREPANCY_REVIEW",
            "status_reasons": [
                "W13 SPEED TAMPERING DETECTED: Nominal 50.000 Hz grid carrier shifted to 53.120 Hz (playback speed ratio alpha = 1.0624x, +6.24% faster than real time).",
                "W13 SPLICE DETECTED: Instantaneous phase discontinuity Δφ = 142.4° at t = 28.0 s with a 12.0-second gap against the continuous NESO reference.",
                "Human SIU review required to inspect native DVR image before relying on clip timing."
            ],
            "what_would_change_this": [
                "Native proprietary DVR export with verified crystal clock calibration showing unedited phase continuity across t = 28.0 s.",
                "Verified hardware sample-rate clock fault in the recording appliance (48.0 kHz -> 45.18 kHz ADC clock drift) without frame removal."
            ],
            "landscape": landscape_1
        },
        "speed_check": {
            "estimated_carrier_hz": 53.120,
            "nominal_hz": 50.0,
            "speed_ratio_alpha": 1.0624,
            "apparent_duration_s": 56.5,
            "true_duration_s": 60.0,
            "splice_detected": True,
            "splice_time_s": 28.0,
            "phase_jump_deg": 142.4,
            "verdict": "MATERIAL_SPEED_AND_SPLICE_ANOMALY (+6.24% speed-up & 12.0s splice at t=28.0s)"
        }
    }

    # CASE 4: Positive Corroboration (MATCH_SUPPORTED)
    landscape_4 = []
    for ts in grid_ts:
        score = float(np.clip(rng.normal(0.17, 0.08), -0.10, 0.39))
        landscape_4.append({"ts_utc": int(ts), "score": round(score, 4), "label": "background"})
    landscape_4.append({"ts_utc": claimed_utc_1, "score": 0.932, "label": "best_peak"})
    landscape_4.append({"ts_utc": claimed_utc_1 - 74200, "score": 0.394, "label": "second_best"})
    landscape_4.sort(key=lambda x: x["ts_utc"])

    case_4 = {
        "case_id": "GC-2026-8902",
        "title": "Case 4: Blinded Benchmark Verification — Claimed Window Corroborated (MATCH_SUPPORTED)",
        "scenario_type": "MATCH_SUPPORTED_BENCHMARK",
        "data_provenance": "ILLUSTRATIVE — SYNTHETIC FIXTURE (NO LIVE MEASUREMENT CLAIMED)",
        "claim_context": {
            "claim_id": "CLM-UK-2026-8902 / Held-Out Benchmark Positive",
            "is_fictional_scenario": True,
            "named_user": "Claims Investigator — Fast-Track Settlement Triage",
            "financial_decision": "Clear video timestamp evidence for standard claim settlement processing (no temporal anomaly detected).",
            "policy_type": "Commercial Property — Storm & Flood Ingress",
            "reserve_gbp": 14800,
            "claimed_start_utc": claimed_utc_1,
            "claimed_start_iso": "2026-10-14T21:15:00Z",
            "matched_start_iso": "2026-10-14T21:15:02Z",
            "search_window_utc": [search_start_1, search_end_1],
            "search_window_label": "72-hour window (2026-10-12 00:00Z to 2026-10-15 00:00Z)",
            "discrepancy_hours": 0.0005,
            "narrative_summary": "Blinded ENF extraction recovers a high-SNR 60-second trace that uniquely locks to the NESO GB 1-second reference at 2026-10-14 21:15:02 UTC—within 2 seconds of the independently withheld ground-truth / stated claim time."
        },
        "intake": {
            "media_filename": "BENCH_ENF_Indoor_mains_04.mp4",
            "media_sha256": "2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae",
            "probe": {
                "container": "MPEG-4 / WAV PCM companion",
                "codec_video": "H.264 (25.00 fps constant, UK PAL shutter)",
                "codec_audio": "PCM 16-bit (44,100 Hz)",
                "duration_s": 60.0,
                "fps": 25.0,
                "is_vfr": False,
                "row_readout_us": 18.5,
                "audio_fs_hz": 44100,
                "resolution": "1920x1080"
            },
            "blinding": {
                "metadata_withheld": True,
                "stripped_fields": ["Ground-truth manifest timestamp", "Creation time", "Filename index"],
                "notice": "BLINDED ANALYSIS ACTIVE: Ground-truth timestamp withheld during extraction & 72h search; revealed only at post-search verification."
            }
        },
        "investigation_replay": [
            {
                "attempt_id": 1,
                "stage": "Proposal 1 (Multi-Harmonic Audio + Rolling-Shutter Wall ROI)",
                "argon_hypothesis": "Argon detects strong 100 Hz and 200 Hz acoustic harmonics and stationary 25 fps indoor mains illumination.",
                "tool_call": "analyse_audio(path='BENCH_ENF_04.mp4', harmonics=[100,200], window_s=4.0, hop_s=1.0)",
                "verifier_outcome": "ACCEPTED",
                "verifier_rule_triggered": "ALL_QUALITY_GATES_PASSED (frac_valid = 0.98, snr_db = 17.5 dB)",
                "verifier_reason": "High-SNR sequence accepted on Attempt 1; unique correlation peak (r = 0.932) matches stated window within ±2s.",
                "metrics": {"median_q": 0.93, "frac_valid": 0.98, "snr_db": 17.5}
            }
        ],
        "trace": {
            "source": "audio",
            "method": "stft_multiharmonic_weighted_ridge_v1",
            "nominal_hz": 50,
            "harmonics_used": [100, 200],
            "window_s": 4.0,
            "hop_s": 1.0,
            "fs_media": 44100.0,
            "duration_s": 60.0,
            "media_sha256": "2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae",
            "params": {"n_fft": 65536, "band_halfwidth_hz": 0.30},
            "quality_summary": {"median_q": 0.93, "frac_valid": 0.98, "snr_db": 17.5},
            "provenance": {"code": "work/W06/extract.py", "version": "0.2.0-illustrative"},
            "t": t.tolist(),
            "f": trace_f_case1.tolist(),
            "q": trace_q_case1.tolist(),
            "visual_corroboration_note": "Audio and visual ENF traces are mutually consistent (r = 0.86); reported as a single joint physical environment match."
        },
        "reference": {
            "source": "NESO",
            "cadence_s": 1,
            "grid": "GB",
            "coverage": [search_start_1, search_end_1],
            "url": "https://api.neso.energy/dataset/system-frequency-data",
            "sha256": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
            "aligned_f": ref_f_case1.tolist()
        },
        "match": {
            "best": {
                "start_utc": claimed_utc_1 + 2,
                "score": 0.932,
                "rmse_mhz": 3.8,
                "offset_hz": 0.0002
            },
            "candidates": [
                {"rank": 1, "start_utc": claimed_utc_1 + 2, "iso": "2026-10-14T21:15:02Z", "score": 0.932, "rmse_mhz": 3.8, "offset_hz": 0.0002},
                {"rank": 2, "start_utc": claimed_utc_1 - 74200, "iso": "2026-10-13T00:38:20Z", "score": 0.394, "rmse_mhz": 25.9, "offset_hz": -0.0044}
            ],
            "null": {
                "method": "block_permutation_ar1_calibrated",
                "n": 5000,
                "p_empirical": 0.0001,
                "score_threshold": 0.540
            },
            "uniqueness": {
                "margin_vs_second": 0.538,
                "second_best_distance_s": 74202
            },
            "diagnostics": {
                "effective_dof": 46.8,
                "claimed_time_score": 0.932,
                "claimed_time_rmse_mhz": 3.8,
                "sub_segment_consistency": "PASSED: Split halves independently align within 1s."
            },
            "status": "MATCH_SUPPORTED",
            "status_reasons": [
                "Blinded ENF match peak (r = 0.932, RMSE = 3.8 mHz) exceeds null threshold (0.540, p_empirical = 0.0001).",
                "Strong uniqueness margin (+0.538 above second-best candidate across 72h search space).",
                "Matched timestamp (2026-10-14 21:15:02 UTC) corroborates stated claim window within 2 seconds."
            ],
            "what_would_change_this": [
                "Evidence of synthetic audio injection or re-recorded loudspeaker playback of a known historical grid trace.",
                "Discovery of a post-recording audio track replacement in container atom structure."
            ],
            "landscape": landscape_4
        },
        "speed_check": {
            "estimated_carrier_hz": 50.000,
            "nominal_hz": 50.0,
            "speed_ratio_alpha": 1.00000,
            "apparent_duration_s": 60.0,
            "true_duration_s": 60.0,
            "splice_detected": False,
            "splice_time_s": None,
            "phase_jump_deg": 3.1,
            "verdict": "NOMINAL_SPEED_CONSISTENT (No speed tampering or splice detected)"
        }
    }

    bundle = {
        "schema_version": "interfaces.md.v1",
        "generated_by": "work/W15/generate_fixtures.py",
        "default_data_provenance": "ILLUSTRATIVE — SYNTHETIC FIXTURE (NO LIVE MEASUREMENT CLAIMED)",
        "cases": [case_1, case_2, case_3, case_4]
    }

    with open(out_dir / "cases_illustrative.json", "w", encoding="utf-8") as f:
        json.dump(bundle, f, indent=2)

    # Also save standalone integration/interfaces.md v1 sample files for drop-in testing
    with open(out_dir / "sample_case1.trace.json", "w", encoding="utf-8") as f:
        json.dump(case_1["trace"], f, indent=2)
    with open(out_dir / "sample_case1.match.json", "w", encoding="utf-8") as f:
        json.dump(case_1["match"], f, indent=2)
    np.savez(
        out_dir / "sample_case1.trace.npz",
        t=np.array(case_1["trace"]["t"], dtype=np.float64),
        f=np.array(case_1["trace"]["f"], dtype=np.float64),
        q=np.array(case_1["trace"]["q"], dtype=np.float64),
    )
    print(f"Wrote {out_dir / 'cases_illustrative.json'} with {len(bundle['cases'])} cases.")


if __name__ == "__main__":
    generate_cases()
