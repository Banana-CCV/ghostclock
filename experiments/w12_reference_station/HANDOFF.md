# Worker W12 — Integration & Pitch Deck Handoff (`HANDOFF.md`)

**Worker ID:** W12 (Live Reference Station & Near-Real-Time Feeds)  
**Status:** `DONE`  
**Evidence Grade:** `A` (Live APIs + hardware + real GB NESO/Elexon + real `ENF-WHU` audio verified)  

---

## 1. Components to Promote to the Final GhostClock Build

| Component / File | Recommendation | Why / Interface Contract |
|---|---|---|
| [`work/W12/reference_station.py`](reference_station.py) | **KEEP (Promote)** | Complete 1-second live reference recorder (`--mode live`), file replay (`--mode replay`), and operator preflight (`--mode preflight`). Outputs atomic Parquet + JSON sidecar strictly adhering to `integration/interfaces.md` §2 (`source="LOCAL_STATION"`, `cadence_s=1`, `grid="GB"`). Includes `load_local_station(start_utc, end_utc)` and `crosscheck_station_vs_15s_ref()`. |
| [`work/W12/OPERATOR.md`](OPERATOR.md) | **KEEP (Promote)** | Essential venue runbook for setting up a passive mains-hum source (laptop charger brick / extension lead, zero wiring modification), disabling Windows 11 SST/Voice-Focus noise suppression, verifying NTP offset, and monitoring `station_health.json`. |
| **Live Feed Architecture** (`Elexon BMRS 15s` + `LOCAL_STATION 1s` + `netzfrequenz.info 1s CE`) | **KEEP (Promote)** | Use `LOCAL_STATION` (`1 s`) for short same-day venue clips ($<120\text{ s}$), cross-checked live against `Elexon BMRS` (`15 s`, ~46.5 s latency) to prove authenticity to judges, and `netzfrequenz.info/json/act.json` (`1 s` live Continental Europe) for the *"Which Grid?"* live demonstration. |
| **Threshold Refinement for Production** (`min_snr_db`) | **UPGRADE IN PROD** | Raise `min_snr_db` from `6.0 dB` to **`14.0 dB`** (plus inter-harmonic dispersion $\le 15\text{ mHz}$) to account for the $+9.3\text{ dB}$ extreme-value bias of picking the maximum across 60 FFT bins in white noise (documented in `FAILURES.md`). For uploaded field audio with speech, use W06/W07's non-causal Viterbi/DP tracker rather than the station's causal frame-by-frame peak picker. |

---

## 2. Deck-Worthy Numbers (All Real & Measured from `work/W12/RESULTS.json`)

- **Public GB Live Feed Latency & Cadence (`2026-11-08`):**
  - **NESO 1-second Archive (`api.neso.energy`):** `1.0 s` cadence, **`38.4 days` publication lag** (latest available on 8 Nov 2026 is September 2026).
  - **Elexon BMRS Live Stream (`data.elexon.co.uk`):** `15.0 s` exact cadence, **`46.5 s` live latency** (`HTTP 200`, no API key required).
  - **Public GB $\le 1\text{--}5\text{ s}$ Feed:** **None exists** without commercial PMU licensing (`GridRadar` returns `HTTP 401`). This justifies why W12's `LOCAL_STATION` is mandatory for 1-second same-day demos.
- **Station 1s-to-Elexon 15s Cross-Validation (`N=239` 15s steps / `3,593` 1s steps over 1 hour, `20 dB` SNR):**
  - **Correlation:** **Pearson $r = 0.99955$** (`point_15s`) and **$r = 0.99862$** (`centred_mean_15s`).
  - **Error & Offset:** **$\text{RMSE} = 2.25\text{ mHz}$**, **$\text{MAE} = 1.80\text{ mHz}$**, **$\text{Offset Bias} = -0.19\text{ mHz}$**.
  - **Ablation Gain:** Multi-harmonic CRLB weighting + window-centre timestamp alignment (`v2`) reduces 15 s cross-check RMSE by **11.0×** vs. single-50Hz baseline (`24.79 mHz` $\to$ `2.25 mHz`) and **3.1×** vs. end-timestamped multi-harmonic (`7.03 mHz` $\to$ `2.25 mHz`), eliminating the $+4\text{ s}$ causal window lag.
