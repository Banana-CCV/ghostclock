# GhostClock case GC-5A53FE21 (case_e, fixed)

**Status (code gate): MATERIAL_DISCREPANCY_REVIEW**

- peak NCC 0.99959 > frozen threshold 0.95531 for 300 s
- claimed start differs from the ENF-supported start by -7200 s (> 60 s tolerance)

## Tool calls
0. audio h=[1, 2, 3, 4, 5, 6, 7] win=325+300 s: peak 0.99959 (thr 0.95531), margin 0.03861, start 50769.25 s

Argon calls: 0, tokens {'input': 0, 'output': 0, 'thinking': 0, 'total': 0}, latency 0 s

Post-hoc evaluation (hidden from agent): {'expected': 'MATERIAL_DISCREPANCY_REVIEW', 'status_as_expected': True, 'start_error_s': 0.2}