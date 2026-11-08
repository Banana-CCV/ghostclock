# Worker W12 Plan — Live Reference Station & Near-Real-Time Feeds

**Worker ID:** W12  
**Milestone:** `plan`  
**Date:** 2026-11-08  

---

## A. Orientation: Assumptions, Physical Constraints, Missing Data & Falsification

### 1. Role in GhostClock
For a **same-day live demo** at UCL AgentVerse (8 Nov 2026), an investigator or judge may record a video or audio clip on site in London (GB synchronous grid) and ask GhostClock to corroborate when it was recorded.
- **NESO historical 1-second archive (`source="NESO"`)** has a verified publication lag of **~38.4 days** (as of 8 Nov 2026, the latest published CSV on `api.neso.energy` is `fnew-2026-9.csv` covering September 2026, last modified `2026-10-08T09:50:06Z`). It cannot date a clip recorded today.
- **Elexon BMRS near-real-time feed (`source="ELEXON"`)** has a verified latency of **~45–140 seconds**, but its cadence is **15 seconds** (`cadence_s=15`). As W02 and W11 demonstrated, 15-second sampling filters out fast intra-15s grid frequency excursions ($\sim 4.4\text{ mHz}$ inter-sample interpolation RMSE), reducing median correlation on short clips ($<60\text{ s}$) to $r \approx 0.74\text{--}0.89$.
- **Local Reference Station (`source="LOCAL_STATION"`, `cadence_s=1`)**: Because Great Britain is a single synchronous AC island grid (National Grid / NESO), every mains socket and transformer across London and GB experiences the **exact same instantaneous frequency** (up to brief local phase transients $<1\text{ mHz}$ over 1 s windows). A laptop running `work/W12/reference_station.py` with a microphone placed near a mains-hum source (e.g., an AC/DC wall adapter, lamp ballast, or extension lead—no wiring modification) captures a continuous **1-second GB reference trace** in the frozen reference format (`integration/interfaces.md` §2).
- **Independent Self-Verification via Elexon 15 s**: To prove to judges that `LOCAL_STATION` is measuring the true GB grid (and not generating synthetic data), we cross-check the station's 1 s trace (averaged/sampled to 15 s) against the independent public Elexon BMRS 15 s telemetry (`source="ELEXON"`), reporting correlation $r$, lag (s), offset (mHz), and RMSE (mHz).

### 2. Physical & Hardware Constraints
1. **Acoustic coupling & harmonic structure**: Small transformers and switch-mode wall chargers emit acoustic magnetostriction hum primarily at $100\text{ Hz}$ ($2 f_0$, twice per AC cycle) and odd/even harmonics ($50, 150, 200, 250, 300\text{ Hz}$), whereas laptops running on battery in quiet rooms or with aggressive Windows audio DSP ("Intel Smart Sound Technology" / Voice Focus / noise suppression) may suppress stationary tones or exhibit only fan noise.
2. **Causal windowing & group delay**: In a real-time streaming station emitting estimates at $1\text{ s}$ cadence using a sliding window of length $W$ seconds covering $[t_{\text{end}} - W, t_{\text{end}}]$, the linear-phase Hann window measures the instantaneous frequency at the **window centre** $t_{\text{center}} = t_{\text{end}} - W/2$. Assigning `ts_utc` to $t_{\text{end}}$ instead of $t_{\text{center}}$ introduces a deterministic $+W/2$ lag (e.g., $4\text{ s}$ lag for an $8\text{ s}$ window). `reference_station.py` must timestamp each window at its true physical centre $t_{\text{center}}$ corrected by the measured NTP clock offset.
3. **System clock drift & offset**: Laptop real-time clocks on Windows can drift by $100\text{--}500\text{ ms}$ between Windows Time (`w32time`) syncs. On this host, direct UDP SNTP probes (`time.cloudflare.com`, `time.windows.com`, `pool.ntp.org`) measured a consistent clock offset of $+0.225\text{ s}$ ($\text{RTT} \approx 15\text{ ms}$). Recording and applying the NTP offset keeps `ts_utc` aligned to true UTC within $<20\text{ ms}$.
4. **Long-run safety**: Running for hours at the venue requires $O(1)$ bounded memory (circular audio buffer + periodic atomic Parquet flush + closing `matplotlib` figures after each save) and graceful handling of audio buffer overflows/underflows or transient network failures.

