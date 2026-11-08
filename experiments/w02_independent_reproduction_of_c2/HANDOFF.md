# W02 Handoff: GB Grid-Frequency Reference Data (`NESO` + `ELEXON`) & C2 Reproduction

---

## 1. Components Worth Keeping for the Final Build

1. **Frozen Reference Loader (`work/W02/gb_reference.py`)**:
   - Exposes `load_reference(start_utc: int, end_utc: int, source: str = "NESO") -> pd.DataFrame[ts_utc, f_hz]` conforming to [`integration/interfaces.md`](../../docs/INTERFACES.md) §2.
   - Enforces the physical GB grid frequency gate `[47.0, 52.0] Hz` (rejecting Elexon `0.0 Hz` SCADA dropout sentinels), masks NESO flat-filled outages ($\ge 120\text{ s}$ constant runs such as `2026-09-15` `11,158 s` and `2026-03-31` `479 s`), and encodes the complete 21-month timezone offset rule via `NESO_BST_SHIFTED_MONTHS = {"2025-04", ..., "2025-10"}` (`-3600 s` correction).
   - Supports on-demand Elexon streaming (`/bmrs/api/v1/system/frequency/stream`) when a requested range is not cached locally.
2. **Frozen Parquet + Sidecar JSON Datasets (`datasets/raw/neso/` and `datasets/raw/elexon/`)**:
   - **NESO 1 s (`datasets/raw/neso/`)**: `neso_2026-09.parquet`, `neso_2026-08.parquet`, `neso_2026-07.parquet`, `neso_2026-03.parquet`, `neso_2025-11.parquet`, `neso_2025-10.parquet` (`15,897,600` 1 s rows converted to Parquet + raw CSVs for `2025-12`, `2026-01`, `2026-02` = `23,673,600` total 1 s rows on disk).
   - **Elexon 15 s (`datasets/raw/elexon/`)**: `elexon_last7d_and_today.parquet` (`2026-11-01` to `2026-11-08`), `live_archive.parquet` (`42,840` rows), `elexon_overlap_2026_09.parquet`, `elexon_overlap_2025_11.parquet`, `elexon_dst_2025_10_26.parquet`, `elexon_dst_2026_03_29.parquet`.
   - *Note*: `C2`'s live archiver (`PID 38996` $\to$ `datasets/raw/gb/elexon_live.parquet`) is already running in the background; per Director instruction, W02 did not launch a duplicate daemon. [`work/W02/elexon_archiver.py --once`](elexon_archiver.py) remains available for one-shot refreshes of `datasets/raw/elexon/live_archive.parquet`.
3. **Independent Reproduction of C2 (`agents/reviews/W02_reproduce_C2.md`)**:
   - Confirms C2's findings on Oct 2025 (`+3600 s` BST shift), NESO flat-filled outages, Elexon `0.0 Hz` placeholders, and the 24 h feasibility table ($n = 400$).
   - Adds three discoveries C2 missed: (a) **all seven 2025 BST months (`2025-04..2025-10`)** are shifted by `+3600 s` whereas all 2026 BST months (`2026-04..2026-09`) are true UTC; (b) **auditing Dec 2025, Jan 2026, and Feb 2026** pinpoints the exact onset of the 2026 Elexon scatter to **`2026-02-13`** (after a `+1 s` clock-skew transition from `2026-01-13` to `2026-02-11`, and exact `89.4%` agreement throughout Dec 2025 and Jan 1–11 2026); (c) **linearly interpolating Real Elexon 15 s to 1 s (`ref_elexon_real_lin1s`)** improves 5-min and 10-min localization recall from `73.3%` $\to$ **`80.5%`** and `96.5%` $\to$ **`98.5%`** (halving the 10-min miss rate compared to 15 s point matching).

---

## 2. Deck-Worthy Figures in `work/W02/plots/` (with Mandatory One-Line Captions)

