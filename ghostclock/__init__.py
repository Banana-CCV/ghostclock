"""GhostClock: ENF (electrical network frequency) evidence-corroboration core.

Modules
  audio_enf     mains-hum ENF trace from audio            (from experiments/c1_enfwhu_unseen_holdout/enf.py)
  rs_enf        rolling-shutter ENF trace from video      (from experiments/c4_video_rolling_shutter/rs_enf.py)
  gb_reference  GB grid-frequency reference (NESO 1 s / Elexon 15 s)  (from experiments/c2_...)
  matcher       sliding weighted NCC + calibrated null + baselines    (from experiments/w10_...)
  policy        deterministic decision gate: MATCH_SUPPORTED / INCONCLUSIVE / MATERIAL_DISCREPANCY_REVIEW

Heavy dependencies are imported lazily by each module; `import ghostclock` itself is cheap.
"""
__version__ = "0.1.0"
__all__ = ["audio_enf", "rs_enf", "gb_reference", "matcher", "policy"]
