# W15 Findings — Forensic UX Design, Literature Grounding & Prototype Critique

## 1. Source-Grounded Forensic Visualization & Regulatory Principles (Evidence Grade: C for Literature, B for Executed Prototype Verification)

1. **Separating Model Judgement from Deterministic Calculation (`Traceable Reasoning — 25%`):**
   - Drawing on Grigoras (2007, *Forensic Science International*, DOI: `10.1016/j.forsciint.2006.06.033`) and the *ShadowStop* winning pattern (`sources/SHADOWSTOP_REFERENCE.md`), a forensic UI must never present an LLM text summary as evidence of a timestamp.
   - In both `proto_A` and `proto_B`, **Gemini 4 Argon's role** is visually bounded to the *Investigation Replay* panel (inspecting frame geometry/audio spectrum, selecting candidate ROIs or harmonic combs, and adapting when rejected). **Deterministic code** owns the STFT/rolling-shutter trace extraction, the 259,200-second cross-correlation landscape, the block-permutation null threshold, and the final status badge.

2. **Visualizing Rolling-Shutter & Harmonic Failure Modes (`Ambition — 15%`):**
   - Following Garg et al. (2011, *ACM Multimedia*, DOI: `10.1145/2072298.2072303`) and Vatansever et al. (2019, *IEEE TIFS*, DOI: `10.1109/TIFS.2019.2895540`), naive mean-frame brightness or saturated/DC-inverter LED fixtures fail to recover 100 Hz mains flicker.
   - We surfaced this directly in **Case 1 (`GC-2026-8841`)**: Argon's Attempt 1 targets an overhead LED strip, which the deterministic verifier rejects (`frac_valid = 0.31 < 0.60`, `snr_db = -2.4 dB`). Users can click **`Inspect Rejected Attempt 1 Trace`** in both prototypes to overlay the rejected noisy trace (`#f43f5e`) against the accepted Attempt 2 multi-harmonic audio trace (`#38bdf8`, `RMSE = 4.3 mHz`).

3. **Null Calibration & Search-Space Honesty (`Testing on Unseen Data — 25%`):**
   - Following Hua et al. (2021, *IEEE TIFS*, DOI: `10.1109/TIFS.2021.3099697`), searching a 72-hour window (`259,200` candidate seconds) guarantees spurious background peaks around $r \approx 0.35\text{–}0.45$.
   - Every Match-Landscape chart in `proto_A` and `proto_B` plots the full candidate horizon alongside a prominent red dashed **Null Threshold (`score_threshold = 0.540`, `H0 n = 5000`, `p_empirical`)** and annotates both the **Best Peak** and **2nd-Best Peak (`margin_vs_second`)**.

4. **Regulatory Guardrails & Non-Denial Policy (`Risk Controls — 15–20%`, `Relevance — 15–20%`):**
   - Under **FCA Handbook `ICOBS 8.1.1R`** (fair and prompt claims handling) and **UK GDPR / ICO Video Surveillance Guidance**, an automated system must never deny an insurance claim or label a policyholder fraudulent based on an environmental signal mismatch (which could arise from an islanded generator, UPS inverter, or re-encoded file).
   - Both prototypes enforce a **Human-in-the-Loop Decision Gate** where *"Auto-Deny Claim / Allege Fraud"* is visibly disabled in code, and every verdict includes a dedicated **"What Would Change This?"** counterfactual panel.

---

## 2. Comparative Critique of Prototype A vs. Prototype B (Based on Rendered Headless Screenshots)

We rendered both prototypes at `1680x1050` across three core scenarios (`Case 1: Discrepancy Loop`, `Case 2: Safeguard Inconclusive`, `Case 3: W13 Speed/Splice Tampering`) using headless Chromium (`work/W15/plots/proto_A_*.png` and `work/W15/plots/proto_B_*.png`).

| Evaluation Dimension | Prototype A (`proto_A` — Case File & SIU Dossier) | Prototype B (`proto_B` — Signal Lab Workbench) | Winner & Recommendation |
|---|---|---|---|
| **10-Second Comprehensibility for Non-DSP Finance Judges** | **Very High.** The numbered 1→9 dossier cards read left-to-right like an institutional compliance/credit memo: *Claim Context → Blinding Lock → Argon Replay → Signal Match → Decision Gate*. | **Moderate-High.** High-density dark scientific instrumentation immediately signals deep technical ambition, but requires ~15 seconds to orient between the optical ROI viewport (Pane A) and the top-K table (Pane E). | **`proto_A`** for opening claim framing & human governance; **`proto_B`** for technical deep-dive. |
| **Visualizing the ShadowStop Propose → Reject → Revise Loop** | **Strong narrative clarity:** Attempt #1 (`VERIFIER: REJECTED` in crimson) and Attempt #2 (`VERIFIER: ACCEPTED` in emerald) sit directly above the trace plot with explicit tool calls and threshold formulas. | **Strong spatial clarity:** Pane A visually renders the rejected ceiling ROI (`ROI #1`) vs. the accepted wall bounce + audio harmonic region (`ROI #2`) directly on a simulated CMOS rolling-shutter frame. | **Tie (Complementary):** Combining `proto_B`'s ROI viewport with `proto_A`'s step cards is ideal. |
| **Above-the-Fold Viewport Density (`1680x1050`)** | **Iteration Required (Fixed in Step G):** In our initial v1 render, `proto_A`'s center column clipped the bottom 45% of the Match Landscape plot and the Export button at `1050px` height. After Step G vertical compaction (`165px` SVG height, tighter card padding), all 9 panels and the Export button fit cleanly above the fold. | **Fit on First Pass:** All 7 panes (A–G), including both SVG plots and the Top-K candidate table, rendered 100% above the fold at `1680x1050`. | **`proto_B`** has naturally higher vertical efficiency; **`proto_A` (v2)** now also fits cleanly. |
| **Safeguard & `INCONCLUSIVE` Presentation (`Case 2`)** | Displays an authoritative amber forensic shield (`SAFEGUARD TRIGGERED: Best candidate correlation 0.438 is BELOW the code-enforced null threshold 0.540`) alongside actionable next steps. | Clearly highlights the sub-threshold peak trapped inside the red shaded null rejection zone on the Match Landscape plot. | **Both succeed** in making `INCONCLUSIVE` look rigorous rather than broken. |
