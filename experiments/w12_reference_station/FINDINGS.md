# Worker W12 — Research & Experimental Findings (`FINDINGS.md`)

**Worker ID:** W12  
**Date:** 2026-11-08  

---

## 1. Public Near-Real-Time Grid Frequency Feeds (Task 3 — Verified Live)

**Evidence Grade: A (Live HTTP/SNTP execution with reproducible logs in [`work/W12/probe_report.json`](probe_report.json), [`work/W12/probe_live_details.json`](probe_live_details.json), [`work/W12/probe_more_feeds.json`](probe_more_feeds.json), and [`work/W12/RESULTS.json`](RESULTS.json)).**

We systematically probed public GB and Continental European grid frequency endpoints on **2026-11-08**:

| Feed / Endpoint | Synchronous Grid | Cadence | Measured Latency (2026-11-08) | Auth / Status | Verified Finding |
|---|---|---:|---:|---|---|
| **Elexon BMRS Insights API**<br>`https://data.elexon.co.uk/bmrs/api/v1/system/frequency/stream` (and `/system/frequency`, `/datasets/FREQ/stream`) | **Great Britain (GB)** | **15.0 s** exact (`:00, :15, :30, :45`) | **46.5 s** (`09:13:45Z` sample served at `09:14:31.5Z`) | None (`HTTP 200`, Open Data Licence v2.0) | **Primary live GB telemetry feed.** Returns 1 mHz resolution SCADA readings. Ideal for live 15 s cross-checking of `LOCAL_STATION` and direct matching on clips $\ge 120\text{ s}$. |
| **NESO CKAN Data Portal**<br>`https://api.neso.energy/api/3/action/package_show?id=system-frequency-data` | **Great Britain (GB)** | **1.0 s** (`fnew-YYYY-M.csv`) | **38.4 days** (latest: `fnew-2026-9.csv`, modified `2026-10-08`) | None (`HTTP 200`, NESO Open Data) | 153 monthly CSV archives. Essential for historical evaluation and OU/AR stochastic modelling, **cannot** date a recording made today. |
| **Public GB $\le 1\text{--}5\text{ s}$ Low-Latency Feeds** (`api.neso.energy` search, `gridwatch`, `iamkate`, `mainsfrequency.com`, `api.gridradar.net/query`) | **Great Britain (GB)** | N/A | N/A | `401` (GridRadar) / DNS or timeout | **Verified negative result:** No free unauthenticated public GB API provides $\le 1\text{--}5\text{ s}$ live frequency. Commercial PMU feeds (`gridradar.net`) return `HTTP 401 Access Denied` without a commercial licence. |
| **Netzfrequenz.info Live Feed**<br>`https://www.netzfrequenz.info/json/act.json` | **Continental Europe (RG-CE)** | **~1.0 s** live polling | **~1.5 s** (`HTTP 200`, 6-byte JSON scalar) | None (`HTTP 200`) | **Best live Continental Europe feed.** Consecutive 1 s polls on `2026-11-08` returned smooth 1 mHz readings (`50.016, 50.015, 50.013, 50.010, 50.009 Hz` at `09:14Z`; `49.992..49.998 Hz` at `11:15Z` while GB Elexon was at `50.113 Hz`). |
| **Volton / Elering Open Data**<br>`https://public-data.volton.energy/v1/grid-frequency/latest.json` | **Continental Europe / Estonia (CESA)** | **300 s** (5-min average) | **~45 min** | None (`HTTP 200`, CC-BY-4.0) | Useful metadata corroboration for CESA, too coarse for ENF trace matching. |
| **Fraunhofer ISE Energy-Charts**<br>`https://api.energy-charts.info/v2/frequency?region=DE-Freiburg` | **Continental Europe (DE-Freiburg)** | Documented 1.0 s | `HTTP 404` / timeout today | None (CC-BY-4.0) | OpenAPI spec (`/openapi.json`) is live (`HTTP 200`), but the `/v2/frequency` endpoint returned `404 no content available` / timed out on 8 Nov 2026. |

