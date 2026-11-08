# C5 progress

- 12:05 Read W18 (106 KB agent; its agy smoke test failed with `-p` flag misuse). Decided to write a compact agent in work/C5/agent.py instead of debugging W18.
- 12:10 agy smoke test with --json-schema: SUCCESS, structured_output returned, 30 s, ~8k tokens (agy_test_out.json).
- 12:20 agent.py written: C1 cache traces + C1 NCC matcher (read-only imports), director blind_match Elexon scan for the venue case, C1 frozen thresholds as the gate.
- 12:24 Fixed pipeline (no Argon) on cases a-e: reproduces C1's holdout parquet exactly (case_a peak 0.99959, case_c 0.95257, case_b 0.72111). All five statuses as expected.
- 12:25 Argon runs for cases a-d launched in parallel (logs/run_*.log).
- 12:29-12:33 Argon runs a-e complete: all 5 gate statuses as expected; case_e shows gate override (Argon MATCH_SUPPORTED -> gate MATERIAL_DISCREPANCY_REVIEW, hidden false claim).
- 12:30 Added --fixed-long ablation (all harmonics, longest calibrated window). Statuses identical to Argon on all 5 cases; Argon's useful choice (600 s window) is reproducible by the simple rule.
- 12:36 Fixed venue duration (ffprobe 49.39 s instead of trace-span estimate 52.99 s); re-ran case_d with Argon (INCONCLUSIVE). Old run kept in runs/case_d_superseded_bad_duration/.
- 12:42 README.md written. Totals: 11 Argon calls, 129,993 tokens, 798 s Argon latency.
