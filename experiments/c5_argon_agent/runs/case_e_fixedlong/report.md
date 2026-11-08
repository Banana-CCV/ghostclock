# GhostClock case GC-5A53FE21 (case_e, fixed_long)

**Status (code gate): MATERIAL_DISCREPANCY_REVIEW**

- peak NCC 0.99966 > frozen threshold 0.87678 for 600 s
- claimed start differs from the ENF-supported start by -7200 s (> 60 s tolerance)

## Tool calls
0. audio h=[1, 2, 3, 4, 5, 6, 7] win=0+600 s: peak 0.99966 (thr 0.87678), margin 0.21796, start 50769.23 s

Argon calls: 0, tokens {'input': 0, 'output': 0, 'thinking': 0, 'total': 0}, latency 0 s

Post-hoc evaluation (hidden from agent): {'expected': 'MATERIAL_DISCREPANCY_REVIEW', 'status_as_expected': True, 'start_error_s': 0.18}