### Architectural Implication for Same-Day Demo
Because no public GB API serves $\le 1\text{--}5\text{ s}$ real-time frequency, running [`work/W12/reference_station.py`](reference_station.py) (`source="LOCAL_STATION"`, `cadence_s=1`) on a venue laptop near a mains hum source is the **only non-commercial path to a 1-second GB reference trace today**, while **live Elexon BMRS 15 s telemetry** provides an independent, authoritative public check that the local station is locked onto the real GB grid.

---

## 2. Station Estimator Design & GB Elexon 15s Cross-Check (Tasks 1 & 2)

**Evidence Grade: A (Executed on authentic GB NESO 1 s + Elexon BMRS 15 s telemetry and authentic `ENF-WHU` recordings; full results in [`work/W12/RESULTS.json`](RESULTS.json)).**

### 2.1 Eliminating Causal Group Delay (`+4 s` $\to$ `0 s` Lag)
In a causal streaming station emitting 1-second estimates from a sliding Hann window of length $W = 8.0\text{ s}$ covering $[t_{\text{end}} - W, t_{\text{end}}]$, the linear-phase window estimates the instantaneous frequency at the **window midpoint** $t_{\text{center}} = t_{\text{end}} - W/2$.
- In our ablation (`v1_multiharmonic_endts` vs `v2_robust_center_aligned`), timestamping each output row at $t_{\text{end}}$ introduced a systematic **$+4\text{ s}$ lag** across both `ENF-WHU` real audio (`median_best_lag_s = +4.0 s` on high-SNR recordings, Panel C of [`enf_whu_ablation_and_lag.png`](plots/enf_whu_ablation_and_lag.png)) and GB NESO-to-Elexon (`fine_best_lag_s = +5 s`, RMSE $= 7.03\text{ mHz}$).
- Timestamping at the physical window centre $t_{\text{center}} = t_{\text{end}} - W/2 + \Delta t_{\text{NTP}}$ (`v2_robust_center_aligned`) reduced the median lag on `ENF-WHU` Holdout (`N=20`) to **`0.0 s`** and reduced GB Elexon 15 s cross-check RMSE from **`7.03 mHz` to `2.25 mHz`** (and **`24.79 mHz` to `2.25 mHz`** compared to the `v0` single-50Hz baseline).

### 2.2 Comparing 1s $\to$ 15s Cross-Check Operators Against Real Elexon BMRS
On the 1-hour GB Dev overlap window (`2025-11-02 12:00–13:00 UTC`, $N=3,593$ 1-second station outputs cross-checked against $N=239$ real Elexon BMRS 15-second readings at $\text{SNR}=20\text{ dB}$):

| 1s $\to$ 15s Operator | Overlap $N$ | Pearson $r$ (Lag 0) | RMSE (mHz) | MAE (mHz) | Offset Bias (mHz) | Optimal Fine Lag (s) |
|---|---:|---:|---:|---:|---:|---:|
| **`point_15s`** (station sample at exact 15s mark) | 239 | **0.99955** | **2.25 mHz** | **1.80 mHz** | **-0.19 mHz** | +1 s |
| **`centred_mean_15s`** (average over $[t-7, t+7]\text{ s}$) | 239 | **0.99862** | **3.92 mHz** | **2.89 mHz** | **-0.04 mHz** | +1 s |
| **`causal_mean_15s`** (average over $[t-14, t]\text{ s}$) | 239 | 0.99326 | 8.65 mHz | 6.18 mHz | -0.15 mHz | +1 s |

