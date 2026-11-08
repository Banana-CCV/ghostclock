# GhostClock case GC-5D3E3A38 (case_a, argon)

**Status (code gate): MATCH_SUPPORTED**

- peak NCC 0.99967 > frozen threshold 0.87678 for 600 s

## Argon explanation
The 734.0 s audio recording exhibits strong mains-hum signal quality across harmonics 2, 3, 4, and 6, with median SNRs of 193.02, 125.59, 280.63, and 183.63, a median frame quality of 22.81 dB, and 1.0 of frames at or above 10 dB. Using the 600 s analysis window starting at 0 s with harmonics 2, 3, 4, and 6, the extracted ENF trace (standard deviation 21.25 mHz and valid frame fraction 1.0) matched the 86349 s (24 h, 50 Hz) reference window with a peak normalised cross-correlation of 0.99967. This peak correlation substantially exceeds the frozen threshold of 0.87678 for a 600 s window and stands well above the second-highest peak of 0.78237, giving a margin of 0.2173 and a z-score of 3.33. Consequently, the analysis supports an implied media start at 50769.22 s within the reference window.

## What would change this conclusion
- An external claimed start time that differs from the supported media start of 50769.22 s beyond the permitted discrepancy tolerance would change the gate outcome to MATERIAL_DISCREPANCY_REVIEW.
- Another threshold-passing configuration within the 734.0 s recording yielding an implied media start that disagrees by more than 5 s from 50769.22 s would change the outcome to INCONCLUSIVE.
- Evidence that the 86349 s (24 h, 50 Hz) reference trace does not cover the true geographic grid or date window of the recording would invalidate the supported match at 50769.22 s.

## Tool calls
0. audio h=[2, 3, 4, 6] win=0+600 s: peak 0.99967 (thr 0.87678), margin 0.2173, start 50769.22 s

Argon calls: 2, tokens {'input': 10443, 'output': 6872, 'thinking': 5936, 'total': 17315}, latency 119.5 s

Post-hoc evaluation (hidden from agent): {'expected': 'MATCH_SUPPORTED', 'status_as_expected': True, 'start_error_s': 0.17}