# C2 findings: GB grid-frequency reference (Elexon + NESO), 2026-11-08

All numbers come from real API calls and downloads made today. A machine-readable copy is in RESULTS.json.

## 1. Elexon BMRS / Insights FREQ (live + history)
- Endpoint: https://data.elexon.co.uk/bmrs/api/v1/system/frequency?from=ISO&to=ISO&format=json
  (also /system/frequency/stream, /datasets/FREQ, /datasets/FREQ/stream).
  Docs: https://bmrs.elexon.co.uk/api-documentation/endpoint/system/frequency ; OpenAPI: https://data.elexon.co.uk/swagger/v1/swagger.json
- **Cadence 15 s**, stamped on the absolute grid ts % 15 == 0. From 2026-11-07 00:00Z to now there are 0 missing slots.
- **Spot (instantaneous) values.** The OpenAPI description says data is "received every 2 minutes", with a value "for one or more spot times". The cross-check in section 3 confirms a point sample, not a mean.
- **Timezone:** measurementTime is UTC (Z). from/to accept offsets: 09:00+01:00 returned rows from 08:00Z.
- **Max span per request:** 7 days on /system/frequency (HTTP 400 beyond that); 24 h on /datasets/FREQ. Ranges are inclusive at both ends (1 day = 5761 rows).
- **History:** the earliest record is 2021-08-30T00:00:00Z.
- **Latency:** data arrives in batches about every 2 min. Over 14 archiver polls the newest row was 8 to 93 s old; W02 saw up to 142 s. Plan for 2 to 2.5 min.
- **Traps:**
  - During outages Elexon publishes **0.0 Hz placeholders**: 87 rows in Oct 2025 and 182 in Aug 2026.
  - It also has real gaps: Aug 2026 is missing 224 slots, including one gap of 3375 s.
  - The archiver and loader store any value outside 45 to 55 Hz as NaN.
- **Today's data is not at risk.** Elexon keeps history. The local archiver just removes the network dependency for the demo.

## 2. NESO 1 s historical data
- **Where it lives:**
  - CKAN API: https://api.neso.energy/api/3/action/package_show?id=system-frequency-data
  - Page: https://www.neso.energy/data-portal/system-frequency-data
- **What is published:**
  - 153 monthly CSVs, from **Jan 2014 to Sep 2026**. The Sep 2026 file was last modified 2026-10-08.
  - **Oct 2026 is not published yet**, so the publication lag is about 5 to 6 weeks.
  - The full list is in neso_months.json.
- **Download URLs:** .../dataset/cb1cc925-ecd8-4406-b021-3a3f368196e1/resource/ID/download/fnew-YYYY-M.csv
  - They return a 302 redirect to a signed R2 URL, so use curl -L.
  - Each file is about 72 to 75 MB.
- **File format:** columns dtm,f.
  - dtm is a naive timestamp.
  - **Midnight rows are date-only**, so parse with format=ISO8601.
  - f has 3 decimals (1 mHz).
- **Months converted:** 2025-10, 2025-11, 2026-03, 2026-06, 2026-08 and 2026-09, written to datasets/raw/gb/neso_YYYY_MM.parquet with a .json sidecar.
  - Each month has exactly days x 86400 rows.
  - There are 0 gaps, 0 duplicates and 0 NaN.
- **Hidden outages are flat-filled with a constant value:**
  - 2026-09-15 07:30:03 to 10:35:59 UTC: constant 49.895 Hz for 11158 s.
  - 2026-03-31 13:39:28: constant 50.046 Hz for 479 s.
  - Both are recorded as bad_intervals in the sidecars and masked by the loader.
- **Timezone:**
  - Both DST-change days (2025-10-26 and 2026-03-29) have exactly 86400 rows.
  - Against Elexon (UTC), the per-day best lag is 0 s in 2025-11, 2026-03, 2026-06 (7 days at 1 to 2 s), 2026-08 and 2026-09.
  - **The exception is 2025-10: all 31 days match at +3600 s**, including the days after the DST change (per-day RMSE 0.57 to 0.94 mHz). So the Oct 2025 file is stamped UTC+1 for the whole month.
  - The row-count DST check alone would not have caught this.
  - The loader applies a -3600 s correction from neso_time_corrections.json.
  - Caveat: this assumes Elexon is correct. Elexon is the UTC Z feed, it matches wall-clock time live, and it agrees with NESO at 0 s in the other months. I had no third independent anchor.
  - **Run lagscan.py on any new month before trusting it.**

