# GhostClock case GC-5A53FE21 (case_e, argon)

**Status (code gate): MATERIAL_DISCREPANCY_REVIEW**

- peak NCC 0.99967 > frozen threshold 0.87678 for 600 s
- claimed start differs from the ENF-supported start by -7200 s (> 60 s tolerance)

**Conflicts:** Argon proposed MATCH_SUPPORTED, gate decided MATERIAL_DISCREPANCY_REVIEW: gate wins

## Argon explanation
The 734.0 s audio recording contains a clean 50 Hz mains hum across harmonics 2, 3, 4, and 6, which exhibit high median signal-to-noise ratios of 193.02, 125.59, 280.63, and 183.63 respectively. Using these harmonics over a 600 s analysis window starting at 0 s yielded a valid frame fraction of 1.0 and a trace standard deviation of 21.25 mHz. Comparing this extracted trace against the 86349 s reference window produced a peak normalised cross-correlation of 0.99967, which substantially exceeds the frozen threshold of 0.87678. The best match stands well above the second-highest peak of 0.78237 by a margin of 0.2173 (z-score 3.33) and places the implied media start at 50769.22 s within the reference window.

## What would change this conclusion
- A claimed recording start time differing from the implied media start of 50769.22 s in the reference window would trigger a material discrepancy review.
- An additional passing analysis window whose implied media start disagrees with 50769.22 s would change the status to inconclusive.
- Evidence that the 86349 s reference window is from the wrong electrical grid or date range would invalidate the time alignment.

## Tool calls
0. audio h=[2, 3, 4, 6] win=0+600 s: peak 0.99967 (thr 0.87678), margin 0.2173, start 50769.22 s

Argon calls: 2, tokens {'input': 16515, 'output': 5675, 'thinking': 4889, 'total': 22190}, latency 100.6 s

Post-hoc evaluation (hidden from agent): {'expected': 'MATERIAL_DISCREPANCY_REVIEW', 'status_as_expected': True, 'start_error_s': 0.17}