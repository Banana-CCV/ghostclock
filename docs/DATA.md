# Data

Raw datasets and media are **not committed**: they are large, licensed separately, or private team recordings. This page lists where each dataset came from, its licence, the checksums we recorded, and the data traps we found. Per-file provenance sidecars for the GB reference are in [data_manifest/gb/](data_manifest/gb/neso_2026_09.json).

## Sources and licences

| Dataset | What we used | Licence / terms | Where to get it |
|---|---|---|---|
| **ENF-WHU** (Hua et al.) | 130 H1 recordings (8 kHz) with H1_ref (400 Hz) and 28 one-day references (`H1_ref_one_day`), plus 50 H0 no-ENF recordings | MIT (Copyright 2023 Hua Guang) | GitHub repository of the ENF-WHU dataset |
| **ENF Moving Video Database**, Zenodo 3549379 (Fernández-Menduiña & Pérez-González) | One video `MOV2_20190508_200450A.mp4` (1.2 GB) and its mains reference `b827ebd746d7_tensiunator2_20190508_200340.wav` | CC-BY-4.0 (as recorded in [C4 METHOD.md](../experiments/c4_video_rolling_shutter/METHOD.md)) | doi:10.5281/zenodo.3549379 |
| **NESO** historic system frequency (1 s) | Months 2025-10, 2025-11, 2026-03, 2026-06, 2026-08, 2026-09 (W02/W11 streamed further months for audits) | NESO Open Data Licence (from the CKAN package metadata, [neso_package.json](../experiments/c2_gb_reference_and_feasibility/neso_package.json)) | NESO data portal, monthly `fnew-YYYY-M.csv` |
| **Elexon BMRS** Insights API `system/frequency` (15 s) | Monthly extracts for the NESO overlap months, plus a live archive from 2026-11-07 00:00Z | Elexon BMRS data terms (not re-checked for this release) | `https://data.elexon.co.uk/bmrs/api/v1/system/frequency` |
| **Team venue recordings** (08 Nov 2026) | Two phone videos | Private; not distributed | SHA-256 below |

## Checksums

**Zenodo files (md5, from the Zenodo API, verified on download by C4):**

| File | md5 | Size (bytes) |
|---|---|---|
| `MOV2_20190508_200450A.mp4` | `cd940e751d85e5ae2b7c3fb46a4e40ae` | 1,212,054,170 |
| `b827ebd746d7_tensiunator2_20190508_200340.wav` | `9b478a76c5222552f2d4f85178fe493a` | 1,800,044 |

**GB reference parquet files (SHA-256 of the converted parquet, from each sidecar):**

| File | SHA-256 |
|---|---|
| `neso_2025_10.parquet` | `d61fd0bc7eb9e436e5778c7edb36f15abd38053b2efb2414d46bcf70f8d92a07` |
| `neso_2025_11.parquet` | `78c53116f8fa544effaad29e65f76b0aff7b5fc83f7674ba50ee59c1e511297b` |
| `neso_2026_03.parquet` | `fc1bd711197ddde81e140be15aa72fd0e11cd3b9fe2ae47100e947872f4d86a4` |
| `neso_2026_06.parquet` | `ac37bc1f29e579ec22492eec9fa75b17cdfe59ab429cfbf978c58ebbc10b0236` |
| `neso_2026_08.parquet` | `3a552dcd9d18a0a3ea381e2446935111f9687c9e33fd80a4cbfb35b8754c0993` |
| `neso_2026_09.parquet` | `b0098376b7965191c34bd01168dd0c0835e1c7e1f16ba256c7516b1d353fd55e` |
| `elexon_2025_10.parquet` | `1d7567c8663167aed5a4b1039c02df35c6c1c684eb85fdaaa3c41d41f95b596f` |
| `elexon_2025_11.parquet` | `841d7edbd760b39824ba1a9e0fadbabd2aac1e988e9033b684fcd3cee97b6e0c` |
| `elexon_2026_03.parquet` | `8b4f4197712103a664906da0dec9ce86554a7c72d4d65620fd9f1f69c7bb3fb5` |
| `elexon_2026_06.parquet` | `c5bed2d8953e1a51fb75e6cfe7fb6ceb000ac6a14fc92d89a906daf767664d30` |
| `elexon_2026_08.parquet` | `d397cf58a901a025a3033d644e3b84b09dc52b4142dadee01e1f84af7aac08fb` |
| `elexon_2026_09.parquet` | `50997bae1c9198ea45d6e29851190ca8e6bc398587a18717ff64711ee9b84b14` |

