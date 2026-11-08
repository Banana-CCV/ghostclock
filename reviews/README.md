# Independent verification (director reviews)

These scripts are a key traceability asset. Before any number reached the evidence pack, the director (separate from the workstream or worker that produced the number) re-derived it with **separate, deliberately simple code**: from the raw trial table, the saved traces, or the raw reference files, not by re-running the worker's pipeline. All four were re-run on 08 Nov 2026 during release packaging, and their outputs are saved in [outputs/](outputs/).

| Script | Checks | Inputs | Result (saved output) |
|---|---|---|---|
| [director_verify_c1.py](director_verify_c1.py) | C1 holdout coverage, ±5 s accuracy and false matches for every clip length, recomputed from the trial table and the frozen thresholds | committed: [trial table](../experiments/c1_enfwhu_unseen_holdout/trials/final_w16_q_clip05_holdout.parquet), [frozen.json](../experiments/c1_enfwhu_unseen_holdout/frozen.json) | [all counts match](outputs/director_verify_c1.txt), e.g. 5 min: 105/135, 105/105, wrong-day 28/270, H0 0/153 |
| [director_verify_c4.py](director_verify_c4.py) | Video r recomputed over every lag from 0 to 252.5 s | committed: saved RS and reference traces | [best lag 81.5 s, r = 0.9954, n = 633, debiased RMSE 1.07 mHz, best r more than 10 s away 0.685](outputs/director_verify_c4.txt) |
| [director_verify_c2.py](director_verify_c2.py) | Elexon archive liveness; NESO-vs-Elexon RMSE by lag for Nov 2025 and Sep 2026 | GB parquet files (not committed; `GHOSTCLOCK_GB_DIR`) | [0.59 mHz (Nov 2025) vs 7.45 mHz (Sep 2026) at lag 0; about 85–88 mHz at ±3600 s](outputs/director_verify_c2.txt) |
| [director_verify_w06.py](director_verify_w06.py) | W06 extractor on ENF-WHU H1/003 against a reference ENF computed independently with a plain STFT | ENF-WHU + W06 smoke trace (not committed; `GHOSTCLOCK_WORKSPACE`) | [r = 0.9760 at lag 0, 0.9993 at −4 s; RMSE 5.48 mHz](outputs/director_verify_w06.txt) |

Written reviews: [director_W06_smoke.md](director_W06_smoke.md) and [director_W17.md](director_W17.md). The second downgrades the simulated "framing tournament" scores to grade D and flags unverified figures. [W10_audit_summary.md](W10_audit_summary.md) is worker W10's audit of sibling studies and baselines (a Gemini worker; not a director review).

Run from the repo root: `python reviews/director_verify_c1.py` and `python reviews/director_verify_c4.py` work out of the box.
