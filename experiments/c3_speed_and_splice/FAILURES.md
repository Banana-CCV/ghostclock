# C3 failures and limitations (holdout numbers unless stated; k/n and Wilson 95% CI)

All manipulated clips are SYNTHETIC: ffmpeg speed changes, or numpy splices of real ENF-WHU
audio. ENF-WHU was recorded in Wuhan on a 50 Hz grid. None of it is GB footage and none of it is CCTV.

## Speed check

1. **The false-alarm rate on unmodified clips is above the 5 % dev target on holdout.**
   - Dev: 20/425 = 4.7 % [3.1, 7.2].
   - Holdout: 18/225 = 8.0 % [5.1, 12.3].
   - Holdout by length: 5 s 2/45, 8 s 4/45, 15 s 5/45, 30 s 4/45, 60 s 3/45.

   Cause: many ENF-WHU recordings contain non-mains tonal families from machinery and fans,
   for example a 48.66 Hz family in recording 090. When the 50 Hz family is weak, the comb
   locks onto these families.
2. **The detection rate is moderate, even for the motivating scenario.**
   - 8 s at 1.75x: 20/45 = 44 % [31, 59].
   - The same, restricted to clips whose 8 s original was judged CONSISTENT: 13/24 = 54 % [35, 72].
   - Dev, for comparison: 58/85 = 68 % [58, 77].
   - Overall, holdout asetrate: 819/2475 = 33 % [31, 35].
   - For k from 0.95 to 1.1, given the original was CONSISTENT: 370/735 = 50 % [47, 54].

   About 26 % of altered holdout clips return NO_GRID_SIGNAL (640/2475), because the ENF in
   ENF-WHU is often weak.
3. **Rational speed factors are nearly blind (octave and harmonic collisions).**
   Most ENF-WHU hum is the 100 Hz family. At k = 1.5 it moves to multiples of 150 Hz, which
   are still multiples of 50. The same happens at k = 2.0 (multiples of 200) and partly at
   k = 1.25 (250 = 5 x 50). Holdout TPR pooled over lengths:
   - k = 1.25: 24/225 = 11 %
   - k = 1.5: 20/225 = 9 %
   - k = 2.0: 29/225 = 13 %

   At 2.0x and 30 s, 38/45 clips are called CONSISTENT_WITH_REALTIME. This limit is physical:
   without a reference, "100 Hz family with no 50 Hz fundamental at k = 1" cannot be told
   apart from "50 Hz family at k = 2".
4. **The k estimate is unreliable, even when the flag is correct.**
   - Among holdout detections at 8 s / 1.75x, k is within 1 % of the truth in only 1/20.
   - The comb's best family is often a non-mains tonal family scaled by k. Typical ratios
     k_hat/k are 0.96-0.98, 0.60, 0.80 and 1.26.
   - The demo clip from recording 120 is flagged correctly, but its k_hat is 1.86.
   - Use the flag. Treat k as a hint only, and only when the explained lines match the
     n x 50k pattern by eye (see `plots/spectrum_orig_vs_1.75x_8s.png`).
5. **The bootstrap CI is far too narrow: it measures precision, not accuracy** (`eval/ci_check.json`).
   - For originals that were called CONSISTENT, the measurement CI (relative to 50.000 Hz)
     covers k = 1 in only 1/24 clips at 8 s and 4/29 at 30 s. The real grid frequency is not
     exactly 50.000 Hz, and the sub-window bootstrap ignores that.
   - The CI that adds the +/-0.2 Hz grid band covers k = 1 in 19/24 (8 s) and 24/29 (30 s).
   - For correctly detected 1.75x clips, coverage is 0/20 (8 s) and 0/24 (30 s), because the
     wrong family was selected (point 4).
   - Report only the grid-band interval, and only together with the CONSISTENT decision.
6. **atempo (tempo change with pitch preserved) is invisible as a speed change, as expected.**
   - Holdout SPEED_ALTERED rate: 3/990 = 0.3 % [0.1, 0.9]. Dev: 5/1870.
   - It is not called CONSISTENT either (35/990 = 3.5 %). 946/990 = 95.6 % come back as
     NO_GRID_SIGNAL: WSOLA time-stretching breaks the phase continuity of the hum, so its
     lines smear into the noise floor.
   - In short: the hum frequency is not shifted, so the check cannot measure k. The
     manipulation also tends to destroy the hum evidence. A loss of hum is only a weak hint,
     because many genuine clips also lack hum.
7. **AMBIGUOUS_50_vs_60 is untested.** There is no 60 Hz data. On unmodified holdout clips it
   fires 17/225 times, all from coincidental lines at common multiples such as 300 Hz.
   amb_margin was not tuned.
8. **H0 (no-ENF recordings).**
   - Holdout: 120/120 NO_GRID_SIGNAL for originals, and 120/120 for synthetic 1.75x versions.
   - Dev was worse: 22/180 CONSISTENT and 5/180 SPEED_ALTERED (2.8 %). Some "no-ENF"
     recordings still contain tonal lines.
   - Only 4 holdout sources, so the CI is wide: [0.97, 1.0] over 120 clips, but the clips
     are not independent.
9. **Statistical caveats.**
   - There is one source segment per H1 recording, and the clip lengths are nested prefixes.
     Cells across L and k therefore share recordings and are not independent.
   - Wilson intervals treat clips as independent. The effective holdout n is about 45
     recordings in 15 day groups.
   - The split is 85/45 recordings (65/35), not 60/40, because one recording day holds 19
     recordings.

## Splice check

10. **It needs strong ENF.** The dev-tuned rule (line SNR >= 20 dB, theta = 1.55 rad) marks
    many clips NO_GRID_SIGNAL:
    - deletions: 160/450
    - insertions: 114/270
    - unmodified: 38/180
11. **Holdout detection.** "Localised" means a flag within 1.5 s of the true splice.
    | | All clips | Clips with a usable line |
    |---|---|---|
    | Deletions (1-30 s) | 59/450 = 13 % [10, 17] | 59/290 = 20 % [16, 25] |
    | Insertions (2-10 s) | 89/270 = 33 % [28, 39] | 89/156 = 57 % [49, 65] |

    A deletion of d seconds shifts the phase by 2*pi*f*d (mod 2*pi), which is often small, so
    many deletions are undetectable in principle. The dev-to-holdout gap is small (dev
    deletions localised 129/850 = 15 %).
12. **False alarms on unmodified clips with a usable line.**
    - Holdout: 12/142 = 8.5 % [4.9, 14.2] (dev 14/285 = 4.9 %). Above target on holdout again.
    - At 30 s: 9/77 = 11.7 %. Longer clips give more chances for a noise-induced jump.
    - The clip edges (2.5 s) are excluded, so a splice in the first or last 2.5 s cannot be found.
13. Splices were made by sample-exact concatenation (numpy) with no cross-fade and no
    re-encoding. Real edits with fades or codecs will behave differently. This was not tested.

## Engineering
- The machine was saturated by other workers (Python import took about 90 s), so the evaluation
  grid was budgeted: atempo was run at 8 s and 30 s only, and splices at 15 s and 30 s.
- Bugs found and fixed before the final run: `pick_line` compared frequency instead of SNR.
  The pre-fix test output is kept as `eval/features_test_run_buggy.jsonl` and is not used.
- The H0 crop-to-source map (`h0_crop_map.json`) is uncertain: the minimum NCC is 0.368, and
  O01/O10 received no crops. Only O-files are used in the evaluation.
