# W02 Progress Log: GB Reference Data (`NESO` + `Elexon`) & Independent Reproduction of `C2`

## `[orient]` — 2026-11-08T09:50:00Z
- Read `AGENTS.md`, `sources/interfaces.md`, `sources/agentverse-brief.md`, `sources/ucl-agentverse-deck.txt`, `sources/shadowstop-demo-deck.html`, and `agents/status/W02.json`.
- Confirmed contract requirements:
  1. Discover NESO historical system frequency CKAN API/datastore, list all available months and latest month, download recent 3 months (`2026-09`, `2026-08`, `2026-07`) + `2025-11` (and DST boundary months `2026-03`, `2025-10`, plus winter transition months `2025-12`, `2026-01`, `2026-02`), inspect timestamp/timezone/BST-GMT/cadence/gaps/quantisation, and write frozen Parquet + sidecar `.json` + `sha256` to `datasets/raw/neso/`.
  2. Call Elexon BMRS `/datasets/FREQ` and `/datasets/FREQ/stream`, measure cadence (`15 s`), history depth (`2020-01-01`), max query span (`7 days` on `/datasets/FREQ`, unlimited on `/datasets/FREQ/stream`), live latency (`~17–47 s`), rate limits, timezone (`UTC`), and save last 7 days + today to `datasets/raw/elexon/` in frozen format.
  3. Cross-check Elexon vs NESO on overlapping periods (Nov 2025 + Sep 2026 + Dec 2025–Feb 2026 transition) with 70% Dev / 30% Holdout split, full $\tau \in [-3700, +3700]\text{ s}$ lag sweeps, and sub-second spline / 31-tap FIR / AR(1)+white-noise diagnostics.
  4. Implement `work/W02/gb_reference.py` (`load_reference(start_utc, end_utc, source)` + CLI) and `work/W02/elexon_archiver.py` (deduplicating live archiver writing `datasets/raw/elexon/live_archive.parquet`).
  5. Audit alternative public GB frequency sources at $\le 1\text{ s}$.
  6. Act as the **Independent Reproducer of `C2`** (`agents/reviews/W02_reproduce_C2.md`), verifying the `2025-10` `+3600 s` offset, auditing all 21 NESO monthly files (`2025-01`..`2026-09`), pinpointing the exact start date of the 2026 Elexon scatter (`2026-02-13`), verifying NESO flat-filled outages (`2026-09-15` and `2026-03-31`), and independently reproducing C2's 24 h feasibility table ($n = 400$, $\sigma = 2\text{ mHz}$).

## `[first-result]` — 2026-11-08T10:15:00Z
- Discovered NESO CKAN package `47a138f7-0f05-4046-bf69-9723d893282f` (`55` monthly CSV resources `2022-03` through `2026-09`, latest `2026-09-30T23:59:59Z`).
- Converted 6 core NESO monthly archives (`2026-09`, `2026-08`, `2026-07`, `2026-03`, `2025-11`, `2025-10`) to `datasets/raw/neso/neso_<YYYY-MM>.parquet` + `.json` (`15,897,600` rows).
- Fetched Elexon last 7 days + today (`datasets/raw/elexon/elexon_last7d_and_today.parquet`, `live_archive.parquet`, `42,840` rows) and overlap windows (`2026-09`, `2025-11`, `2025-10-26`, `2026-03-29`).
- Ran initial cross-check (`work/W02/crosscheck_neso_elexon.py` -> `work/W02/crosscheck_results.json`): Nov 2025 Holdout RMSE = `0.6776 mHz` ($r = 0.999962$), Sep 2026 Holdout RMSE = `6.5204 mHz` ($r = 0.996390$).