The live Elexon archive (`elexon_live.parquet`) grows continuously, so it has no fixed hash.

**Team recordings:** [SHA256SUMS.txt](../experiments/team_recordings_venue/SHA256SUMS.txt).

**ENF-WHU:** the dev/holdout split is recorded file by file in [split.json](../experiments/c1_enfwhu_unseen_holdout/split.json), with the project-wide copy at [source/enf_whu_split.json](source/enf_whu_split.json). Per-file ground truth is in [gt_w16.json](../experiments/c1_enfwhu_unseen_holdout/gt_w16.json).

## Traps found, and how the code handles them

Each of these would have produced false matches if left alone.

| Trap | Evidence | Handling |
|---|---|---|
| **NESO 2025 BST months stamped UTC+1.** Oct 2025 matches Elexon at +3600 s on every day, including after the 26 Oct clock change. W02 extended this to all of Apr–Oct 2025. 2026 files are clean UTC | [C2 FINDINGS.md](../experiments/c2_gb_reference_and_feasibility/FINDINGS.md), [W02 review](../experiments/w02_independent_reproduction_of_c2/W02_reproduce_C2.md) | `ghostclock/data/neso_time_corrections.json` applies −3600 s to 2025-10. **Months not listed default to 0**: Apr–Sep 2025 must be added (and checked with the lag scan) before use. Also, because 2025-10 is UTC+1 and 2025-11 is UTC, the hour 2025-10-31T23:00Z–23:59:59Z is missing. |
| **NESO flat-filled outages.** 2026-09-15 07:30:03–10:35:59 UTC (11,158 s at a constant 49.895 Hz) and 2026-03-31 (479 s at 50.046 Hz) | [C2 FINDINGS.md](../experiments/c2_gb_reference_and_feasibility/FINDINGS.md), [sidecar](data_manifest/gb/neso_2026_09.json) | `bad_intervals` in the sidecars are masked to NaN by `gb_reference.py`. The matcher also masks any flat run of 15 or more samples. |
| **Elexon 0.0 Hz placeholders** during outages (1 row in Nov 2025, 167 in Jan 2026, 732 in Feb 2026) | [W02 review](../experiments/w02_independent_reproduction_of_c2/W02_reproduce_C2.md) | Values outside 45–55 Hz become NaN. |
| **Elexon 2026 extra scatter.** About 3.5–5.6 mHz extra noise against NESO from 2026-02-13; RMSE at lag 0 is 0.59 mHz in Nov 2025 vs 7.45 mHz in Sep 2026 | [director check output](../reviews/outputs/director_verify_c2.txt) | Prefer NESO 1 s when it has been published. With Elexon, linearly interpolate to 1 s (W02) and require longer clips. |
| **Elexon is a point sample, not a 15 s average** (88.5% of values exactly equal NESO at ts % 15 == 0, Nov 2025) | [W02 review](../experiments/w02_independent_reproduction_of_c2/W02_reproduce_C2.md) | Do not block-average the query against real Elexon. That costs recall (0.655 vs 0.733 at 5 min). |
| **ENF-WHU ground-truth offsets.** Per-file offsets of −5 to +4.5 s; one day-reference file repeats whole hours (recordings 090/091) | [C1 DATASET_NOTES.md](../experiments/c1_enfwhu_unseen_holdout/DATASET_NOTES.md) | The primary tolerance is ±5 s. ±1 s claims use only per-file refined ground truth. 090/091 are excluded from C1, and the W10 uniqueness gate returns `INCONCLUSIVE` on them. |
| **Filename timestamps are unreliable** (Zenodo MOV2: the filename implies a 70 s lag, the ENF says 81.5 s) | [C4 FAILURES.md](../experiments/c4_video_rolling_shutter/FAILURES.md) | Metadata is never used as ground truth for the match. |
| **Rotation metadata** on the team phone videos (`rotation = -90`) | [team report](../experiments/team_recordings_venue/A001_11081142_C004/report.json) | Probed by `quick_check` (the band direction depends on the displayed orientation). |
