# C1 failure cases (real, from ENF-WHU; numbers from RESULTS.json / gt_w16.json / trials/*.parquet)

## 1. Recordings with no grid-tracking ENF (largest failure class)
These H1 recordings, despite being labelled "ENF captured", never match their own day's reference, and their full ~10-min trace matches **no** day of the 28 (best NCC 0.27-0.66, versus >=0.96 for genuine matches; checked for dev 016-019, 031, 035, 036).
- Dev: 016, 017, 018, 019 (the whole 016-019 day), 031, 035, 036. Example 018: harmonic-3 (150 Hz) line has median SNR ~900, yet its frequency track correlates 0.03 with the reference.
- Holdout: 022, 023, 024, 025 (the whole 020-025 day: very strong 100/150 Hz lines, SNR 300-660, whose frequency track does not follow the reference; r = -0.12..0.21), 005 (a rock-steady 250 Hz tone, SNR ~1600, frequency std 1.2 mHz, i.e. not ENF), 014 (no peak above noise; every frame fails the 0.05 Hz clip, so the matcher abstains with no score), 056 (r 0.43).
- Effect: these cause most abstentions. At 5 min on holdout, 30/135 trials abstained; recordings 005, 014, 022, 023, 024, 025 and 056 account for 21 of them (0/3 issued each).
- Cause: not determined. Plausibly hum from a source that does not follow the grid (a battery or inverter device, or a local generator). It is not a date mix-up inside the dataset, because no day matches.

## 2. Wrong-reference false matches exceed the 5% target
The threshold was set on pooled dev nulls (wrong-reference + H0) at 5%. H0 excerpts score lower than wrong-reference excerpts, so the pooled 5% hides a higher wrong-reference rate even on dev: 31/504 = 6.2% at 5 min. On holdout it is worse: 28/270 = 10.4% at 5 min, 23/270 = 8.5% at 3 min, 19/252 = 7.5% at 8 min. H0 false matches on holdout were 0/153 (1/36 at 8 min).
- The false matches cluster in a few recordings: holdout 051 (17), 011 (13), 055 (10), 029 (9); dev 120 (15), 129 (13), 119 (12). Most have clean ENF (011, 029, 119, 120 have rec-vs-ref r ~1.0). A smooth 2-10 min ENF excerpt, once its mean is removed, finds a lookalike somewhere in 86,400 candidate offsets of another day.
- So peak-NCC alone does not separate "right day" from "lookalike on a wrong day" well enough. In a 3-way search (own day vs the two sampled wrong days), the own day wins only 118/135 = 87.4% of holdout 5-min trials (supplementary.three_way_day_search).
- Fix candidates (not done; would need a fresh holdout look): calibrate on wrong-reference nulls separately; normalise the score by the number of effective independent samples; match on first differences or high-passed ENF; require consistency across sub-excerpts.

## 3. Ground truth itself has a few seconds of per-file scatter (dataset property)
The best lag between each recording's ENF and its own H1_ref ENF is not zero and not constant. Over 69 reliable files it ranges from -4.95 to +4.47 s, with clusters near -1..0 s and +3..+4 s (DATASET_NOTES.md). Our pipeline uses zero-phase filtering and the same frame convention on both sides, so this offset is in the data, not in our code.
- Consequence: accuracy within +-1 s against README GT is only 33-54% of issued matches (holdout). Against the per-file refined GT (README lag minus d_i, files with r>=0.9 only), it is 31/34 = 91% at 5 min, with median |err| 0.18 s. All issued correct-reference matches are within +-5 s of README GT (105/105 at 5 min), which is the tolerance we can defend.

## 4. Duplicated hours in a reference file (dataset artifact)
`H1_ref_one_day/089-107_ref.wav` repeats whole hours: 42/138 ten-minute chunks have an identical copy exactly 3600 s away. Recordings 090 and 091 therefore have 7 equally perfect offsets (README GT margin 0.000), so their timestamp cannot be identified. Trials whose GT stretch is duplicated are excluded from accuracy and counted in `h1_excluded_ambiguous_gt` (dev: 25 at 1 min, 11 at 2 min, 6 at 3-8 min). This day is in DEV only.

## 5. Interference tone captured by the tracker (057)
`plots/spectrogram_interference_057.png`: a steady tone at ~250.8 Hz (50.16 Hz fundamental-equivalent) captures the combined tracker for about 45% of frames, so the track jumps between ENF (~50.00) and the tone. The +-0.05 Hz clip around the file median removes those frames (only 106/300 frames used in the plotted excerpt), and the match still succeeded (err -0.84 s). But 057 also produced 5 wrong-reference false matches. A continuity-constrained tracker (Viterbi or multi-trace carving) and stationary-tone rejection would help here.

## 6. Short excerpts
At 1 min, the dev null pushes the threshold to NCC 0.9976, and holdout coverage is 9/135 = 6.7%. Top-1 without a threshold is correct (+-5 s) for only 25% of trials. Two minutes or more is the useful range (coverage 29% at 2 min, 53% at 3 min, 78% at 5 min).

## 7. 10-minute point is thin
Only 23 holdout and 26 dev recordings are >= 616 s long (most recordings are about 600 s, minus a 16 s window), and H0 has only 1 holdout file that long (9 trials). Treat the 10-min point and its false-match rate as low-n.
