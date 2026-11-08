> **Release note.** Study by Gemini worker W12. **Not independently re-verified**. It is a prototype and feeds no reported metric.

# Worker W12 — Live Reference Station & Near-Real-Time Feeds (`README.md`)

## Overview
Worker **W12** makes a **same-day live venue demo** possible for GhostClock:
1. **`work/W12/reference_station.py`**: A real-time 1-second Electrical Network Frequency (ENF) recorder and file-replay station that captures audio from the laptop's microphone or line-in via `sounddevice` (with `ffmpeg -f dshow` fallback on Windows), measures and applies the system clock's UDP SNTP offset across `time.cloudflare.com`, `time.windows.com`, and `pool.ntp.org`, extracts fundamental-equivalent grid frequency (`~50.0 Hz`) at a `1 s` cadence using a window-centre-aligned CRLB multi-harmonic estimator (`50, 100, 150, 200, 250, 300 Hz`), atomically writes rolling Parquet + JSON sidecars in the frozen format (`integration/interfaces.md` §2, `source="LOCAL_STATION"`), cross-checks against live 15-second Elexon BMRS telemetry (`source="ELEXON"`), and outputs a live 3-panel diagnostic plot and JSON health report.
2. **`work/W12/validate_station.py`**: Reproducible validation and ablation suite evaluating `reference_station.py` across:
   - Authentic GB NESO 1 s grid frequency (`datasets/raw/neso/`) driving acoustic mains hum cross-checked against authentic Elexon BMRS 15 s telemetry (`datasets/raw/elexon/`).
   - Authentic recorded audio from `ENF-WHU` (`H1` ambient audio vs `H1_ref` reference power traces, plus `H0` non-ENF negatives).
   - Live hardware microphone capture + live GB Elexon BMRS (`15 s` cadence) + live Continental Europe `netzfrequenz.info` (`1 s` cadence) polling + the **"Which Grid? (GB vs Continental Europe)"** discriminator.
3. **`work/W12/OPERATOR.md`**: Complete venue runbook covering safe passive hum-source selection (no wiring modification), Windows SST/Voice-Focus noise-suppression mitigation, preflight health checks, continuous execution, and graceful shutdown.

---

## Dependencies
All core dependencies (`numpy`, `scipy`, `pandas`, `pyarrow`, `matplotlib`, `soundfile`, `requests`) are in the shared Python 3.12 virtual environment, plus `sounddevice` (`0.5.5`, installed via `python -m pip install sounddevice`).

---

## Exact Run Commands (from Repository Root `<WORKSPACE>`)

### 1. Operator Preflight Check (5 seconds — NTP Offset + Audio Devices + Harmonic SNR)
```powershell
python work/W12/reference_station.py --mode preflight --out work/W12/live_run
```

### 2. Run Live Venue Reference Station Continuously
```powershell
# Run for 30 seconds (set --duration-s 0 to run indefinitely until Ctrl+C):
python work/W12/reference_station.py --mode live --duration-s 30 --out work/W12/live_run

# Optional: specify audio input device index or FFmpeg DirectShow backend:
python work/W12/reference_station.py --mode live --duration-s 30 --device 14 --out work/W12/live_run
python work/W12/reference_station.py --mode live --duration-s 30 --backend ffmpeg --out work/W12/live_run
```

### 3. Replay a Recorded WAV File into Frozen `LOCAL_STATION` Parquet + 15s Cross-Check
```powershell
python work/W12/reference_station.py --mode replay `
  --in datasets/raw/enf-whu/repo/ENF-WHU-Dataset/H1/001.wav `
  --ref-in datasets/raw/enf-whu/repo/ENF-WHU-Dataset/H1_ref/001_ref.wav `
  --start-utc 1762000000 `
  --out work/W12/replay_001
```

### 4. Reproduce All Validation Experiments, `RESULTS.json`, and Figures in `work/W12/plots/`
```powershell
python work/W12/validate_station.py
```

### 5. Re-run Live API & Hardware Probes
```powershell
python work/W12/probe_environment_and_feeds.py
python work/W12/probe_live_details.py
```

---

## Key Output Artifacts
- [`work/W12/reference_station.py`](reference_station.py) — Reference station CLI and library (`load_local_station`, `extract_stream_array`, `crosscheck_station_vs_15s_ref`).
- [`work/W12/OPERATOR.md`](OPERATOR.md) — Venue operator manual and hum-source setup guide.
- [`work/W12/RESULTS.json`](RESULTS.json) — All measured experimental metrics with denominators.
- [`work/W12/FINDINGS.md`](FINDINGS.md) — Scientific and API findings with primary citations and evidence grades.
- [`work/W12/FAILURES.md`](FAILURES.md) — Documented failure modes and real failure cases (`001.wav` speech/motion interference, low-SNR breakdown, uncoupled mic).
- [`work/W12/HANDOFF.md`](HANDOFF.md) — Promotion recommendations and deck-worthy plot manifest.
- [`work/W12/plots/`](plots) — Deck-ready PNG figures.
