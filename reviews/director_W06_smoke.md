# Director review: W06 smoke claim (2026-11-08 ~09:50)
Claim: W06 audio_enf on ENF-WHU H1/003 gives r=0.976, RMSE 5.48 mHz vs the reference.
Check: independent STFT (16 s Hann, 1 s hop, 16× zero-pad, log-parabolic interpolation) on H1_ref/003_ref.wav (400 Hz); W06's trace compared at matching window centres. Script: agents/reviews/director_verify_w06.py.
Result: r=0.9760, RMSE 5.47 mHz (de-meaned 3.85 mHz) → **REPRODUCED (grade B, one clip)**.
Finding: the zero-lag correlation is 0.977, but at a −4 s shift it is **0.9994**. This is a systematic ~4 s offset between the W06 time axis and the reference: a convention bug (window start vs centre / filter delay) or a dataset alignment offset. It must be resolved before quoting timestamp accuracy; it affects W10's matcher tolerance and C1's results.
