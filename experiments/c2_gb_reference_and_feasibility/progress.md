# C2 progress (GB reference data)

- 09:41Z Probed Elexon `/system/frequency` live: 15 s cadence, UTC 'Z', 7-day max span, offsets in from/to honoured.
- 09:42Z `elexon_archiver.py` written, tested `--once` (backfill 2026-11-07 00:00Z -> now, 8088 rows, 0 missing), started detached via WMI Win32_Process.Create (pythonw).
- 09:43Z NESO CKAN package listed (153 monthly resources, Jan 2014 .. Sep 2026). Downloaded Aug 2026, Sep 2026, Oct 2025; converted to frozen parquet + sidecars.
- 09:45Z Found Elexon 0.0 placeholders (outages) -> archiver now stores NaN; restarted archiver (new PID).
- 09:50Z Cross-check: Oct 2025 NESO is +3600 s vs Elexon for the whole month (incl. after DST end). Downloaded Nov 2025, Mar 2026, Jun 2026 to localise; per-day lag scan running.
- 10:10Z Found flat-filled NESO outages (Sep 15 2026 3.1 h, Mar 31 2026 8 min) -> `bad_intervals` in sidecars, masked by loader.
- 10:10Z `gb_reference.py` loader + CLI written and tested (NESO, ELEXON, ELEXON --fetch).
- 10:10Z Feasibility probe running (4 parallel processes, n=1000 per D).
- 10:15Z Lag scan done: Elexon is a point sample of NESO 1 s (lag 0, 88 pct identical) through Nov 2025; Oct 2025 NESO file is +3600 s all month (correction written); 2026 months lag 0 but Elexon has 3-6 mHz extra scatter.
- 10:20Z Feasibility done (sigma 2 mHz: NESO 1 s, NESO 15 s pt/avg, REAL Elexon 15 s; plus sigma 10 mHz sensitivity), n=1000 per cell.
- 10:25Z RESULTS.json, FINDINGS.md, README.md written; archiver still running.
