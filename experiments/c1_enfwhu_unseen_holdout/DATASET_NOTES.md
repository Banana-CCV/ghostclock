# ENF-WHU dataset notes (C1)

Source: `datasets/raw/enf-whu/repo/ENF-WHU-Dataset/` (Hua et al., Wuhan University; MIT licence). Recorded around Wuhan University campus (classroom, campus path, meeting room, office, dormitory, library), China -> 50 Hz grid. All files are 16-bit PCM mono WAV. Numbers below were measured by C1 with soundfile, not copied from the README.

| folder | files | sample rate | duration (min / median / max) | content |
|---|---|---|---|---|
| `H1/` 001..130.wav | 130 | 8000 Hz | 268.1 / 604.4 / 954.0 s | real-world recordings (smartphone / voice recorder) that captured ENF |
| `H1_ref/` 001_ref..130_ref.wav | 130 | 400 Hz | 268.0 / 604.0 / 953.0 s | noise-free mains reference, same span as the matching H1 recording |
| `H1_ref_one_day/` | 28 | 400 Hz | 82921 / 86365 / 86426 s | 24-h mains reference per recording **day**; name lists the H1 ids recorded that day (e.g. `043-059_ref.wav` covers H1 043..059) |
| `H0/` O01..O10.wav | 10 | 8000 Hz | 290-918 s | real recordings with **no** ENF captured |
| `H0/` 01..40.wav | 40 | 8000 Hz | 480 s (all) | random crops of the O-files (README) |

Day groups (28): sizes range from 1 recording (e.g. 001, 002, 005) to 19 (089-107).

## H0 crop provenance (measured, `h0_groups.json`)
Crops 01-39 are bit-exact sub-sequences of O02..O08 (6 crops each from O02..O07, 3 from O08). Crop 40 is not bit-exact anywhere but matches O09 with waveform NCC 0.979 (all other O-files < 0.2), so it is assigned to O09. O01 and O10 have no crops. H0 grouping for the split is by source O-file.

## Alignment / ground truth
- README (April 2023 note): the ground-truth timestamp of `H1/xxx.wav` is the lag at which the noise-free `H1_ref/xxx_ref.wav` matches inside its one-day reference; a recording should match "at the same or a very close lag".
- `H1_ref` files are **not** bit-exact crops of the one-day file (checked on 001, 003, 004, 050: max sample difference ~18k-33k LSB), so the lag must be found by ENF matching, not sample matching. C1 does this with full-length NCC of ENF traces (`gt.py`, same extractor for both) and sub-second parabolic refinement.
- There is no wall-clock time or date anywhere in the dataset; ground truth is an offset (seconds) into the day file, which is exactly what we evaluate.
- Offsets between a recording and its own H1_ref: see "Measured alignment" below (filled from `gt_w16.json`).

## H1 vs H0
H1 = ENF present (test: correct offset within the right day reference). H0 = no ENF (any issued match is a false match). C1 also creates wrong-reference trials: an H1 excerpt searched in a *different* day's reference (any issued match is false); `check_ref_overlap.py` verifies the 28 days do not overlap in time.

## Measured alignment (gt.py, gt_w16.json) — answers the director's "~4 s shift" question
Same extractor on both sides (zero-phase Butterworth `sosfiltfilt`, delay-compensated `resample_poly`, frame i centred at i+8 s for every file, so there is no filter delay or start-vs-centre convention difference between H1 and H1_ref traces).
For each recording, the lag d maximising the correlation between the recording's ENF and its own H1_ref ENF (lags -30..+30 s, parabolic refinement); d>0 = recording trace at t+d matches reference at t.
- Reliable files (r at best lag >= 0.9): 57/85 dev, 12/45 holdout, 69/130 total.
- d over the 69 reliable files: median +0.56 s, range -4.95 .. +4.47 s; rounded histogram {-5:1, -3:2, -2:1, -1:16, 0:14, +1:8, +2:5, +3:16, +4:6}. Dev-only: median 0.56, range -3.39..+4.47.
- Conclusion: the offset is **per-file and not constant** (two clusters, near -1..0 s and near +3..+4 s), so it is a property of the dataset's recording/reference alignment (start-time logging precision of a few seconds), not a time-axis convention. A constant calibration cannot remove it, so dcal = 0.
- Consequences for scoring: the README ground truth is only trustworthy to about +-5 s. **Primary tolerance is +-5 s against README GT.** +-1 s accuracy is reported (a) against README GT (will be pessimistic) and (b) against a per-file *refined GT* = README lag - d_i, only for files with reliable d_i (r>=0.9). (b) uses the same recording's full-length trace against its own short reference (not the 24-h search), so it is a labelled secondary check, not the headline.

## Reference integrity audits
- One-day references: all 28 have 100% valid frames (|f-50|<0.5 Hz and peak/median >10 dB).
- No two day references overlap in time: 30-min chunks of each day searched in every other day give max NCC 0.811 (vs ~1.0 for true matches) — `ref_overlap_w16.json`. So wrong-reference trials are genuinely wrong.
- **Dataset artifact:** `089-107_ref.wav` contains whole hours that are repeated (42 of 138 ten-minute chunks have a second copy with NCC >= 0.995, RMS difference ~0.01 mHz, copies exactly 3600 s apart: e.g. 3600 -> 7200 s). Recordings 090 and 091 have their README ground truth inside the repeated hours (full-length NCC = 1.000 at 7 different lags, margin 0.000), so their timestamp is not identifiable from this reference. All other 27 day references have no duplicates (`dup_scan_w16.json`). Trials whose GT stretch has a duplicate copy are flagged `gt_ambiguous` and excluded from accuracy (count reported). This day is in DEV, so the holdout is unaffected.
- README GT match quality: ref-in-day NCC peak >= 0.97 for all 130 (min 0.9736, file 128); margins are >= 0.025 except 090/091 above.
