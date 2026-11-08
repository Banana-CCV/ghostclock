# GhostClock case GC-2D54CEB7 (case_d, argon)

**Status (code gate): INCONCLUSIVE**

- media duration 49 s < shortest calibrated length 60 s (C1 holdout: 1-min coverage 9/135, 5-min 105/135; need >= 5-10 min of usable hum)

## Argon explanation
This recording has a total duration of 49.39 s, which is shorter than the minimum calibrated window length of one minute required for a reliable Electrical Network Frequency (ENF) match. The extracted audio trace contains 34 frames spanning from 8.0 s to 41.0 s with a median signal quality of 11.86 dB and a median frequency of 49.9692 Hz (standard deviation 7.29 mHz). The extracted video trace contains 42 frames spanning from 3.999249999979968 s to 44.99156249977464 s with a median signal quality of 17.29 dB and a median frequency of 49.9735 Hz (standard deviation 11.0 mHz). Because neither the 49.39 s recording nor its usable signal spans are long enough to support a calibrated comparison against the 130891 s grid-frequency reference window (interpolated to 1 s from 15 s Elexon measurements), the automated gate must classify the result as inconclusive.

## What would change this conclusion
- Providing a longer, unedited version of the recording that exceeds the minimum calibrated window length rather than the current 49.39 s duration.
- Obtaining continuous audio or video ENF traces longer than the current 34 audio frames (8.0 s to 41.0 s) and 42 video frames (3.999249999979968 s to 44.99156249977464 s) so a calibrated correlation window can be evaluated against the 130891 s reference window.
- Supplying corroborated external metadata or a narrower permitted reference window than 130891 s alongside a sufficiently long recording that meets the calibrated correlation threshold.

## Tool calls

Argon calls: 1, tokens {'input': 8188, 'output': 6400, 'thinking': 5749, 'total': 14588}, latency 165.0 s

Post-hoc evaluation (hidden from agent): {'expected': 'INCONCLUSIVE', 'status_as_expected': True}