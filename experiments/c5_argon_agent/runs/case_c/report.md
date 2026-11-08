# GhostClock case GC-B3305B14 (case_c, argon)

**Status (code gate): INCONCLUSIVE**

- basis match peak NCC 0.78438 <= frozen threshold 0.87678 for 600 s

## Argon explanation
The 734.0 s audio recording contains a clean electrical hum signal, with a median frame quality of 22.81 dB, a valid frame fraction of 1.0, and strong median signal-to-noise ratios on harmonics 2, 3, 4, and 6 (193.02, 125.59, 280.63, and 183.63). Using the longest calibrated 600 s analysis window starting at 0 s across harmonics 2, 3, 4, and 6, the highest correlation against the 86350 s (24 h) 50 Hz reference trace is 0.78438 (with a second-best peak of 0.74538, margin of 0.039, and z-score of 3.07), which falls well below the required threshold of 0.87678. A second 600 s analysis window starting at 134 s using harmonics 2, 4, and 6 also failed to meet the 0.87678 threshold, reaching a peak correlation of 0.74851 (with a second-best peak of 0.73477, margin of 0.01375, and z-score of 2.95). Because the extracted frequency trace does not match the provided reference trace above the required threshold, the dating result is inconclusive.

## What would change this conclusion
- Comparing the extracted audio trace against a different 24 h (86350 s) 50 Hz grid reference window covering another date range or grid region, in case the recording occurred outside the permitted reference period.
- Obtaining a 600 s match whose peak normalised cross-correlation exceeds the frozen threshold of 0.87678 with consistent implied media start times.
- Receiving verified recording hardware information or an alternative synchronous reference trace to determine whether sampling-rate drift degraded correlation with the 50 Hz grid trace.

## Tool calls
0. audio h=[2, 3, 4, 6] win=0+600 s: peak 0.78438 (thr 0.87678), margin 0.039, start 50923.11 s
1. audio h=[2, 4, 6] win=134+600 s: peak 0.74851 (thr 0.87678), margin 0.01375, start 50924.01 s

Argon calls: 3, tokens {'input': 25144, 'output': 13366, 'thinking': 12139, 'total': 38510}, latency 204.7 s

Post-hoc evaluation (hidden from agent): {'expected': 'INCONCLUSIVE', 'status_as_expected': True}