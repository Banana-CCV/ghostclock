# Worker W12 — Documented Failures, Limitations & Risk Controls (`FAILURES.md`)

**Worker ID:** W12  
**Date:** 2026-11-08  

---

## 1. Real Failure Case 1: Foreground Speech & Motion Transients Corrupting Low-SNR Windows (`ENF-WHU` `H1/001.wav`)

- **Artifact:** [`work/W12/plots/station_replay_001_health.png`](plots/station_replay_001_health.png) and `exp1_enf_whu_real_audio_validation.replay_001_case` in [`work/W12/RESULTS.json`](RESULTS.json).
- **What Happened:** On `ENF-WHU` `H1/001.wav` (a 482-second outdoor/campus mobile recording), our station locked accurately onto the true grid trace from $t = 125\text{ s}$ to $t = 470\text{ s}$ (where the 4th harmonic at $200\text{ Hz}$ reached $15\text{--}28\text{ dB}$ SNR, tracking the reference within $<2\text{ mHz}$). However, during the first $0\text{--}120\text{ s}$ (and briefly at $t \approx 360\text{ s}$), the person carrying the recorder was walking and speaking. Voice formants and footstep impacts created transient narrowband peaks inside the $\pm 0.45 h\text{ Hz}$ harmonic search window with local peak-to-median ratios of $8\text{--}12\text{ dB}$—just above our $6.0\text{ dB}$ single-frame gate—pulling the estimated fundamental to $49.62\text{--}50.36\text{ Hz}$. Across the full clip, those early outliers degraded the unmasked 15 s cross-check correlation to $r = -0.1053$ ($\text{RMSE} = 92.88\text{ mHz}$).
- **Why It Happened across `H1` `001..040` vs `099..118`:** Recordings `001..040` in `ENF-WHU` contain heavy outdoor speech/walking interference (`median_r_15s_lag0 = 0.1204`, `median_rmse = 117.7 mHz`), whereas `099..118` (indoor/stationary recordings with continuous mains coupling) achieved **`median_r_15s_lag0 = 0.9954`** and **`median_rmse = 1.50 mHz`**.
- **Operational Lesson & Mitigation:**
  1. For the **venue reference station (`reference_station.py`)**, the laptop microphone is stationary and placed $1\text{--}5\text{ cm}$ from a constant mains-hum source (AC/DC charger brick or extension lead), ensuring $\text{SNR} \ge 15\text{--}25\text{ dB}$ without walking/speech transients.
  2. For **uploaded evidence clips** containing speech, frame-by-frame causal STFT peak picking is insufficient; GhostClock must use W06/W07's non-causal Viterbi/dynamic-programming ridge tracker and temporal slow-variation weighting, which bridges across transient speech bursts.

---

## 2. Real Failure Case 2: Uncoupled Laptop Microphone & Windows SST Noise Suppression (`live_run`)

- **Artifact:** Panel C of [`work/W12/plots/live_venue_and_which_grid.png`](plots/live_venue_and_which_grid.png), [`work/W12/probe_live_details.json`](probe_live_details.json), and [`work/W12/live_run/station_health.json`](live_run/station_health.json).
- **What Happened:** When running `reference_station.py --mode live` on this laptop's built-in `Microphone Array (Intel® Smart Sound Technology for Digital Microphones)` in an unattended room without a transformer positioned near the microphone:
  - In our initial 6-second raw FFT test (`probe_live_details.json`), the per-harmonic SNRs at $100, 150, 200, 250, 300\text{ Hz}$ were only `+2.59, +5.73, +2.15, +0.75, -0.48 dB`, and the apparent harmonic peaks disagreed by $>200\text{ mHz}$ (`50.17 Hz` vs `49.93 Hz` vs `49.85 Hz`).
  - During the 10-second live station run (`exp3_live_venue_and_which_grid.live_laptop_capture`), only $66.7\%$ of windows passed the basic SNR check, triggering **`status: "DEGRADED_LOW_SNR"`** (and `NO_MAINS_HUM_LOW_SNR` when $<50\%$ pass).
