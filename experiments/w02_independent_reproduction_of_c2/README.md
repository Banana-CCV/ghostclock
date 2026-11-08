> **Release note.** Gemini worker W02's independent reproduction of C2. The director used it as the grade-A evidence for the feasibility table ([FINAL report §3](../../docs/EVIDENCE.md)). Scripts, results and plots are included; no raw data.

# GhostClock W02 — GB Grid-Frequency Reference Data (NESO 1 s + Elexon BMRS 15 s)

Owner of Great Britain (GB) mains grid-frequency reference data (`NESO` 1-second historical archive + `Elexon BMRS` 15-second near-real-time feed) and independent reproducer of `C2` (`agents/reviews/W02_reproduce_C2.md`).

---

## 1. Key Deliverables in `work/W02/`

| File | Purpose |
|---|---|
| [`work/W02/gb_reference.py`](gb_reference.py) | Production loader implementing `load_reference(start_utc, end_utc, source)` (`integration/interfaces.md` §2) + CLI (`--inventory`, `--source NESO\|ELEXON\|AUTO`, `--out`). Enforces `[47.0, 52.0] Hz` range gate, masks flat-filled NESO outages ($\ge 120\text{ s}$), and exports `NESO_BST_SHIFTED_MONTHS`. |
| [`work/W02/elexon_archiver.py`](elexon_archiver.py) | Deduplicated Elexon BMRS `/system/frequency/stream` poller writing `datasets/raw/elexon/live_archive.parquet` + `.json`. |
| [`agents/reviews/W02_reproduce_C2.md`](W02_reproduce_C2.md) | Independent claim-by-claim reproduction of `C2` (`work/C2/`), including the full-month `2025-12`, `2026-01`, `2026-02` transition audit (`2026-02-13` scatter onset) and $n=400$ 24 h feasibility benchmark. |
| [`work/W02/FINDINGS.md`](FINDINGS.md) | Full technical report with primary citations, `[-3700, +3700] s` lag sweep on Sep 2026 vs Nov 2025, 21-month NESO timezone/transducer audit (`2025-01`..`2026-09`), and Dev/Holdout cross-check tables. |
| [`work/W02/RESULTS.json`](RESULTS.json) | Machine-readable structured results with exact denominators ($N$) and SHA-256 dataset manifest. |
| [`work/W02/FAILURES.md`](FAILURES.md) | Real-world data anomalies caught and mitigated (`0.0 Hz` Elexon SCADA dropouts, `2025-04..2025-10` `+3600 s` BST shifts, `2026-09-15` 3.1 h NESO flat-filled outage, midnight date-only rows). |
| [`work/W02/HANDOFF.md`](HANDOFF.md) | Integration handoff for `W10`, `W11`, `W12`, `W17`, `W18` and deck-worthy figure captions. |
| [`work/W02/plots/`](plots) | Deck-worthy PNG plots (`c2_reproduction_transition_and_feasibility.png`, `sep2026_vs_nov2025_lag_and_regime_diagnosis.png`, `neso_vs_elexon_crosscheck.png`, `elexon_nov2025_dropout_failure_case.png`). |

---

## 2. Exact Commands to Reproduce from Repo Root (`<WORKSPACE>`)

### A. Query Local Parquet Inventory (`NESO` + `ELEXON`)
```powershell
python work/W02/gb_reference.py --inventory
```

### B. Load Reference Data via CLI or Python (`integration/interfaces.md` §2)
```powershell
# Load 10 minutes of 1-second NESO historical reference (601 rows):
python work/W02/gb_reference.py --start-utc 2026-09-29T12:00:00Z --end-utc 2026-09-29T12:10:00Z --source NESO

# Load 15 minutes of 15-second Elexon reference from local today archive (61 rows):
python work/W02/gb_reference.py --start-utc 2026-11-08T09:00:00Z --end-utc 2026-11-08T09:15:00Z --source ELEXON --no-network
```

Python import:
```python
from work.W02.gb_reference import load_reference, get_neso_month_utc_offset_s

df_1s = load_reference(1790683200, 1790683800, source="NESO")     # DataFrame[ts_utc: int64, f_hz: float64]
df_15s = load_reference(1794128400, 1794129300, source="ELEXON")  # DataFrame[ts_utc: int64, f_hz: float64]
```

### C. One-Shot Refresh of `datasets/raw/elexon/live_archive.parquet`
*(Note: C2's background daemon is already polling `datasets/raw/gb/elexon_live.parquet`; use `--once` to avoid starting a second daemon.)*
```powershell
python work/W02/elexon_archiver.py --once
```

### D. Reproduce All W02 Audits, Cross-Checks & C2 Reproduction
```powershell
# 1. Convert & verify NESO/Elexon datasets:
python work/W02/fetch_and_inspect_neso_elexon.py

# 2. Run Dev/Holdout NESO vs Elexon cross-check & failure-case plots:
python work/W02/crosscheck_neso_elexon.py

# 3. Run [-3700, +3700] s lag sweep on Sep 2026 & 21-month (2025-01..2026-09) audit:
python work/W02/diagnose_sep2026_and_all_months_lags.py

# 4. Run independent reproduction of C2 (Dec 2025–Feb 2026 full-month transition audit + n=400 feasibility table):
python work/W02/reproduce_c2_and_transition.py
```
