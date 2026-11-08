# GhostClock W12 — Live Venue Reference Station Operator Guide (`OPERATOR.md`)

**Component:** `work/W12/reference_station.py`  
**Output Schema:** Frozen Reference Series v1 (`source="LOCAL_STATION"`, `cadence_s=1`, `grid="GB"`)  

---

## 1. Why Run the Local Station at the Venue?

- **NESO 1-second historical archive (`api.neso.energy`)** lags by **~38 days** (monthly CSV publication). It cannot date a video or audio clip recorded today at the hackathon venue.
- **Elexon BMRS near-real-time feed (`data.elexon.co.uk`)** has low latency (**~45–60 seconds**), but its sampling cadence is **15 seconds** (`cadence_s=15`). While 15 s resolution is sufficient for clips $\ge 120\text{ s}$, short judge clips ($15\text{--}60\text{ s}$) lose correlation against a 15 s grid because fast intra-15s frequency excursions ($\sim 4.4\text{ mHz}$ RMSE) are smoothed out.
- **Synchronous GB Grid Principle:** Great Britain operates as a single synchronous AC island grid. A reference station running anywhere in London senses the **exact same instantaneous grid frequency** as any mains-powered light or appliance at the venue. Running `reference_station.py` continuously on a team laptop provides a **1-second GB reference trace** (`local_station.parquet`), while continuously cross-checking its 15-second average against live Elexon BMRS telemetry to prove to judges that the local station is tracking the real National Grid.

---

## 2. Choosing & Positioning a Safe Mains-Hum Source (No Wiring Modification)

> **Safety Rule:** **Never** modify mains wiring, build DIY voltage dividers, or connect mains cables to an audio jack. Use **passive acoustic or magnetic induction coupling only** from standard consumer equipment at the venue table.

### Best Hum Sources (Ranked by Harmonic SNR)
1. **Heavy AC/DC Wall Adapter or Laptop Power Brick (Best — 15 to 28 dB SNR at 100/150/200/300 Hz):**
   - Place the laptop's microphone (or an external USB/3.5 mm wired lapel mic) **1–5 cm** from a plugged-in laptop charger brick, monitor power brick, or phone charger under load (charging a device).
   - Magnetostriction and switching-rectifier ripple emit strong, crisp harmonics at **$100\text{ Hz}$ ($2 f_0$)**, **$150\text{ Hz}$ ($3 f_0$)**, **$200\text{ Hz}$ ($4 f_0$)**, and **$300\text{ Hz}$ ($6 f_0$)**. Because `reference_station.py` uses CRLB $h^2 \cdot \text{SNR}_h$ multi-harmonic weighting, a strong $100\text{ Hz}$ or $200\text{ Hz}$ harmonic yields **2× to 4× finer frequency resolution** than $50\text{ Hz}$ alone.
2. **Multi-Socket UK Extension Lead Under Load + Dynamic/Wired Earbud Mic (12 to 20 dB SNR):**
   - Drape the cord/capsule of a passive 3.5 mm wired headset mic directly alongside a multi-way UK extension block powering laptops or monitors. Passive inductive/capacitive pickup couples $50\text{ Hz}$ and $150\text{ Hz}$ directly into the unbalanced mic line without acoustic room noise.
3. **Mains Desk Lamp / Fluorescent Ballast / Venue Fridge or Vending Machine (10 to 18 dB SNR):**
   - Place the microphone near a mains-powered lamp transformer or appliance housing.

### Sources and Settings to Avoid
- **Laptop running on battery alone with nothing plugged in nearby:** produces only cooling-fan broadband noise (verified in our automated test: harmonic SNR $< 3\text{ dB}$, which triggers `NO_MAINS_HUM_LOW_SNR`).
- **Windows "Voice Focus" / Intel Smart Sound Technology (SST) AI Noise Suppression:**
  - Modern Windows 11 laptops apply real-time stationary-tone suppression on the default `Microphone Array (Intel® Smart Sound Technology)` input, which actively notches out $50/100/150\text{ Hz}$ hum after 1–2 seconds!
  - **Fix (takes 15 seconds in Windows Settings):** Open **Settings $\to$ System $\to$ Sound $\to$ Properties** for your microphone and set **Audio enhancements** to **Off** (or select `Microphone (Realtek HD Audio Mic input)` via `--device 14`).

---

## 3. Step-by-Step Venue Startup Procedure

All commands are run from the repository root (`<WORKSPACE>`).