- **Why It Happened:**
  1. Without a nearby transformer or loaded extension cable, a laptop microphone in a quiet room senses only broadband fan/ambient noise.
  2. Intel Smart Sound Technology (SST) / Windows 11 "Voice Focus" applies an adaptive stationary-tone notch filter designed specifically to remove $50/60\text{ Hz}$ mains hum from voice calls.
- **How Our Risk Control Handled It:** Rather than silently emitting a flat or random $\sim 50.000\text{ Hz}$ trace that could cause false downstream matches, `evaluate_health_status()` immediately flags `NO_MAINS_HUM_LOW_SNR` / `DEGRADED_LOW_SNR` and [`work/W12/OPERATOR.md`](OPERATOR.md) instructs the operator to place a charger brick within $1\text{--}5\text{ cm}$ of the mic and disable Windows Audio Enhancements before starting the demo.

---

## 3. Real Failure Case 3: Phase-Threshold Breakdown Below `+10 dB` Narrowband SNR (`snr_sweep`)

- **Artifact:** Panel D of [`work/W12/plots/station_vs_elexon_15s_crosscheck.png`](plots/station_vs_elexon_15s_crosscheck.png) and `exp2_gb_neso_to_elexon_15s_validation.dev_window_nov2025.snr_sweep` in [`work/W12/RESULTS.json`](RESULTS.json).
- **What Happened:** In our controlled SNR sweep on the 1-hour GB NESO-to-Elexon dataset (`N=239` 15 s intervals):
  - At **$\text{SNR} = +25\text{ dB}$ and $+20\text{ dB}$**, the station achieved $r = 0.9997$ ($\text{RMSE} = 1.80\text{ mHz}$) and $r = 0.9996$ ($\text{RMSE} = 2.25\text{ mHz}$).
  - At **$\text{SNR} = +15\text{ dB}$**, the station achieved $r = 0.9954$ ($\text{RMSE} = 7.37\text{ mHz}$).
  - At **$\text{SNR} = +10\text{ dB}$**, accuracy degraded sharply to $r = 0.5575$ ($\text{RMSE} = 116.8\text{ mHz}$), and at **$\le +6\text{ dB}$**, correlation collapsed to zero ($r = 0.056$, $\text{RMSE} = 202.8\text{ mHz}$).
  - Furthermore, because taking the maximum over $\sim 60$ FFT bins inside a $\pm 0.45 h\text{ Hz}$ search band on pure Gaussian noise produces an extreme-value peak that is $\sim 9.3\text{ dB}$ above the median flanking noise floor (`measured_peak_harmonic_snr_db = 9.28 dB` at `-15 dB` true input SNR!), a naive `6.0 dB` peak-to-median SNR gate fails to reject pure white noise (`valid_fraction = 0.968` at `-15 dB`, and `0.964` on `H0` negatives).
- **Critical Takeaway for Final Build:**
  - The extreme-value bias of `max(Pxx) / median(Pxx)` over 60 spectral bins is $\approx 9.3\text{ dB}$ under pure white noise. Therefore, in production, the **single-harmonic lock gate must be set to $\ge 14.0\text{ dB}$** (not $6.0\text{ dB}$), combined with an inter-harmonic agreement check ($\text{std}(f_h/h) \le 15\text{ mHz}$ across at least two harmonics).

---

## 4. Public Feed Availability Failures (`Fraunhofer Energy-Charts` & `GridRadar`)

- **Fraunhofer ISE `api.energy-charts.info/v2/frequency`:** Although documented in `/openapi.json` (`HTTP 200`) as providing 1-second Continental Europe frequency from Freiburg, Germany, live GET requests on `2026-11-08` returned `HTTP 404 ("no content available")` or timed out after `4.0 s`. We mitigated this by verifying and integrating `https://www.netzfrequenz.info/json/act.json` (`HTTP 200`, `1 s` live cadence, `~1.5 s` latency).
- **`api.gridradar.net/query`:** Returned `HTTP 401 Access Denied` without a paid commercial bearer token.