## 3. Cross-check: Elexon vs NESO (with correction)
| month | RMSE mHz | median abs mHz | exact (<=0.5 mHz) | best lag (days) | implied extra Elexon noise mHz |
|---|---|---|---|---|---|
| 2025-10 (NESO -3600 s) | 0.74 | 0 | 87.8 % | +3600 (31/31) | 0.0 |
| 2025-11 | 0.93 | 0 | 88.7 % | 0 (30/30) | 0.0 |
| 2026-03 | 7.06 | 4 | 7.3 % | 0 (30/31) | 5.5 |
| 2026-06 | 5.55 | 2 | 12.3 % | 0 (23), 1-2 (7) | 3.2 |
| 2026-08 | 7.49 | 3 | 9.7 % | 0 (30/31) | 3.9 |
| 2026-09 | 7.97 | 4 | 6.9 % | 0 (30/30) | 6.3 |

- **Up to Nov 2025, Elexon is a point sample of the NESO 1 s series** at the same UTC second. The residual is just 1 mHz rounding.
  - The 15 s means fit worse than the point value. For example, Aug 2026: point 7.49 mHz, centred 15 s mean 8.14 mHz, trailing mean 10.15 mHz.
- **In 2026 the two series are no longer identical.** Lag 0 is still best, so the timing is still aligned.
  - Elexon is rougher than NESO point samples. The std of 15 s differences implies about 3 to 6 mHz of extra white-noise-like scatter.
  - So Elexon is not an average: it is an independent or differently processed measurement.
  - The change happened between Dec 2025 and Mar 2026; Dec 2025 to Feb 2026 were not checked.
- Plot: plots/neso_vs_elexon_1h.png (2026-09-10 12:00 to 13:00 UTC, no shift applied).

## 4. Feasibility probe (SEMI-SYNTHETIC)
**Setup:**
- Data: real NESO 1 s, Aug and Sep 2026, with the outage masked.
- Trial: a random segment plus white Gaussian noise, searched in a 24 h window that contains it.
- Matcher: mean-removed NCC, computed with FFT.
- Success: the top-1 match is within +-15 s of the truth. n = 1000 per cell.

**Reference variants:**
- The 15 s searches keep 1 s resolution by trying all 15 query phases.
- "pt" is a point sample on the ts%15==0 grid. "avg" is a 15 s block mean of both query and reference.
- "Elexon real" uses the query from NESO 1 s and the ACTUAL Elexon 15 s series as the reference.

| D | sigma | 1 s ref | 15 s pt (NESO) | 15 s avg (NESO) | Elexon real 15 s |
|---|---|---|---|---|---|
| 2 min | 2 mHz | 1.000 | 0.472 | 0.876 | 0.102 |
| 5 min | 2 mHz | 1.000 | 0.994 | 1.000 | 0.747 |
| 10 min | 2 mHz | 1.000 | 1.000 | 1.000 | 0.951 |
| 20 min | 2 mHz | 1.000 | 1.000 | 1.000 | 0.994 |
| 2 min | 10 mHz | 0.766 | 0.026 | 0.199 | - |
| 5 min | 10 mHz | 0.992 | 0.559 | 0.967 | - |
| 10 min | 10 mHz | 1.000 | 0.945 | 1.000 | - |
| 20 min | 10 mHz | 1.000 | 1.000 | 1.000 | - |

**What this means:**
- **1 s reference at sigma = 2 mHz succeeds every time.** Treat this as an upper bound: the query and reference come from the same series, and the noise is white.
- **A 15 s point reference needs D >= 5 min at sigma 2 mHz**, and D >= 10 min at sigma 10 mHz.
- **Block-averaging to 15 s beats point sampling.** Average both the query and the reference.
- **Real 2026 Elexon is the binding constraint for the same-day demo.** Its extra 3 to 6 mHz of scatter cuts the success rate to 0.10, 0.75, 0.95 and 0.99 for 2, 5, 10 and 20 min.
  - **Use recordings of 10 min or more (20 min preferred) for a live demo against Elexon.**
  - Clips of 2 to 5 min need NESO 1 s data, which is published about 6 weeks later.
- **Where the match is found, it is precise:** the median error is 0 to 1 s in the successful cells.
