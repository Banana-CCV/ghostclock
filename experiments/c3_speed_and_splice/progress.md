# C3 progress log (Sun 8 Nov 2026)

- Read ENF-WHU README: H1 = 130 real recordings with ENF (8 kHz mono, 5-20 min, Wuhan, 50 Hz grid), H1_ref_one_day names give day groups (28), H0 = O01..O10 long no-ENF recordings + 40 random crops 01..40.
- Mapped the 40 H0 crops to their source O-file by normalised cross-correlation (`_map_h0.py` -> `h0_crop_map.json`). Map is imperfect: min NCC 0.368, and O01/O10 received no crops. Only O-files are used for H0 evaluation, so the map only matters for listing crops in the split.
- Froze split (`make_split.py` -> `split.json`, seed 20261108) BEFORE any tuning: H1 dev 85 recs / 13 day groups, holdout 45 recs / 15 day groups (65/35 by recordings; greedy group assignment overshot 60 % because one day has 19 recordings). H0 dev sources O02,O04,O05,O06,O07,O09; holdout O01,O03,O08,O10.
- Verified grid limits: ESQCR 2002 reg. 27(3)(a) permits +/-1 % of declared 50 Hz; NESO operates within 49.8-50.2 Hz normally (statutory 49.5-50.5 Hz).
- Wrote `speed_check.py` (comb search 25-120 Hz, k=1 hypothesis tests, bootstrap CI) and `splice_check.py` (narrow-band ENF phase tracking, jump statistic).
- Machine was heavily loaded by other workers (Python import alone took ~90 s), so the eval was budgeted: one seeded source segment per H1 recording, atempo at 8 s and 30 s only, splices at 15 s and 30 s.
- Test run on rec 090 exposed a bug in splice_check.pick_line (compared frequency instead of SNR) and an over-wide band-pass (+/-1 Hz -> in-band SNR < 0 dB). Fixed: strongest line up to 950 Hz, band +/-(0.2+0.03n) Hz, w = 1 s. Buggy test rows moved to eval/features_test_run_buggy.jsonl (unused).
- Full run: 140 jobs, 13,980 feature rows (eval/features.jsonl).
- Tuned on DEV only (FAR target 5 % on unmodified H1 and on H0): speed lam=3.0, s_k1=8, s_alt=30, margin=inf, min_lines_alt=2 (dev FAR 4.7 %, dev TPR 39.5 %); splice t_line=20 dB, theta=1.55 rad (dev FAR 4.9 % on clips with a line).
- Holdout report -> RESULTS.json. Headline: 8 s @ 1.75x TPR 20/45 = 44 % [31, 59]; FAR unmodified 18/225 = 8.0 % [5.1, 12.3]; atempo flagged 3/990; H0 120/120 NO_GRID_SIGNAL.
- ci_check.py: the bootstrap CI is far too narrow (precision only); the grid-band CI covers k=1 in 19/24 (8 s). k_hat often follows a non-mains tonal family -> recorded in FAILURES.md.
- Plots in plots/. The demo spectrum uses DEV recording 090 (clean example); holdout recording 065 had no usable hum at 8 s.
