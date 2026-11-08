# Frozen interfaces (v1, set by director 2026-11-08). Change only via the director.

## 1. ENF trace (output of any extractor; audio or video)
Files: `<name>.trace.npz` + `<name>.trace.json`
- npz arrays: `t` float64, seconds from media start (window centres) · `f` float64, Hz, estimated **fundamental-equivalent** grid frequency (already divided by the harmonic number, so ≈50.0) · `q` float64 in [0,1], per-window quality (NaN `f` where unusable)
- json: `{"source": "audio"|"video", "method": str, "nominal_hz": 50|60, "harmonics_used": [..], "window_s": float, "hop_s": float, "fs_media": float, "duration_s": float, "media_sha256": str, "params": {...}, "quality_summary": {"median_q": .., "frac_valid": .., "snr_db": ..}, "provenance": {"code": "work/<ID>/...", "version": str}}`
- **Never** include wall-clock timestamps from metadata in the trace.

## 2. Grid reference series
Parquet or CSV with columns: `ts_utc` (int64 epoch **seconds**, UTC) and `f_hz` (float64). Optional `source`. Must be regularly sampled; declare cadence in a sidecar `.json`: `{"source": "NESO"|"ELEXON"|"LOCAL_STATION"|"DATASET_REF", "cadence_s": 1|15|.., "grid": "GB"|"CN-central"|"ES"|.., "coverage": [start,end], "url": .., "sha256": ..}`.
Python loader signature (W02 owns GB): `load_reference(start_utc: int, end_utc: int, source: str = "NESO") -> pandas.DataFrame[ts_utc, f_hz]`.

## 3. Match result (W10 owns the matcher)
`match(trace, reference, search_start_utc, search_end_utc, config) -> dict`:
`{"best": {"start_utc": int, "score": float, "rmse_mhz": float, "offset_hz": float}, "candidates": [top-K same shape], "null": {"method": str, "n": int, "p_empirical": float, "score_threshold": float}, "uniqueness": {"margin_vs_second": float, "second_best_distance_s": int}, "diagnostics": {...}, "status": "MATCH_SUPPORTED"|"INCONCLUSIVE"|"MATERIAL_DISCREPANCY_REVIEW", "status_reasons": [str], "what_would_change_this": [str]}`
A `claimed_start_utc` may be passed **only** to the final decision step, never to the search.

## 4. Extractor API
`analyse_audio(path, config) -> (trace_npz_path, trace_json_path)`; `analyse_video(path, config) -> (… same …, rois: list)`. CLI form: `python <script> --in <media> --out <dir> [--nominal 50]`.

## 5. Eval case manifest (W03/W10)
CSV: `case_id, media_path, media_sha256, dataset, grid, true_start_utc_or_ref_alignment, duration_s, modality, has_enf_label, split(dev|holdout), notes`. The holdout rows are never used for tuning.
