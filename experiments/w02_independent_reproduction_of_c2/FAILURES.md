# W02 Failures, Pitfalls & Real-World Data Anomalies Caught

Every failure mode below was encountered in real GB reference data or during pipeline execution, quantified, and mitigated in production code ([`gb_reference.py`](gb_reference.py), [`elexon_archiver.py`](elexon_archiver.py), and [`fetch_and_inspect_neso_elexon.py`](fetch_and_inspect_neso_elexon.py)).

---

## 1. Failure Case 1: Raw `0.0 Hz` SCADA Dropout Sentinel in Elexon BMRS (`2025-11-06T18:33:45Z`)
* **Symptom**: On the 7-day November 2025 overlap dataset (`2025-11-01` to `2025-11-07`, $N = 40,320$), initial unfiltered cross-check against NESO 1 s gave an alarming **`RMSE = 249.4451 mHz`** and **`Pearson r = 0.293448`**, despite **`88.48%`** of timestamps matching to `0.000 Hz`.
* **Root Cause**: At a single 15 s timestamp—**`2025-11-06T18:33:45Z` (`ts_utc = 1762454025`)**—Elexon BMRS emitted `frequency = 0.0 Hz` (a SCADA telemetry dropout sentinel) while the true GB grid frequency recorded by NESO was **`50.088 Hz`** ($|\Delta f| = 50,088\text{ mHz}$).
* **Code Mitigation**: Enforced a physical GB grid frequency gate **`[47.0, 52.0] Hz`** in [`gb_reference.py`](gb_reference.py), [`elexon_archiver.py`](elexon_archiver.py), and [`fetch_and_inspect_neso_elexon.py`](fetch_and_inspect_neso_elexon.py), converting out-of-range sentinel values to `NaN` on the regularised grid and recording them in the sidecar JSON (`"raw_anomalies_gated"`).
* **Measured Impact**: Filtering that single sample reduced 7-day November 2025 RMSE from **`249.4451 mHz` to `0.6783 mHz`** and increased Pearson $r$ from **`0.293448` to `0.999962`** (see [`elexon_nov2025_dropout_failure_case.png`](figures/elexon_nov2025_dropout_failure_case.png)).

---

## 2. Failure Case 2: NESO 2025 Summer Months (`2025-04`..`2025-10`) Exported in BST (`UTC+1`, `+3600 s`) + 1-Hour Gap on `2025-10-31T23:00Z`
* **Symptom**: When testing the UK autumn clock change (`2025-10-26 01:00Z`, BST$\to$GMT) using `fnew-2025-10.csv`, naive UTC parsing produced **`RMSE = 80.3095 mHz`** and **`Pearson r = 0.307679`** against Elexon BMRS (`n = 1,921`).
* **Root Cause**: Our 21-month audit ([`diagnose_sep2026_and_all_months_lags.py`](diagnose_sep2026_and_all_months_lags.py)) proved that in **2025**, NESO exported all seven summer-time monthly CSVs (`2025-04`, `2025-05`, `2025-06`, `2025-07`, `2025-08`, `2025-09`, `2025-10`) with `dtm = UTC + 3600 s` (**BST / `UTC+1`**) across the **entire file**—including the final 5 GMT days of October 2025 after `2025-10-26 01:00Z`! Specifically:
  - The first row of `fnew-2025-10.csv` (`2025-10-01 00:00:00, 50.021`) actually occurred at **`2025-09-30T23:00:00Z`** (verified against Elexon `2025-09-30T23:00:00Z..2025-10-01T00:00:00Z`: `RMSE = 0.4596 mHz`, $r = 0.999962$, `90.04%` exact `0.000 Hz` match).
  - The last row of `fnew-2025-10.csv` (`2025-10-31 23:59:59`) actually occurred at **`2025-10-31T22:59:59Z`**, leaving an unrecorded **1-hour gap (`2025-10-31T23:00:00Z..23:59:59Z`)** before `fnew-2025-11.csv` starts at true UTC `2025-11-01T00:00:00Z`.
  - Starting in **`2025-11` and continuing through all of `2026` (`2026-01`..`2026-09`)**, NESO fixed its export pipeline to output **strict UTC (`lag = 0 s`) year-round**, including all 2026 BST summer months (`2026-04`..`2026-09`).
* **Code Mitigation**: Applied `-3600 s` offset correction to `neso_2025-10.parquet` (`coverage: [1759273200, 1761951599]`), Reducing October 2025 RMSE from **`80.3095 mHz` to `0.6984 mHz`** ($r = 0.999947$), and exported `NESO_BST_SHIFTED_MONTHS` and `get_neso_month_utc_offset_s(ym)` in [`gb_reference.py`](gb_reference.py).

---

## 3. Failure Case 3: Elexon `/system/frequency` Default Query Trap (Artificial Multi-Hour Lag)
* **Symptom**: Calling `GET https://data.elexon.co.uk/bmrs/api/v1/system/frequency` without query parameters (or passing `measurementDateTimeFrom`/`To` instead of `from`/`to`) at `09:13 UTC` returned data ending at `2026-11-08T00:00:00Z` (**9.2 hours stale**).
* **Root Cause**: On `/system/frequency`, the query parameter names are `from` and `to` (whereas `/datasets/FREQ` uses `measurementDateTimeFrom`/`To`). When `from` and `to` are omitted or unrecognised, `/system/frequency` defaults to the 24-hour period ending at **midnight UTC of the current day**.
* **Code Mitigation**: All W02 scripts ([`gb_reference.py`](gb_reference.py) and [`elexon_archiver.py`](elexon_archiver.py)) call `/bmrs/api/v1/system/frequency/stream` with explicit `from` and `to` ISO-8601 UTC parameters, yielding true near-real-time data with **32–142 s latency**.

---

## 4. Failure Case 4: NESO Midnight Date-Only Timestamp Format Quirk (`2026-08` and `2026-09`)
* **Symptom**: Strict `strptime("%Y-%m-%d %H:%M:%S")` parsing fails on `fnew-2026-8.csv` and `fnew-2026-9.csv`.
* **Root Cause**: In August 2026 (`31` rows) and September 2026 (`30` rows), NESO's CSV exporter stripped `00:00:00` from midnight timestamps, writing `"2026-09-01,50.086"` followed by `"2026-09-01 00:00:01,50.078"`.
* **Code Mitigation**: Used `pd.to_datetime(..., format="mixed", utc=True).dt.as_unit("s").astype("int64")` (and explicit `len == 10` padding in streaming parsers), recovering 100% of midnight samples with zero gaps.

---

## 5. Failure Case 5: 2-Hour Inter-Transducer Telemetry Divergence on `2026-09-27 09:00:30Z..11:05:00Z`
* **Symptom**: On the September 2026 Dev split (`2026-09-24..28`), native 15 s RMSE was `13.2556 mHz` (`P99 = 62.0 mHz`, `max = 190.0 mHz`), roughly double the Holdout split RMSE (`6.5362 mHz`, `P99 = 16.0 mHz`, `max = 24.0 mHz`).
* **Root Cause**: Inspection via [`verify_oct2025_start_and_sep27.py`](verify_oct2025_start_and_sep27.py) isolated a single 2-hour window on **`2026-09-27T09:00:30Z` to `2026-09-27T11:05:00Z`** (`243` points $>20\text{ mHz}$) where NESO's control-room recorder and Elexon's BMRS feed diverged by up to `190 mHz` (with no lag $\tau \in [-43200, +43200]\text{ s}$ aligning them during those 2 hours). Outside that 2-hour window (`n = 39,573`), September 2026 7-day RMSE is **`6.4678 mHz`** ($r = 0.997144$).