## `[verify]` — 2026-11-08T10:30:00Z
- Verified `work/W02/gb_reference.py` CLI and Python API on both `NESO` (`601` rows returned for 10 min) and `ELEXON` (`61` rows returned for 15 min).
- Verified `work/W02/elexon_archiver.py --once` (`42,840` deduplicated rows in `datasets/raw/elexon/live_archive.parquet`, latency `32.0 s`, sha256 `85151fbbdb96039967677c98d390b3a0702e2c0cc87324768c1f237daee420e4`). Did NOT start a second background archiver daemon per Director instruction (C2's archiver `PID 38996` is already active).

## `[revision]` — 2026-11-08T10:55:00Z
- **Director Note Lag Sweep & 21-Month Audit (`work/W02/diagnose_sep2026_and_all_months_lags.py` -> `work/W02/director_note_lag_diagnosis.json`)**:
  - Swept $\tau \in [-3700, +3700]\text{ s}$ on full Sep 2026 (`N = 172,800`): global optimum is strictly $\tau = 0\text{ s}$ (`RMSE = 6.3227 mHz`), whereas $\tau = \pm 3600\text{ s}$ gives `~106.5 mHz` ($r \approx 0$).
  - Audited all 21 NESO monthly files (`2025-01`..`2026-09`): all seven 2025 BST months (`2025-04`..`2025-10`) have a `+3600 s` (`UTC+1`) shift in NESO, including the 5 GMT days at the end of `2025-10`. Every 2026 month (`2026-01`..`2026-09`, including all 2026 BST summer months) is strict `UTC+0` ($\tau = 0\text{ s}$).
- **Independent Reproduction of `C2` & Dec 2025–Feb 2026 Transition Audit (`work/W02/reproduce_c2_and_transition.py` -> `work/W02/c2_reproduction_results.json`)**:
  - Downloaded full months `2025-12`, `2026-01`, and `2026-02` (`7,776,000` 1 s rows) to `datasets/raw/neso/` and `datasets/raw/elexon/` (`23,673,600` total NESO rows across 9 monthly Parquets).
  - Pinpointed the exact transition timeline:
    - **Dec 2025 (`31/31` days) & Jan 1–11 2026 (`11/11` days)**: Pure point-sample equivalence at $\tau = 0\text{ s}$ (`0.50–0.65 mHz` typical daily RMSE, `85.8%–90.7%` exact match).
    - **Jan 13 – Feb 11 2026 (`30` days)**: `+1 s` clock skew between feeds (`best_lag = +1 s` on `26/30` days, median daily RMSE `1.65 mHz` at `+1 s`, `0.0 mHz` extra white noise).
    - **Starting `2026-02-13`**: `best_lag` returned permanently to `0 s` (`16/16` days Feb 13–28) while the **`3.5–6.3 mHz` independent transducer scatter began permanently** (`frac_exact` dropped from `27.3%` on Feb 12 to `8.2%–12.8%` on Feb 13–28).
  - Confirmed C2's flat-filled NESO outages (`2026-09-15` `11,158 s` at `49.895 Hz` and `2026-03-31` `479 s` at `50.046 Hz`) and discovered that Elexon BMRS remained **100% live and dynamic** during NESO's 3.1-hour `2026-09-15` outage (`744/744` valid 15 s rows, `49.838–50.121 Hz`).
  - Reproduced C2's 24 h feasibility table ($n = 400$, $\sigma = 2\text{ mHz}$, `seed = 20261108`) within $\pm 2.3\%$, and showed that **1 s linear interpolation of Real Elexon (`ref_elexon_real_lin1s`)** improves top-1 dating accuracy to `0.180` (2m), `0.805` (5m), `0.985` (10m), and `0.998` (20m).

## `[final]` — 2026-11-08T11:04:00Z
- Wrote independent review `agents/reviews/W02_reproduce_C2.md` (and copy `work/W02/W02_reproduce_C2.md`).
- Generated all 4 deck-worthy plots in `work/W02/plots/` (and `work/W02/figures/`).
- Completed `work/W02/RESULTS.json`, `work/W02/FINDINGS.md`, `work/W02/FAILURES.md`, `work/W02/HANDOFF.md`, and `work/W02/README.md`.
- Updated `agents/status/W02.json` to `"status": "DONE"`.
