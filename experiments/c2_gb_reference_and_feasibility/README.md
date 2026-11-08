# work/C2: GB grid-frequency reference (Elexon live + NESO 1 s)

## Data (datasets/raw/gb/)
All files are in the frozen format: Parquet with `ts_utc` int64 epoch s (UTC) and `f_hz` float64, plus a sidecar `.json` with {source, cadence_s, grid, coverage, url, sha256}.

- `elexon_live.parquet`: 15 s data, kept current by the archiver. Backfilled from 2026-11-07 00:00Z.
- `elexon_YYYY_MM.parquet`: 15 s Elexon data for the months that have NESO overlap (used in the cross-check).
- `neso_YYYY_MM.parquet`: 1 s data for 2025-10, 2025-11, 2026-03, 2026-06, 2026-08 and 2026-09.
  - Sidecars may contain `bad_intervals`: flat-filled outages that the loader masks.
- `neso_csv/`: the raw NESO CSVs as downloaded.

## Scripts
- `elexon_archiver.py`: polls every 120 s and appends new rows with dedup. Every 30 min it re-requests the last 24 h to heal gaps.
  - Logs to `archiver.log`; the PID is in `archiver.pid`; `archiver.lock` keeps it to a single instance.
  - `--once` backfills and exits.
  - Start it detached with PowerShell, using WMI so it survives the parent shell:
    Invoke-CimMethod Win32_Process -MethodName Create -Arguments @{CommandLine="<repo>\.venv\Scripts\pythonw.exe <repo>\work\C2\elexon_archiver.py"; CurrentDirectory="<repo>"}
  - Stop it: Stop-Process -Id (Get-Content work\C2\archiver.pid). Also stop its venv launcher parent.
- `gb_reference.py`: load_reference(start_utc, end_utc, source="NESO"|"ELEXON", fetch=False) returns a regular grid with NaN where data is missing.
  - CLI: python work/C2/gb_reference.py --source ELEXON --start 2026-11-08T09:00Z --end 2026-11-08T10:00Z [--out ref.parquet] [--fetch]
  - NESO per-month time corrections come from `neso_time_corrections.json`. Oct 2025 is shifted by -3600 s.
- `neso_convert.py`: converts a NESO CSV to parquet and sidecar, and prints QC.
- `crosscheck.py`, `lagscan.py`: compare Elexon with NESO (lag, RMSE). Outputs go to crosscheck*.json and lagscan.json.
- `feasibility.py`: the semi-synthetic NCC dating probe. Outputs go to feas_runs/.

## Results
- FINDINGS.md (with URLs), RESULTS.json, progress.md.
- plots/neso_vs_elexon_1h.png.