- **Authentic Stationary Audio Validation (`ENF-WHU` Holdout `H1` `099..118`, $N=20/20$ recordings):**
  - **15 s Cross-Check:** **Median Pearson $r = 0.9954$**, **Median RMSE $= 1.50\text{ mHz}$**, **Median Lag $= 0.0\text{ s}$** (`90.0%` of recordings achieve $r \ge 0.90$).
  - **1 s Full-Resolution Trace:** **Median Pearson $r = 0.9898$**.
- **"Which Grid?" (GB vs. Continental Europe) Live & Statistical Discrimination:**
  - **Live Divergence (`2026-11-08T11:15Z`):** GB Elexon at **`50.113 Hz`** vs. Continental Europe (`netzfrequenz.info`) at **`49.996 Hz`** (**`117 mHz` instantaneous separation**).
  - **30-Trial Benchmark (`15-min` windows at `15 s` cadence, $N=60$ points/window):** Same-grid median $r = +0.99893$ vs. Wrong-grid median $r = -0.05422$ (**`100.0%` discrimination accuracy** at $r = 0.80$ gate, $60/60$ windows).

---

## 3. Deck-Worthy Figures in `work/W12/plots/` (with Mandatory Data-Type Captions)

1. **[`work/W12/plots/station_vs_elexon_15s_crosscheck.png`](plots/station_vs_elexon_15s_crosscheck.png)**
   - **Caption:** `SEMI-SYNTHETIC` — Authentic GB NESO 1-second grid frequency (`2025-11-02 12:00–13:00 UTC`, $N=3,593$) modulated into a multi-harmonic acoustic hum waveform (`50–300 Hz`), extracted by `work/W12/reference_station.py` (`LOCAL_STATION`), and cross-checked against authentic Elexon BMRS 15-second SCADA telemetry ($N=239$), achieving $r = 0.99955$, $\text{RMSE} = 2.25\text{ mHz}$, and $0\text{ s}$ window-centre lag.
2. **[`work/W12/plots/enf_whu_ablation_and_lag.png`](plots/enf_whu_ablation_and_lag.png)**
   - **Caption:** `REAL-MEASURED` — Ablation across authentic `ENF-WHU` microphone recordings ($N=40$ Dev `H1` + high-SNR subset) comparing `v0` (single 50 Hz, end-timestamp), `v1` (multi-harmonic 50–300 Hz, end-timestamp), and `v2` (multi-harmonic 50–300 Hz, window-centre timestamp), showing elimination of the $+4\text{ s}$ causal window lag to $0\text{ s}$ and reduction of median 15 s RMSE from $272.7\text{ mHz}$ to $110.9\text{ mHz}$ on noisy outdoor clips ($1.50\text{ mHz}$ on stationary Holdout `H1`).
3. **[`work/W12/plots/live_venue_and_which_grid.png`](plots/live_venue_and_which_grid.png)**
   - **Caption:** `REAL-MEASURED` — Live `2026-11-08` telemetry fetched from GB Elexon BMRS (`15 s` cadence, $N=115$, latest `50.113 Hz`) vs. Continental Europe `netzfrequenz.info` (`1 s` cadence, `49.996 Hz`), 30-trial GB-vs-CE synchronous grid discrimination ($100\%$ accuracy at $r=0.80$), and live laptop microphone risk-control test flagging `DEGRADED_LOW_SNR` when no hum source is present.
4. **[`work/W12/plots/station_replay_001_health.png`](plots/station_replay_001_health.png)**
   - **Caption:** `REAL-MEASURED` — Three-panel `reference_station.py` diagnostic dashboard on authentic `ENF-WHU` recording `H1/001.wav` vs. `H1_ref/001_ref.wav`, illustrating both a real failure mode (walking/speech interference during $0\text{--}120\text{ s}$) and tight multi-harmonic lock ($200\text{ Hz}$ H4 at $16.9\text{ dB}$ median SNR, $<2\text{ mHz}$ tracking error) once stationary ($125\text{--}470\text{ s}$).
