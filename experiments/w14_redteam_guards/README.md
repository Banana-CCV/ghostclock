> **Release note: INCOMPLETE.** Gemini worker W14 wrote a threat model, a plan, attack code and guard code, but **produced no evaluation results**. `RESULTS.json`, `FINDINGS.md`, `FAILURES.md` and `ATTACK_MATRIX.md`, which are referenced below, do not exist. No robustness claim is made from this folder.

# GhostClock Worker W14: Adversarial Red Team & Defensive Guard Suite (`work/W14/`)

## 1. Overview
Worker **W14** is the adversarial red team and stress-testing authority for **GhostClock**. Our module systematically evaluates **7 adversarial attack families (`a`–`g`, 29 parameter variants)** against three pipeline tiers:
1. **Tier 1 (`M0_naive`):** Unguarded STFT multi-harmonic extractor + sliding FFT Normalized Cross-Correlation (NCC) baseline (`r_peak >= 0.42` / naive i.i.d. Fisher-$z$).
2. **Tier 2 (`W06_W10_base`):** Current production `W06` multi-harmonic consensus extractor (`work/W06/audio_enf.py`) + `W10` look-elsewhere & split-half calibrated matcher (`work/W10/matcher.py` + `work/W10/policy.py`), imported read-only **without** W14 adversarial guards.
3. **Tier 3 (`W06_W10_W14_guarded`):** Full hardened pipeline combining `W06 + W10` with W14's **6 deterministic code-enforced guards (`G1`–`G6`)**.

All experiments strictly respect `eval/splits/enf_whu_split.json` (**zero holdout files touched**) and explicitly label all synthetic GB grid experiments generated from real NESO 1-second frequency data (`2026-08-01` vs `2026-09-01`) as `[SYNTHETIC-NESO]`.

---

## 2. Directory Contents
- [`ORIENT.md`](ORIENT.md): Threat model, physical assumptions, sibling interfaces, and falsification criteria.
- [`PLAN.md`](PLAN.md): Pre-registered attack families `(a)`–`(g)`, guard definitions `G1`–`G6`, dataset hygiene, and hypotheses `H1`–`H4`.
- [`attacks.py`](attacks.py): Deterministic, seed-fixed (`seed=20261108`) implementation of all 7 attack families:
  - `(a)` Cascade IIR notch removal (`50 Hz` only; `50, 100, 150 Hz`; all harmonics `50..350 Hz` at `Q=35` and `Q=15`).
  - `(b)` Continuous-phase FM sinusoid ENF injection (`100 Hz` single-tone, `h=1..4` multi-harmonic, over `H0` and `H1` across SNRs, plus `b4` white-box room-convolved multi-harmonic spoof).
  - `(c)` Double ENF (two concurrent grid traces mixed across all harmonics at `0 dB` and `+3 dB`, and harmonic-split odd vs even harmonics).
  - `(d)` Re-encoding & signal transforms (`ffmpeg` AAC 32 kbps, 20 kbps WhatsApp VoIP codec profile, MP3 64 kbps, stationary spectral gating noise suppression, `8000->11025->8000 Hz` resampling, `+2000 ppm` clock drift, WSOLA `atempo=1.05` & `1.25` time-stretch, `+0.5%` & `+2.0%` pitch shift).
  - `(e)` Short-duration cropping (`10s, 20s, 30s, 60s, 120s, 300s` against 24-hour reference).
  - `(f)` Splicing & concatenation (`50/50`, `70/30` asymmetric, `120s-60s-120s` middle overdub replacement, `120s-60s-120s` middle insertion shift, and cross-modal audio-vs-video spoofing).
  - `(g)` Metadata & container spoofing (`ffmpeg` RIFF `ICRD`/`creation_time` tags, spoofed filename, spoofed filesystem `mtime`, and mismatched `claimed_start_utc`).
- [`guards.py`](guards.py): Deterministic implementation of the 6 defensive guards (`G1`–`G6`):
  - `G1`: `spectral_notch_and_suppression_guard`
  - `G2`: `too_clean_injector_guard`
  - `G3`: `harmonic_consistency_and_pitch_guard`
  - `G4`: `multi_segment_splice_and_drift_guard`
  - `G5`: `duration_and_uniqueness_guard`
  - `G6`: `audio_video_agreement_guard`
- [`run_redteam_eval.py`](run_redteam_eval.py): End-to-end evaluation harness producing `RESULTS.json` (`work/W14/RESULTS.json`, not included in this repository) and diagnostic plots in `plots/` (`work/W14/plots/`, not included in this repository).
- `ATTACK_MATRIX.md` (`work/W14/ATTACK_MATRIX.md`, not included in this repository): Complete `attack × outcome × guard × residual risk` matrix and plain-English deck summary of what we cannot defend against.
- `FINDINGS.md` (`work/W14/FINDINGS.md`, not included in this repository), `FAILURES.md` (`work/W14/FAILURES.md`, not included in this repository), `HANDOFF.md` (`work/W14/HANDOFF.md`, not included in this repository).

---

## 3. Exact Reproduction Commands (Run from Repo Root)

### A. Run the single-file deterministic guard CLI on any audio clip
```powershell
python work/W14/guards.py --in datasets/raw/enf-whu/repo/ENF-WHU-Dataset/H1/001.wav --out work/W14/smoke_guard_001.json --nominal 50
```

### B. Generate demo attacked audio clips
```powershell
python work/W14/attacks.py --demo-out work/W14/demo_attacks
```

### C. Run the complete W14 Adversarial Red-Team Evaluation Suite & Regenerate Plots
```powershell
python work/W14/run_redteam_eval.py
```

### D. Dependencies
Uses the shared repository Python 3.12 virtual environment (`numpy`, `scipy`, `pandas`, `soundfile`, `matplotlib`) plus `ffmpeg` and `ffprobe` on `PATH`. No additional packages required.
