# W02 Experiment & Engineering Plan: GB Reference Data (NESO + Elexon)

## 1. Objectives & Scope
As owner of Great Britain (GB) grid-frequency reference data (`W02`), our goal is to empirically characterise, download, standardise, and cross-validate the two primary official GB grid frequency sources—**NESO Historical System Frequency (1 s)** and **Elexon BMRS System Frequency (~15 s)**—and determine whether any public $\le 1\text{ s}$ low-latency feed exists for same-day live demonstrations.

All outputs strictly adhere to the frozen interface in `integration/interfaces.md` §2.

---

## 2. Input / Output Schema (`integration/interfaces.md` §2)
- **Data File (`.parquet`):**
  - `ts_utc`: `int64` — Unix epoch timestamp in **seconds** (UTC), strictly increasing at regular steps of `cadence_s`. Any missing grid readings within a file's `[start_utc, end_utc]` span are regularised onto the exact integer grid with `f_hz = NaN` (or documented before/after regularisation) so downstream matchers (`W10`) can assume a uniform grid.
  - `f_hz`: `float64` — Measured GB mains frequency in Hz (nominal $50.000\text{ Hz}$).
  - `source` (optional column): `string` (`"NESO"` or `"ELEXON"`).
- **Sidecar Metadata (`.json`):**
  ```json
  {
    "source": "NESO",
    "cadence_s": 1,
    "grid": "GB",
    "coverage": [1761955200, 1764547199],
    "url": "https://...",
    "sha256": "<sha256-of-parquet-file>",
    "raw_sha256": "<sha256-of-raw-csv-or-json>",
    "row_count": 2592000,
    "valid_count": 2592000,
    "missing_count": 0,
    "licence": "..."
  }
  ```
- **Python API (`work/W02/gb_reference.py`):**
  - `load_reference(start_utc: int, end_utc: int, source: str = "NESO") -> pd.DataFrame` returning columns `["ts_utc", "f_hz"]` sorted by `ts_utc` in `[start_utc, end_utc]`.
  - CLI: `python work/W02/gb_reference.py --start-utc <int|ISO> --end-utc <int|ISO> --source <NESO|ELEXON|AUTO> [--out <path>]`
- **Live Archiver (`work/W02/elexon_archiver.py`):**
  - Polls Elexon BMRS API every $N$ minutes (plus `--once` mode for deterministic testing and immediate backfilling) and appends deduplicated rows sorted by `ts_utc` to `datasets/raw/elexon/live_archive.parquet` (with updated sidecar `.json`).

---

## 3. Research & Discovery Tasks
1. **NESO CKAN API (`https://api.neso.energy/api/3/action/package_show?id=system-frequency-data`):**
   - Enumerate all historical monthly resources, their coverage months, UUIDs, exact download URLs, update timestamps, and licences.
   - Download the **most recent 3 available months** plus **Nov 2025** (if not already among the top 3; if Nov 2025 is in the top 3, also include an October/March BST transition month so BST/GMT transition behaviour is explicitly tested on authentic data).
   - Inspect timestamp format, timezone convention (UTC vs Europe/London BST/GMT), cadence, gaps, and value quantisation step size (e.g., $1\text{ mHz} = 0.001\text{ Hz}$).
2. **Elexon BMRS API (`https://data.elexon.co.uk/bmrs/api/v1/system/frequency` and `/stream`):**
   - Measure live response cadence, latency relative to request UTC clock, max query window on standard vs stream endpoints, historical retention depth, rate limits, and value precision.
   - Fetch the **last 7 days plus today**, convert to frozen Parquet + sidecar JSON under `datasets/raw/elexon/`.
3. **Alternative $\le 1\text{ s}$ Public GB Feeds:**
   - Programmatically probe candidate endpoints (NESO Data Portal other frequency packages, UK Gridwatch / Templar, Dynamic Demand, Energy Dashboard, iamkate, OpenPMU / Power-Grid Frequency Database) and verify actual response cadence and latency.

---

## 4. Cross-Check Experimental Design (NESO 1 s vs Elexon 15 s)
To determine how Elexon (~15 s) relates to NESO (1 s) and whether Elexon can substitute for NESO:
- **Overlapping Dataset & Split:**
  - Identify an overlapping time span where both NESO 1 s and Elexon 15 s data exist (fetching a matching 7-day Elexon historical window overlapping our downloaded NESO months if NESO lags behind the last 7 days).
  - **Development split (first 70% of overlapping timestamps):** Fit/identify:
    1. Exact timestamp alignment lag $\tau \in [-60, +60]\text{ s}$ between Elexon `measurementTime` and NESO `dtm`.
    2. Sampling operator hypothesis: Is Elexon an instantaneous point sample (decimation $f_{\text{NESO}}(t + \tau)$) or a Causal/Centred Moving Average over window $W \in \{1, 5, 10, 15, 30, 60\}\text{ s}$?
    3. Upsampling reconstruction baseline (Zero-Order Hold / Nearest) vs improved interpolation (Linear vs Cubic Spline / PCHIP) from 15 s Elexon back to 1 s NESO grid.
  - **Holdout split (remaining 30% of overlapping timestamps):** Evaluate out-of-sample RMSE (mHz), MAE (mHz), max absolute error (mHz), and Pearson correlation $r$ at both 15 s native timestamps and 1 s reconstructed timestamps, plus short-window (60 s, 180 s, 600 s) correlation degradation.

---

## 5. Falsifiable Success Thresholds
1. **H1 (Telemetry Equivalence at 15 s):** At optimal lag $\tau$ and window $W$ selected on Dev, Holdout RMSE between Elexon and NESO at 15 s steps is $\le 2.0\text{ mHz}$ with Pearson $r \ge 0.99$. *Falsified if Holdout RMSE $> 5.0\text{ mHz}$.*
2. **H2 (15 s Upsampled Substitute for 1 s NESO):** When Elexon 15 s is interpolated to 1 s on Holdout, overall 1 s RMSE must be $\le 5.0\text{ mHz}$, and on 60 s sliding windows the median correlation between 1 s NESO and interpolated Elexon must exceed $r = 0.90$. *If 60 s sliding-window correlation drops below $0.85$ on $>20\%$ of windows due to sub-15 s grid dynamics, we falsify Elexon as a reliable drop-in substitute for short ($\le 60\text{ s}$) clips and require longer clip durations or 1 s reference data.*
3. **H3 (Same-Day 1 s Public Feed Availability):** A same-day live demo at 1 s resolution is possible via public APIs *only if* a verified public endpoint serves GB frequency at cadence $\le 1\text{ s}$ with latency $\le 15\text{ minutes}$. *Falsified if NESO 1 s lags by days/weeks and all live public GB endpoints are $\ge 15\text{ s}$ cadence or offline.*

---

## 6. Expected Failure Modes & Safeguards
- **BST/GMT Daylight Saving Transition Errors:** If NESO stores local UK time or changes date formats across months, naive parsing shifts timestamps by 3600 s during BST (late March to late October) or creates duplicate/missing hours on transition days. We will explicitly inspect transition timestamps and verify against Elexon's ISO-8601 `Z` (UTC) timestamps.
- **Elexon 24-Hour Query Span Limit:** Standard `/system/frequency` rejects or truncates queries $>24\text{ h}$. We will chunk multi-day fetches into $\le 24\text{ h}$ windows (or use `/system/frequency/stream`) and verify completeness.
- **Aliasing / Subsampling Loss:** 15 s sampling has a Nyquist frequency of $1/30\text{ Hz} \approx 0.033\text{ Hz}$. Any ENF fluctuation with period $<30\text{ s}$ is lost or aliased in Elexon data.
