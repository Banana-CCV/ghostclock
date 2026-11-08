# Experiments

One folder per study. Each contains the scripts as run, a README with the run commands, `RESULTS.json` (metrics with denominators), `FAILURES.md` and plots. Raw data, media and caches are excluded. Scripts refer to the original workspace layout (`<WORKSPACE>/work/<ID>/`, `<WORKSPACE>/datasets/raw/...`), so to re-run one, recreate that layout or edit the path constants at the top of the script. The reusable, path-portable versions of the key modules are in [`ghostclock/`](../ghostclock/README.md).

Studies `c*` are the team's engineering workstreams (WS-C1 to WS-C5). Studies `w*` were run by Gemini 4 Argon worker agents and are **not independently re-verified** unless the Verification column says otherwise.

| Folder | Study | Data | Grade | Verification |
|---|---|---|---|---|
| [c1_enfwhu_unseen_holdout](c1_enfwhu_unseen_holdout/README.md) | End-to-end audio dating on ENF-WHU, frozen dev → one holdout run | REAL | **A** | Director recomputed every count ([script](../reviews/director_verify_c1.py)) |
| [c2_gb_reference_and_feasibility](c2_gb_reference_and_feasibility/README.md) | GB reference (NESO 1 s, Elexon 15 s), data traps, feasibility vs clip length | REAL / SEMI-SYNTHETIC | A (feasibility, via W02) / B | Director spot check ([script](../reviews/director_verify_c2.py)); W02 reproduction |
| [c3_speed_and_splice](c3_speed_and_splice/README.md) | No-reference speed and splice checks | REAL audio + SYNTHETIC edits | B | Not reproduced |
| [c4_video_rolling_shutter](c4_video_rolling_shutter/README.md) | Video ENF from rolling-shutter flicker | REAL (1 clip) + SYNTHETIC | B | Director recomputed r over all lags ([script](../reviews/director_verify_c4.py)) |
| [c5_argon_agent](c5_argon_agent/README.md) | Gemini 4 Argon investigator loop with a code gate: 5 real cases plus 2 no-Argon ablations | REAL (logged Argon runs) | B | Release engineer re-read the reports; runs not repeated |
| [w02_independent_reproduction_of_c2](w02_independent_reproduction_of_c2/README.md) | Independent reproduction of C2 plus a 21-month timezone audit | REAL / SEMI-SYNTHETIC | A (the reproduction itself) | It *is* the independent check of C2 |
| [w06_audio_extractor](w06_audio_extractor/README.md) | Multi-harmonic consensus audio extractor, ENF-presence detector, codec robustness | REAL (dev only) | B | Director reproduced on 1 clip ([script](../reviews/director_verify_w06.py)) |
| [w10_matcher_and_null_calibration](w10_matcher_and_null_calibration/README.md) | Matcher, look-elsewhere null calibration, decision policy, baselines | REAL / SEMI-SYNTHETIC | B | **Not independently re-verified** |
| [w11_uniqueness_math](w11_uniqueness_math/README.md) | Uniqueness and feasibility mathematics, settlement-boundary volatility | REAL NESO / SEMI-SYNTHETIC | B | **Not independently re-verified** (its README self-grades A; the director grades it B) |
| [w12_reference_station](w12_reference_station/README.md) | Live local reference station prototype | REAL / SYNTHETIC | B | **Not independently re-verified**; feeds no reported metric |
| [w14_redteam_guards](w14_redteam_guards/README.md) | Red-team attack families and guards | — | **Incomplete** | Code and plan only, **no results produced** |
| [team_recordings_venue](team_recordings_venue/README.md) | **Hero:** the team's 18.4-min venue video dated blind against 36 h of live GB data, 2 s from the camera clock; a 49 s clip correctly abstains | REAL | B (2 s from the camera clock; one recording) | Blind search re-run from the committed trace during packaging: identical |