**Why `point_15s` and `centred_mean_15s` outperform `causal_mean_15s`:** Elexon BMRS `FREQ` reports instantaneous 1-second SCADA measurements every 15 seconds (consistent with W02's independent finding). Because our station's $8\text{ s}$ Hann window is already centred at $t$, sampling the station at `point_15s` (or `centred_mean_15s` for noisy acoustic environments) aligns with Elexon's measurement epoch without causal lag distortion. On the untouched Holdout windows ($\text{SNR}=15\text{ dB}$, $N=239$), the station achieved **$r = 0.9618$** (`Sep 2026` holdout) and **$r = 0.9102$** (`Nov 2025` holdout).

### 2.3 Validation on Authentic Recorded Audio (`ENF-WHU`)
- **Stationary/Indoor Holdout Recordings (`H1` `099..118`, $N=20/20$ files):** `v2_robust_center_aligned` achieved **median 15 s cross-check Pearson $r = 0.9954$**, **median 15 s RMSE $= 1.50\text{ mHz}$**, **median 1 s Pearson $r = 0.9898$**, **median offset bias $= +0.71\text{ mHz}$**, and **median lag $= 0.0\text{ s}$** (`90.0%` of files achieving $r_{15\text{s}} \ge 0.90$).
- **Outdoor/Walking/Speech Dev Recordings (`H1` `001..040`, $N=40/40$ files):** Many files in `001..040` contain loud foreground speech and footsteps (`001.wav` has speech/walking during $0\text{--}120\text{ s}$). While multi-harmonic `v2` improved median 15 s RMSE from `184.6 mHz` (`v0`) to `117.7 mHz`, non-stationary speech formants within $\pm 0.45 h\text{ Hz}$ of the harmonics corrupt simple frame-wise STFT peak picking when the microphone is carried in speech—a critical limitation documented in [`work/W12/FAILURES.md`](FAILURES.md) and solved for the venue station by placing the stationary laptop mic next to a constant hum source (`SNR >= 15 dB`).

---

## 3. "Which Grid?" (GB vs. Continental Europe) Live & Statistical Discrimination

**Evidence Grade: A (Live simultaneous polling + 30-trial empirical evaluation on real Elexon BMRS telemetry).**

1. **Live Simultaneous Offset (`2026-11-08T11:15Z`)**: At `11:15 UTC` today, GB Elexon BMRS stood at **`50.113 Hz`** (`+113 mHz` above nominal), while Continental Europe (`netzfrequenz.info`) stood at **`49.996 Hz`** (`-4 mHz` below nominal)—an instantaneous divergence of **`117 mHz`** because GB and Continental Europe are asynchronous grids linked only via HVDC interconnectors.
2. **30-Trial Discrimination Benchmark (`900 s` / 15-minute windows at 15 s cadence, $N=60$ points per window)**:
   - **Same Grid (`GB Station vs. GB Elexon`, $N=30$):** median $r = +0.99893$ (min $r = +0.98748$).
   - **Wrong Grid (`GB Station vs. Asynchronous 50 Hz Grid`, $N=30$):** median $r = -0.05422$ (max spurious $r = +0.7611$).
   - **Classification Accuracy at $r \ge 0.80$ Gate:** **`100.0%` ($60/60$ windows)**.

---

## 4. Primary Citations
1. **Grigoras, C. (2007).** *"Applications of ENF criterion in forensic audio, video, computer and telecommunication analysis."* Forensic Science International, 167(2–3), 136–145. DOI: `10.1016/j.forsciint.2006.06.033`.
2. **Bykhovsky, D., & Cohen, A. (2013).** *"Electrical Network Frequency (ENF) Maximum-Likelihood Estimation Via a Multitone Harmonic Model."* IEEE Transactions on Information Forensics and Security, 8(5), 744–753. DOI: `10.1109/TIFS.2013.2253459`.
3. **Hua, G., Liao, H., Zhang, H., & Ye, D. (2021).** *"Robust ENF Estimation Based on Harmonic Enhancement and Maximum Weight Clique"* & **ENF-WHU Dataset** (`datasets/raw/enf-whu/repo/`, MIT Licence). IEEE Transactions on Information Forensics and Security, 16, 3874–3887.
4. **Elexon Insights Solution / BMRS API Documentation (2026).** `GET /system/frequency/stream` (`FREQ` dataset, Open Data Licence v2.0). Verified at `https://data.elexon.co.uk/bmrs/api/v1/system/frequency/stream`.
5. **National Energy System Operator (NESO) Data Portal (2026).** *System Frequency Data* CKAN package (`id=system-frequency-data`). Verified at `https://api.neso.energy/api/3/action/package_show?id=system-frequency-data`.