### Step 1: Run the 5-Second Preflight Check
Before starting the long-running recorder, verify NTP clock synchronization, inspect audio input devices, and measure per-harmonic SNR:

```powershell
python work/W12/reference_station.py --mode preflight --out work/W12/live_run
```

Inspect the printed JSON output:
- **`ntp.measurable: true`** and **`ntp.offset_s`** (e.g., `+0.225` seconds): confirms UDP port 123 reached `time.cloudflare.com` / `time.windows.com` / `pool.ntp.org`. Even if venue Wi-Fi blocks UDP 123, the station degrades gracefully to the system UTC clock and logs `ntp.measurable: false`.
- **`health.status`**:
  - `"HEALTHY"` (`median_harmonic_snr_db >= 10.0 dB`, `valid_fraction >= 0.85`): **Ready to record.**
  - `"DEGRADED_LOW_SNR"` (`6.0 to 10.0 dB`): **Usable**, but move the mic closer to the power brick/extension lead for $<2\text{ mHz}$ precision.
  - `"NO_MAINS_HUM_LOW_SNR"` (`< 6.0 dB`): **Risk control triggered.** The station is outputting `NaN` rather than hallucinating a 50 Hz trace. Move the microphone closer to a plugged-in charger or turn off Windows Audio Enhancements, then re-run preflight.
  - `"CLIPPING_WARNING"` (`audio_peak >= 0.98`): Lower microphone input volume to ~70% in Windows Sound Settings.

### Step 2: Start the Continuous Reference Station (Start 30+ Minutes Before Demo)
Start the station in a dedicated PowerShell terminal so it continuously builds a 1-second reference archive throughout the judging session:

```powershell
# Run indefinitely (until Ctrl+C), flushing atomic Parquet every 5s and cross-checking Elexon:
python work/W12/reference_station.py --mode live --duration-s 0 --out work/W12/live_run
```

*(Optional)* Also run W02's Elexon 15-second archiver in parallel if you want the shared `datasets/raw/elexon/live_archive.parquet` updated every 2 minutes:

```powershell
python work/W02/elexon_archiver.py --interval-min 2
```

*(Optional)* If selecting a specific audio input device index (e.g. `14` for `Microphone (Realtek HD Audio Mic input)` from `preflight_report.json`) or using the FFmpeg DirectShow backend:

```powershell
python work/W12/reference_station.py --mode live --duration-s 0 --device 14 --out work/W12/live_run
```

---

## 4. Checking Station Health & Live Plots During the Demo

While `reference_station.py` is running, it updates four files atomically in `work/W12/live_run/` (safe to read at any time from another process or UI without file locks):

1. **`work/W12/live_run/station_health.json`**:
   ```powershell
   Get-Content work/W12/live_run/station_health.json
   ```
   Check:
   - `status`: must be `"HEALTHY"` (or `"DEGRADED_LOW_SNR"`).
   - `metrics.valid_fraction`: fraction of 1-second windows passing the $\ge 6\text{ dB}$ multi-harmonic SNR and $[47, 52]\text{ Hz}$ physical gates.
   - `elexon_crosscheck`: shows live `pearson_r_lag0`, `rmse_lag0_mhz`, `offset_bias_mhz`, and `fine_best_lag_s` against live Elexon BMRS 15 s telemetry.
2. **`work/W12/live_run/station_live_plot.png`**:
   - Open this image to show judges the live 3-panel station dashboard:
     - **Panel 1:** 1-second `LOCAL_STATION` ENF trace overlaid with its 15-second average and live Elexon BMRS 15 s telemetry.
     - **Panel 2:** Rolling peak harmonic SNR (dB) vs. the $6.0\text{ dB}$ deterministic abstention threshold and quality score $q(t) \in [0, 1]$.
     - **Panel 3:** Per-harmonic SNR bar chart across $50, 100, 150, 200, 250, 300\text{ Hz}$.
3. **`work/W12/live_run/local_station.parquet` & `local_station.json`**:
   - Standard GhostClock frozen reference series (`columns=["ts_utc", "f_hz", "source"]`, `source="LOCAL_STATION"`, `cadence_s=1`, `grid="GB"`). Pass directly to W10's `match()` function.

---

## 5. Stopping the Station Safely

- Press **`Ctrl+C`** once in the station's PowerShell terminal (or let `--duration-s <N>` finish).
- Because every Parquet and JSON write uses a temporary file (`local_station.parquet.tmp`) followed by an atomic `os.replace()`, stopping the process at any instant **never corrupts** `local_station.parquet` or `local_station.json`.
