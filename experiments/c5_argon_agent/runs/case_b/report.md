# GhostClock case GC-C4376B82 (case_b, argon)

**Status (code gate): INCONCLUSIVE**

- basis match peak NCC 0.67104 <= frozen threshold 0.95531 for 300 s

## Argon explanation
The 465.0 s audio-only recording contains a weak and noisy mains-hum signal, with a median frame quality of 5.74 dB, a trace standard deviation of 45.65 mHz across all harmonics, and a 0.084 fraction of frames reaching at least 10 dB. Testing the longest fitting calibrated window of 300 s starting at 0 s using the highest-SNR harmonics (4, 5, 6, and 7, with median SNRs of 10.72, 7.07, 8.05, and 8.56) yielded a valid frame fraction of 0.36 and a peak correlation (NCC) of 0.66101 against the 86350 s reference window. Testing the same 300 s window with only the strongest harmonic (harmonic 4, median SNR 10.72) produced a valid frame fraction of 0.33 and a peak NCC of 0.67104 (second peak 0.63899, margin 0.03206, z-score 3.64). Both correlation peaks fall far below the required 0.95531 threshold for a 300 s window and point to inconsistent candidate start offsets in the reference trace (14847.64 s versus 69438.95 s). Because the extracted ENF trace is too degraded to produce a statistically reliable match, the result is inconclusive.

## What would change this conclusion
- A cleaner audio source with median frame quality above 5.74 dB, a fraction of frames at or above 10 dB higher than 0.084, and a valid frame fraction above 0.36 so that a 300 s window achieves a peak NCC above the 0.95531 threshold.
- Agreement between harmonic configurations on the implied media start offset within the 86350 s reference trace, rather than divergent offsets like 14847.64 s and 69438.95 s.
- Availability of a video modality with periodic lamp flicker to supplement the noisy audio trace.

Numbers not found in tool outputs (flagged): ['10', '10']

## Tool calls
0. audio h=[4, 5, 6, 7] win=0+300 s: peak 0.66101 (thr 0.95531), margin 0.00558, start 14847.64 s
1. audio h=[4] win=0+300 s: peak 0.67104 (thr 0.95531), margin 0.03206, start 69438.95 s

Argon calls: 3, tokens {'input': 25131, 'output': 12259, 'thinking': 11091, 'total': 37390}, latency 208.5 s

Post-hoc evaluation (hidden from agent): {'expected': 'INCONCLUSIVE', 'status_as_expected': True}