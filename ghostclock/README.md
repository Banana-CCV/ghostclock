# `ghostclock` core library

A deterministic, path-portable core curated from the pre-test studies. It makes no LLM calls. Every module still matches the study code that produced the reported numbers. The only changes are imports and file locations (repo-relative or set by environment variable instead of hard-coded workspace paths), plus one fix to an argparse help string in `matcher.py` (an unescaped `%`).

| Module | Origin | Purpose |
|---|---|---|
| `audio_enf.py` | [C1 `enf.py`](../experiments/c1_enfwhu_unseen_holdout/enf.py) | Mains-hum ENF trace from audio |
| `rs_enf.py` | [C4 `rs_enf.py`](../experiments/c4_video_rolling_shutter/rs_enf.py) | Rolling-shutter ENF trace from video |
| `gb_reference.py` (+ `neso_convert.py`, `elexon_archiver.py`, `data/`) | [C2](../experiments/c2_gb_reference_and_feasibility/README.md) | GB grid-frequency reference: NESO 1 s or Elexon 15 s |
| `matcher.py` | [W10](../experiments/w10_matcher_and_null_calibration/README.md) | Blind weighted-NCC search, calibrated null, top-K, split-half; baselines |
| `policy.py` | [W10](../experiments/w10_matcher_and_null_calibration/README.md) | Deterministic gates giving `MATCH_SUPPORTED` / `INCONCLUSIVE` / `MATERIAL_DISCREPANCY_REVIEW` |
| `tools/quick_check.py`, `tools/decode_and_extract.py`, `tools/make_demo_video.py`, `tools/blind_match.py` | director tools | Triage a media file; decode dark video; render the flicker visualisation; blind-date a trace against the live Elexon archive with a wrong-day null |
| `_paths.py` | new | Repo-relative paths and environment overrides; locates ffmpeg |

**Important.** The grade-A holdout headline was produced by the C1 matcher (`experiments/c1_enfwhu_unseen_holdout/match.py`) with per-length thresholds. `matcher.py` and `policy.py` here are the W10 implementation, which is grade B (not reproduced by the director).

## API

```python
from ghostclock import audio_enf, rs_enf, gb_reference, matcher, policy

# Audio: f(t) in Hz (fundamental-equivalent) plus quality q in dB
x, fs = audio_enf.load_audio("clip.wav")                 # soundfile, with an ffmpeg fallback
r = audio_enf.extract_enf(x, fs)                         # dict with t, f, q (16 s Hann, 1 s hop, harmonics 1-7)

# Video: rolling-shutter trace (see rs_enf.run_video for the end-to-end path)
v = rs_enf.run_video("clip.mp4", f_grid=50.0)

# Reference: a regular grid with NaN where there is no valid data; df.attrs records provenance
ref = gb_reference.load_reference("2026-09-10T00:00Z", "2026-09-10T23:59:59Z", source="NESO", fetch=False)

# Blind match plus policy. The claimed time is used ONLY after the search
res = matcher.match({"t": r["t"], "f": r["f"], "q": r["q"]}, ref,
                    search_start_utc=int(ref.ts_utc.iloc[0]), search_end_utc=int(ref.ts_utc.iloc[-1]),
                    config={"claimed_start_utc": 1789030000, "claim_tolerance_s": 60})
res["status"], res["status_reasons"], res["what_would_change_this"], res["diagnostics"]["policy_audit"]

# Re-evaluate a stored match result under other thresholds
policy.evaluate_policy(res, claimed_start_utc=None, thresholds={"max_p_empirical": 0.01})
```

## CLI

```bash
python -m ghostclock.gb_reference --source ELEXON --start 2026-11-08T09:00Z --end 2026-11-08T10:00Z [--out ref.parquet] [--fetch]
python -m ghostclock.matcher --help
python -m ghostclock.policy --help
python -m ghostclock.tools.quick_check <video_or_audio> [--no-video] [--max-seconds N]   # writes out/quick/<stem>/
python -m ghostclock.tools.make_demo_video <video> --start 30 --dur 15 [--trace out/quick/<stem>/video_rs_trace.csv]
python -m ghostclock.elexon_archiver --once                                              # backfill the live 15 s archive
```

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `GHOSTCLOCK_DATA` | `<repo>/data` | Local data root |
| `GHOSTCLOCK_GB_DIR` | `$GHOSTCLOCK_DATA/gb` | `neso_YYYY_MM.parquet` / `elexon_*.parquet` and their `.json` sidecars |
| `GHOSTCLOCK_OUT` | `<repo>/out` | Outputs of the CLI tools |
| `GHOSTCLOCK_FFMPEG_DIR` | — | Folder with ffmpeg/ffprobe, if they are not on PATH |

`data/neso_time_corrections.json` holds verified per-month NESO timestamp shifts. Only 2025-10 (−3600 s) is listed. W02 found that Apr–Sep 2025 are also stamped UTC+1, so lag-scan any month before trusting it ([docs/DATA.md](../docs/DATA.md)).