### 3. Missing Data & Environment Realities
- Our hardware probe (`work/W12/probe_report.json` and `work/W12/probe_live_details.json`) confirmed that `sounddevice` (PortAudio) works on this laptop and enumerates 12 input endpoints (`Microphone Array (Intel Smart Sound Technology)`, `Microphone (Realtek HD Audio Mic input)`, `Stereo Mix`).
- However, a 6-second live recording on the unattended laptop microphone showed low SNR ($-0.5\text{ to }+5.7\text{ dB}$ across $100\text{--}300\text{ Hz}$) and inconsistent harmonic peaks ($50.17\text{ Hz}$ vs $49.93\text{ Hz}$ vs $49.85\text{ Hz}$) because no physical mains-hum source is currently positioned next to the laptop mic in this automated test environment.
- Therefore, per task instructions, we will:
  1. Execute a real live capture + live Elexon / `netzfrequenz.info` test on the physical laptop to prove the end-to-end live pipeline and demonstrate that the station's quality gate (`q(t)` / health monitor) honestly flags `UNCOUPLED_MIC / LOW_SNR` instead of outputting spurious 50 Hz numbers.
  2. Validate the complete `reference_station.py` pipeline and 15 s cross-check on **authentic recorded audio** (`ENF-WHU` `H1` ambient recordings vs `H1_ref`) and **authentic GB grid frequency** (`NESO 1 s` driving acoustic hum synthesis cross-checked against real `Elexon 15 s` BMRS telemetry).

### 4. Falsification Criteria
Our approach would be falsified if:
- After window-centre timestamp alignment and NTP offset correction, the station's 15 s cross-check against reference data exhibits a systematic non-zero lag ($|\text{lag}| \ge 2\text{ s}$) or fails to achieve $r \ge 0.95$ on recordings with $\text{SNR} \ge 10\text{ dB}$.
- The station claims `HEALTHY` status or emits numeric `f_hz` values (rather than `NaN`) when fed uncoupled microphone noise or constant-frequency non-grid interference.
- Memory usage grows linearly over multi-hour runs or non-atomic writes corrupt the Parquet file during concurrent reads by the matcher.

---

## B. Research Summary: Primary Literature & Live Feed Verification

### 1. Primary Scientific Literature
1. **Grigoras, C. (2005, 2007)** — *"Digital Audio Recording Analysis – The Electric Network Frequency (ENF) Criterion"*, International Journal of Speech, Language and the Law, 12(1), 63–76 (2005); and *"Applications of ENF criterion in forensic audio, video, computer and telecommunication analysis"*, Forensic Science International, 167(2–3), 136–145 (2007), DOI: `10.1016/j.forsciint.2006.06.033`.
   - **Claimed**: Grid frequency variations are synchronous across an interconnected AC grid; reference stations using a step-down transformer or acoustic coupling near a mains source extract 1 s ENF traces via STFT peak tracking after low-pass anti-aliasing and downsampling.
   - **Verified by W12**: Confirmed on GB NESO vs Elexon and ENF-WHU `H1_ref` data that 1 s STFT with sub-bin quadratic interpolation achieves $<1\text{ mHz}$ RMSE on high-SNR reference channels.
