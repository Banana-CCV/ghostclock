# GhostClock case GC-2D54CEB7 (case_d, argon)

**Status (code gate): INCONCLUSIVE**

- media duration 53 s < shortest calibrated length 60 s (C1 holdout: 1-min coverage 9/135, 5-min 105/135; need >= 5-10 min of usable hum)

## Argon explanation
The submitted recording has a total duration of 52.99156249977464 seconds, which falls below the minimum sixty-second duration required for calibrated Electrical Network Frequency matching. Within the recording, the usable audio trace contains 34 frames spanning from 8.0 to 41.0 seconds with a median quality of 11.86 dB and a median frequency of 49.9692 Hz. The video trace contains 42 frames spanning from 3.999249999979968 to 44.99156249977464 seconds with a median quality of 17.29 dB and a median frequency of 49.9735 Hz. Because neither the overall clip nor the extracted traces are long enough to accommodate the shortest calibrated analysis window against the 130891-second reference window, the result is inconclusive.

## What would change this conclusion
- A longer unedited recording extending beyond the current 52.99156249977464-second duration so that it meets the minimum calibrated window requirement.
- Continuous audio or video ENF traces spanning a full calibrated window rather than the current 34 audio frames (8.0 to 41.0 seconds) and 42 video frames (3.999249999979968 to 44.99156249977464 seconds).
- Additional contiguous recordings from the same session that can be evaluated against the 130891-second reference window.

## Tool calls

Argon calls: 1, tokens {'input': 8193, 'output': 9120, 'thinking': 8545, 'total': 17313}, latency 124.5 s

Post-hoc evaluation (hidden from agent): {'expected': 'INCONCLUSIVE', 'status_as_expected': True}