1. [`work/W02/plots/c2_reproduction_transition_and_feasibility.png`](plots/c2_reproduction_transition_and_feasibility.png)
   - **Caption**: `REAL-MEASURED (left) / SEMI-SYNTHETIC (right): Daily NESO-vs-Elexon RMSE across Dec 2025–Feb 2026 pinpointing the exact 2026-02-13 scatter transition (left), and independent n=400 reproduction of 24-hour top-1 ENF localization recall showing 1 s linear interpolation of Real Elexon 15 s reaching 80.5% at 5 min and 98.5% at 10 min (right).`
2. [`work/W02/plots/sep2026_vs_nov2025_lag_and_regime_diagnosis.png`](plots/sep2026_vs_nov2025_lag_and_regime_diagnosis.png)
   - **Caption**: `REAL-MEASURED: Full [-3700, +3700] s lag sweep on Sep 2026 vs Nov 2025 (confirming strict tau = 0 s UTC alignment) and 21-month NESO-vs-Elexon audit (2025-01 to 2026-09) revealing the +3600 s BST export shift across all seven 2025 summer months (2025-04..2025-10) versus strict UTC in all 2026 months.`
3. [`work/W02/plots/neso_vs_elexon_crosscheck.png`](plots/neso_vs_elexon_crosscheck.png)
   - **Caption**: `REAL-MEASURED: Dev/Holdout cross-check of NESO 1 s vs Elexon 15 s showing exact 15 s point decimation (0.72 mHz Dev / 0.58 mHz Holdout RMSE in Nov 2025 vs 7.34 mHz for 15 s moving average), 180 s trace overlay, and sliding-window correlation vs clip duration D (15 s to 600 s).`
4. [`work/W02/plots/elexon_nov2025_dropout_failure_case.png`](plots/elexon_nov2025_dropout_failure_case.png)
   - **Caption**: `REAL-MEASURED: Real Elexon BMRS 0.0 Hz SCADA telemetry dropout on 2025-11-06T18:33:45Z (true NESO grid frequency 50.088 Hz) before and after the [47.0, 52.0] Hz physical range gate, which reduces 7-day RMSE from 249.45 mHz to 0.68 mHz.`

---

## 3. Deck-Worthy Numbers for Judges (`W17` Pitch Deck & `W10`/`W18` Gates)

* **Scale of Real Data Verified**: **23,673,600** 1-second NESO rows across 9 full months + 21-month streaming audit (`2025-01`..`2026-09`), cross-checked against **500,000+** Elexon BMRS 15-second rows (`2021-08-30` to `2026-11-08`).
* **Risk Control / Gate #1 (Physical Frequency Gate `[47.0, 52.0] Hz` + Flat-Run Outage Gate $\ge 120\text{ s}$)**: Catches real Elexon `0.0 Hz` SCADA dropouts (`1` in Nov 2025, `167` in Jan 2026, `732` in Feb 2026) and NESO constant-fill outages (`11,158 s` at `49.895 Hz` on `2026-09-15`; `479 s` at `50.046 Hz` on `2026-03-31`).
* **Risk Control / Gate #2 (NESO 2025 BST Timezone Trap)**: All seven 2025 summer months (`2025-04..2025-10`) in NESO's official archive are stamped in `UTC+1` (`+3600 s`), whereas all 2026 summer months (`2026-04..2026-09`) are in `UTC+0`. Without W02/C2's `-3600 s` correction, every summer/autumn 2025 insurance claim would be mis-dated by exactly 1 hour (`RMSE = 80.31 mHz` $\to$ `0.70 mHz`).
* **Risk Control / Gate #3 (Minimum Clip Duration Gate for 15 s Elexon)**: Same-day Elexon 15 s data (`32–142 s` live latency) requires **$D \ge 5\text{ min}$ (`80.5%` top-1 recall with 1 s linear interpolation)** or **$D \ge 10\text{ min}$ (`98.5%` recall)** over a 24 h search window; clips $\le 2\text{ min}$ (`18.0%` recall) must trigger an automatic `INCONCLUSIVE` abstention unless a 1 s reference (`NESO` historical or `LOCAL_STATION` live) is available.