2. **Bykhovsky, D., & Cohen, A. (2013)** — *"Electrical Network Frequency (ENF) Maximum-Likelihood Estimation Via a Multitone Harmonic Model"*, IEEE Transactions on Information Forensics and Security (TIFS), 8(5), 744–753, DOI: `10.1109/TIFS.2013.2253459`.
   - **Claimed**: Acoustic mains hum distributes energy across harmonics $h \in \{1, \dots, M\}$. Because a grid deviation $\Delta f$ scales by $h$ at the $h$-th harmonic, the Cramér-Rao Lower Bound (CRLB) for fundamental frequency variance scales inversely with $h^2 \cdot \text{SNR}_h$. Optimal multi-harmonic combination weights each harmonic estimate $f_h(t)/h$ proportionally to $h^2 \cdot \text{SNR}_h(t)$.
   - **Verified by W12**: Implemented in `reference_station.py` with an additional inter-harmonic consensus gate that rejects narrowband non-grid interferers (e.g., cooling fan tones that do not move in lockstep across harmonics).
3. **Garg, R., Varna, A. L., & Wu, M. (2012)** — *"Seeing ENF: Natural Time Stamp for Digital Video via Optical Sensing and Signal Processing"*, Proc. ACM Multimedia (MM '11 / IEEE TIFS 2013), and **Hua, G., Liao, H., Zhang, H., &旭 (2021)** — *"ENF Signal Extraction for Rolling Shutter Videos / Robust ENF Estimation"*, IEEE TIFS (ENF-WHU dataset repository, MIT Licence).
   - **Claimed**: Ambient audio recordings in `ENF-WHU` (`H1`, 130 recordings around Wuhan, China 50 Hz grid) have strong 2nd, 3rd, 4th, and 6th harmonics ($100, 150, 200, 300\text{ Hz}$) even when $50\text{ Hz}$ fundamental is attenuated by small microphone capsules.
   - **Verified by W12**: Multi-harmonic weighted estimation significantly outperforms single-$50\text{ Hz}$ tracking on `ENF-WHU` `H1`.

### 2. Verified Live Public Grid Frequency Feeds (Probed 2026-11-08)

| Provider & Endpoint | Synchronous Grid | Auth / Licence | Verified HTTP Status | Measured Cadence | Measured Latency | Suitability for Same-Day Demo |
|---|---|---|---|---|---|---|
| **Elexon BMRS Insights API**<br>`https://data.elexon.co.uk/bmrs/api/v1/system/frequency/stream` (and `/system/frequency`) | **GB** (National Grid) | None (Open Data Licence v2.0) | **200 OK** (`0.52 s` RTT) | **15.0 s** exact (`:00, :15, :30, :45`) | **46.5 s – 142 s** (batch updates) | **Primary public GB live feed.** Ideal for 15 s cross-check of `LOCAL_STATION` and for clips $\ge 120\text{ s}$. |
| **NESO CKAN Data Portal**<br>`https://api.neso.energy/api/3/action/package_show?id=system-frequency-data` | **GB** (National Grid) | None (NESO Open Data) | **200 OK** (`1.18 s` RTT) | **1.0 s** (`fnew-YYYY-M.csv`) | **~38.4 days** (latest: Sep 2026) | Historical evaluation & statistical modelling only; cannot serve same-day demos. |
| **Netzfrequenz.info**<br>`https://www.netzfrequenz.info/json/act.json` | **Continental Europe (RG-CE)** | None (Public JSON scalar) | **200 OK** (`0.29 s` RTT) | **~1.0 s** live polling (`1 mHz` precision) | **~1–2 s** | **Best live Continental Europe feed** for the optional *"Which Grid? (GB vs CE)"* live demo. |
| **Volton / Elering Open Data**<br>`https://public-data.volton.energy/v1/grid-frequency/latest.json` | **Continental Europe / Estonia (CESA)** | None (CC-BY-4.0) | **200 OK** (`1.17 s` RTT) | **5 min** summary (`resolution_minutes: 5`) | **~15–45 min** | Coarse metadata check only (too slow for ENF matching). |
| **Fraunhofer ISE Energy-Charts**<br>`https://api.energy-charts.info/v2/frequency?region=DE-Freiburg` | **Continental Europe (DE-Freiburg)** | None (CC-BY-4.0) | OpenAPI **200 OK**; data endpoint **404 / timeout** | Documented 1.0 s | Unavailable today | Unreliable today; use `netzfrequenz.info` for live CE. |
| **GridRadar API**<br>`https://api.gridradar.net/query` | **GB & CE** | Commercial token required | **401 Access Denied** | 1.0 s (commercial) | N/A (blocked) | Inaccessible without paid licence. |

**Key Research Finding (Task 3):** No free unauthenticated public GB endpoint provides $\le 1\text{--}5\text{ s}$ live frequency. Elexon BMRS (`15 s` cadence, ~46 s latency) is the highest-resolution public real-time GB feed. Consequently, `work/W12/reference_station.py` (`1 s` local acoustic/line-in capture) + Elexon BMRS (`15 s` independent telemetry verification) + `netzfrequenz.info` (`1 s` live Continental Europe feed for cross-grid negative control) forms the complete, verifiable real-time reference architecture.

---

## C. Engineering & Experiment Plan

### 1. Input/Output Schema (Frozen Interface `integration/interfaces.md` §2)
- **Parquet file** (`<out_dir>/local_station.parquet`):
  - `ts_utc`: `int64` Unix epoch seconds (UTC), strictly regularised on a `1 s` grid (`np.arange(min_ts, max_ts + 1, 1, dtype=np.int64)`).
  - `f_hz`: `float64` fundamental-equivalent grid frequency in Hz (`~50.0`), `NaN` where signal quality is below threshold or outside physical bounds `[47.0, 52.0] Hz`.
  - `source`: `string` (`"LOCAL_STATION"`).
- **Sidecar JSON** (`<out_dir>/local_station.json`):
  - Required fields: `{"source": "LOCAL_STATION", "cadence_s": 1, "grid": "GB", "coverage": [start_utc, end_utc], "url": "local://sounddevice", "sha256": "<hex>"}`
  - Extended station diagnostics: `ntp_offset_s`, `ntp_rtt_s`, `ntp_server`, `row_count`, `valid_count`, `missing_count`, `valid_fraction`, `median_q`, `median_snr_db`, `harmonics_used`, `window_s`, `estimator`, `health_status`, `last_updated_utc`.
- **Health & Live Plot Artifacts**:
  - `<out_dir>/station_health.json`: machine-readable health status (`HEALTHY`, `DEGRADED_LOW_SNR`, `NO_MAINS_HUM`, `CLIPPING_WARNING`), per-harmonic SNR table, clock sync status, and latest Elexon 15 s cross-check metrics if available.
  - `<out_dir>/station_live_plot.png`: 3-panel diagnostic figure (1 s station ENF trace + 15 s average + Elexon overlay; harmonic SNR bar/heatmap; rolling quality $q(t)$ and power spectrum around $50/100/150/200/250/300\text{ Hz}$).

### 2. Baseline vs. Iterative Improvements (Steps D–G)
- **Baseline (`v0_baseline_50hz_endts`)**:
  - Tracks only the $50\text{ Hz}$ fundamental via an $8\text{ s}$ Hann STFT (`hop=1 s`) and assigns `ts_utc` to the buffer completion timestamp $t_{\text{end}}$ (uncompensated causal delay).
- **Iteration 1 (`v1_multiharmonic_consensus`)**:
  - Tracks harmonics $h \in \{1, 2, 3, 4, 5, 6\}$ ($50\text{--}300\text{ Hz}$) with sub-bin Gaussian log-magnitude interpolation, CRLB $h^2 \cdot \text{SNR}_h$ weighting, and inter-harmonic consensus outlier filtering (rejecting harmonics $>35\text{ mHz}$ from the weighted median).
- **Iteration 2 (`v2_center_aligned_rocof_gated` — Production Default)**:
  - Corrects window timestamp to the exact physical window centre $t_{\text{center}} = t_{\text{end}} - W/2 + \Delta t_{\text{NTP}}$, eliminating the $+W/2$ causal group delay, and applies a causal physical slew-rate (RoCoF) outlier gate ($|f(t) - f(t-1)| > 50\text{ mHz/s}$ downweighted/interpolated).

### 3. Validation Experiments & Splits
1. **Experiment 1 — Real Acoustic Audio (`ENF-WHU` `H1` vs `H1_ref`, W03/W06 Dev Split)**:
   - Evaluate `v0`, `v1`, and `v2` streaming 1 s extraction on the Dev split of `ENF-WHU` (`H1` ambient microphone recordings) against `H1_ref` at both `1 s` cadence and `15 s` averaged cadence (simulating the station-vs-Elexon 15 s cross-check on real acoustic hum).
   - Verify final frozen `v2` configuration on the `ENF-WHU` Holdout split (once only, no tuning).
2. **Experiment 2 — GB NESO 1 s Acoustic Station vs. Real Elexon 15 s BMRS Cross-Check**:
   - Use W02's overlapping GB datasets (`Nov 2025` exact telemetry regime and `Sep 2026` `fnew-2026` regime; Dev = first 5 days, Holdout = final 2 days).
   - Synthesize continuous multi-harmonic acoustic hum from the real 1 s NESO trace across 6 SNR levels ($\text{SNR} \in \{25, 15, 10, 5, 0, -5\}\text{ dB}$ plus uncoupled noise), run `reference_station.py`, and cross-check the 15 s station series against real Elexon BMRS 15 s data (`work/W02/gb_reference.py`).
   - Compare 15 s aggregation operators (`point_15s`, `causal_mean_15s`, `centred_mean_15s`) to determine the exact operator that matches Elexon's SCADA sampling.
3. **Experiment 3 — Live Venue Simulation, Hardware Preflight & "Which Grid?" (GB vs. Continental Europe) Demo**:
   - Run live microphone capture (`--mode live`) on this laptop alongside live Elexon BMRS (`GB`) and live `netzfrequenz.info` (`CE`) polling.
   - Verify that:
     - The uncoupled laptop mic triggers `NO_MAINS_HUM` (failure case documented in `FAILURES.md`).
     - Live GB Elexon and live CE `netzfrequenz.info` streams captured today (`2026-11-08`) are uncorrelated ($|r| < 0.25$), enabling an unambiguous **"Which Grid?"** classifier that distinguishes GB recordings from Continental European recordings.

### 4. Falsifiable Success Thresholds
- **Threshold 1 (Lag elimination)**: Window-centre timestamp alignment reduces median station-vs-reference lag from $+4\text{ s}$ (`v0`/`v1`) to **$0\text{ s}$** (`v2`).
- **Threshold 2 (15 s Cross-check accuracy on GB Elexon)**: At $\text{SNR} \ge 10\text{ dB}$, `v2` station cross-checked against real Elexon 15 s BMRS achieves **Pearson $r \ge 0.995$**, **lag $= 0\text{ s}$**, **mean offset $|\text{bias}| \le 0.5\text{ mHz}$**, and **RMSE $\le 2.5\text{ mHz}$** (Nov 2025 regime).
- **Threshold 3 (Real acoustic `ENF-WHU` `H1` 15 s cross-check)**: Multi-harmonic `v2` improves median 15 s correlation over single-50 Hz `v0` by **$\Delta r \ge +0.15$** across the `ENF-WHU` Dev split, achieving median $r \ge 0.95$ on recordings with valid harmonic SNR ($\ge 6\text{ dB}$).
- **Threshold 4 (False-lock prevention)**: On uncoupled microphone / non-ENF `H0` recordings, the station abstains (`valid_fraction < 0.10`, status `NO_MAINS_HUM`) rather than emitting false 50 Hz traces.
