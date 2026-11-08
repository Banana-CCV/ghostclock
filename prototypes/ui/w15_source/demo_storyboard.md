# GhostClock — 4-Minute Finalist Pitch & Live Demo Storyboard (`W15`)

> **Epistemic & Provenance Notice:** Every figure, number, and screen state in this storyboard is explicitly badged below as **`REAL-MEASURED`**, **`SYNTHETIC`**, or **`ILLUSTRATIVE`**. In accordance with the AgentVerse Finance rubric and `integration/interfaces.md` v1, GhostClock separates **Gemini 4 Argon's multimodal investigative reasoning** (region selection, harmonic hypothesis generation, tool orchestration, and revision after counterexamples) from **deterministic code verification** (STFT/rolling-shutter signal extraction, cross-correlation, block-permutation null calibration, and hard decision gates).

---

## 1. Minute-by-Minute 4-Minute Pitch Schedule (240 Seconds)

| Time Window | Chapter / Stage | Visual on Screen | Spoken Narrative & Key Message | Rubric Criterion Targeted |
|---|---|---|---|---|
| **0:00 – 0:35** *(35 s)* | **1. The Financial Problem & Physical Insight** | Split screen: (Left) Fictional UK Commercial Property Claim `CLM-UK-2026-8841` (£24,500 escape-of-water reserve, video stated as Wed 14 Oct 21:15 UTC, 24h after policy inception). (Right) Live GB National Grid 50.000 Hz frequency trace (`NESO` 1-second feed) fluctuating by $\pm 50\text{–}150\text{ mHz}$. | *"Insurance Special Investigations Units face a costly binary trap: pay disputed video claims blindly in 48 hours, or spend £2,500+ on external forensic labs and risk unfair delay under FCA ICOBS 8. Every mains-powered room embeds the national grid's unique 50 Hz heartbeat into audio hum and 100 Hz rolling-shutter lighting flicker. GhostClock turns Gemini 4 Argon into an auditable forensic investigator—paired with a deterministic physics verifier that Argon cannot override."* | **Relevance & Impact (15–20%)**: Named user (SIU / Claims Investigator), concrete financial decision (clear vs. hold & request raw media), regulatory context (`FCA ICOBS 8.1.1R`). |
| **0:35 – 1:35** *(60 s)* | **2. The Argon Propose → Verifier Reject → Revise Loop** | Switch to **Prototype B (`proto_B/index.html?case=0`)** + **Prototype A (`proto_A/index.html?case=0`)**: Show **Blinding Lock** (`EXIF`, `CreateDate`, filename, and claimed time stripped). Replay **Attempt 1**: Argon selects bright overhead LED batten ROI (`analyse_video`); deterministic verifier **REJECTS** (`frac_valid = 0.31 < 0.60`, `snr_db = -2.4 dB`, switched-mode DC driver + pixel clipping). Replay **Attempt 2**: Argon adapts, masks clipped ceiling rows, and invokes multi-harmonic audio ridge tracking (`100/150/200 Hz`) + matte wall bounce ROI (`frac_valid = 0.95`, `snr_db = 14.2 dB` → **ACCEPTED**). | *"First, code blinds the file—stripping EXIF and withholding the claimant's stated timestamp from the search. Watch Argon investigate: its first proposal targets the overhead LED strip. A naive AI wrapper would hallucinate a match. Our deterministic verifier rejects Attempt 1 with an exact counterexample: pixel saturation and a DC inverter destroy the 100 Hz carrier (`frac_valid = 0.31`). Argon reads the diagnostic, masks the clipped region, and pivots to 100/150/200 Hz acoustic pump harmonics plus diffuse wall reflection."* | **Ambition & Technical Quality (15%)** + **Traceable Reasoning (25%)**: True ShadowStop-style propose–reject–revise loop; calculations strictly separate from model judgement. |
| **1:35 – 2:30** *(55 s)* | **3. Match Landscape, W13 Tampering & Financial Consequence** | Center stage **Match-Landscape Plot** across 259,200 candidate seconds (72 hours): Best peak locks at `r = 0.914` (`RMSE = 4.3 mHz`) on **Mon 12 Oct 21:14:20 UTC**—**48 hours before the stated loss and prior to policy inception**—far above the block-permutation **Null Threshold (`0.540`, `p = 0.0002`, `margin = +0.502`)**. Briefly toggle **Case 3 (`?case=2`)** showing **W13 Speed & Splice Check** (`53.120 Hz` carrier = `1.0624x` speed-up + `142.4°` splice jump at `t = 28.0 s`). | *"Across 259,200 candidate seconds, the extracted sequence locks uniquely to Monday 12 October at 21:14:20 UTC—48 hours before the stated claim time. And in Case 3, when a clip is sped up by 6.2% or spliced, W13 catches the 53.12 Hz carrier shift and 142-degree phase jump immediately. Every screen states exactly what evidence would change the finding—such as an islanded backup generator log or original camera card."* | **Traceable Reasoning (25%)**: Full search-space landscape, null calibration, counterfactual *"what would change this"*, and Scientific Rule #3 (no audio/video confidence multiplication). |
| **2:30 – 3:25** *(55 s)* | **4. Live Judge-Upload Challenge & Negative Safeguard Firing** | Switch to **Case 2 (`?case=1`) / Live Upload Intake**: Run an unfamiliar or short outdoor dashcam clip (`18 s`, VFR, battery/alternator powered). Show the correlation peak (`r = 0.438`) hitting the red **Code-Enforced Null Gate (`0.540`, `p_empirical = 0.184`)** and failing uniqueness (`margin = 0.027 < 0.15`). Watch the **Risk Control Safeguard** visibly trigger **`INCONCLUSIVE`**, while the Human Review Gate physically blocks claim denial (`FCA ICOBS 8`). | *"What happens when a judge uploads a short outdoor smartphone clip with no grid signal, or when evidence is weak? Right here, the best correlation is 0.438—below our code-enforced 0.540 null threshold. The deterministic safeguard fires on screen, blocking escalation and outputting a rigorous INCONCLUSIVE abstention. And even on a discrepancy, GhostClock cannot deny a claim or label anyone a fraudster—only a human investigator can hold payout and request raw media."* | **Risk Controls & Oversight (15–20%)**: Deterministic safeguard visibly triggers on screen; honest abstention; no automated claim denial; full JSON chain-of-custody log export. |
| **3:25 – 4:00** *(35 s)* | **5. Unseen Holdout Evaluation & Honest Failure Ledger** | Final evidence slide / summary table from W06–W10 held-out benchmark: show coverage, timestamp accuracy conditional on output, false contradiction rate, abstention rate, and explicit failure cases (modern DC LEDs, heavy voice-codec AGC, coarse 15s Elexon feed on short clips). | *"We tested GhostClock on unseen held-out audio and rolling-shutter video clips against open-source baselines. Where signals are clean, dating is accurate to seconds; where lighting is DC-driven or clips are too short for 15-second Elexon feeds, our null gate abstains rather than issuing a false alarm. That is why a financial institution can trust GhostClock near real money decisions."* | **Testing on Unseen Data (25%)**: Honest reporting of misses, abstentions, uncertainty, and baselines without inflated claims. |

---

## 2. Live Judge-Upload Challenge Flow (Interactive Protocol)

To maximize legitimate success while guaranteeing zero fake matches during the live Q&A or finalist pitch:

1. **Step 1 — Guided Capture Offer (Optional, Pre-Pitch):**
   - Invite a judge to record a **60–120 second stationary indoor video** pointed at a mains-lit wall/ceiling fixture (or near an AC appliance/adapter) inside the venue, or supply any existing recording together with an approximate 24–72 hour candidate window and grid zone (`GB 50 Hz`).
2. **Step 2 — Deterministic Intake & Blinding On Screen:**
   - Compute SHA-256 digest and run `ffprobe` (displaying container, codec, frame rate, VFR status, and audio sample rate).
   - Explicitly display the **Blinding Certificate**: strip `QuickTime:CreateDate`, `EXIF`, and filename timestamps; hold any judge-stated capture time outside the search module.
3. **Step 3 — Argon Screening & Adaptive Extraction:**
   - Argon inspects frame brightness distribution, motion masks, and audio spectrum, proposing up to 2 bounded extraction attempts (`analyse_audio` and/or `analyse_video`).
4. **Step 4 — Reference Selection & Resolution Check:**
   - For historical clips (>24h old where `NESO` 1-second data is available), run 1-second resolution matching.
   - For contemporary clips recorded minutes ago where only `Elexon` (~15-second cadence) is available, display the **Reference Cadence Warning**: clips shorter than ~120–180 seconds have low effective degrees of freedom against 15-second samples and will appropriately trigger `INCONCLUSIVE` unless a local 1-second reference monitor is active.
5. **Step 5 — Honest Verdict Reveal:**
   - Whether the upload produces `MATCH_SUPPORTED`, `MATERIAL_DISCREPANCY_REVIEW`, or `INCONCLUSIVE`, both prototypes render the full match landscape, null threshold, and *"what would change this"* counterfactuals—turning even an outdoor/battery clip into a live demonstration of our **Risk Control Safeguard**.

---

## 3. The Negative-Case Safeguard Moment (Rubric Criterion 3 Highlight)

The Finance rubric explicitly rewards strong risk controls where *"limits are enforced in the code, not just a prompt... the agent holds or asks a human when it's unsure, and one [control] triggers on the screen."*

Our negative-case safeguard (`Case 2: GC-2026-9104`, selectable via button `[2]` in both prototypes) demonstrates **two simultaneous code-enforced controls**:
1. **Statistical Abstention Gate (`SAFEGUARD_NULL_CALIBRATION_GATE`):**
   - On an 18-second VFR dashcam clip (`DASH_20261014_outdoor_clip.mp4`), Argon's second attempt extracts a noisy candidate trace (`median_q = 0.41`, `snr_db = 1.8 dB`).
   - Across the 72-hour search space, the maximum cross-correlation reaches `r = 0.438` with a second-best peak at `r = 0.411` (`margin_vs_second = 0.027`).
   - Deterministic verifier code compares `0.438 < 0.540` (`null.score_threshold`, empirical $p = 0.184 > 0.01$) and `0.027 < 0.15` (`min_uniqueness_margin`), **refuses to emit a timestamp**, and locks the status badge to **`INCONCLUSIVE`**.
2. **Regulatory Action Lock (`FCA ICOBS 8.1.1R` Gate):**
   - In the Human-in-the-Loop Decision Gate, the button *"Auto-Deny Claim / Allege Fraud"* is permanently disabled in code. The investigator can only *Clear Evidence*, *Hold & Request Original Media*, or *Escalate to SIU Review*, and must record a signed rationale before exporting the immutable JSON audit bundle.

---

## 4. Two Concrete Fallback Options (Zero-Failure Live Pitch Guarantee)

If live venue Wi-Fi, API latency, or reference feed endpoints degrade during the 4-minute pitch:

- **Fallback Option A — Pre-Validated Local JSON Replay in Static Console (`Zero-Latency Local Mode`):**
  - Both `work/W15/proto_A/index.html` and `work/W15/proto_B/index.html` are 100% self-contained zero-server HTML/JS bundles with zero external runtime dependencies. They work offline straight from disk (`file://`) and can also load any pre-computed `trace.json` + `match.json` from `work/W06`–`W13` via the local file picker in `< 50 ms`.
- **Fallback Option B — Pre-Rendered High-Resolution Walkthrough & Telemetry Deck Figures (`work/W15/plots/`):**
  - If display resolution or browser sandboxing prevents interactive switching during the 4-minute timer, use the 6 pre-rendered `1680x1050` headless browser screenshots (`proto_A_case1..3.png`, `proto_B_case1..3.png`) and the 4-panel composite telemetry figure (`fig_w15_forensic_telemetry_overview.png`) already saved in `work/W15/plots/`.

---

## 5. Figure & Numeric Provenance Ledger (Mandatory Epistemic Audit)

| Figure / Screen / Metric | File Path | Provenance Classification | Exact Description & What Is Claimed |
|---|---|---|---|
| **Prototype A — Case 1 (Discrepancy + Argon Loop)** | `work/W15/plots/proto_A_case1_discrepancy.png` | **`ILLUSTRATIVE / SYNTHETIC FIXTURE`** | Fictional £24,500 warehouse claim (`GC-2026-8841`) showing Argon Attempt 1 rejection (`frac_valid=0.31`) and Attempt 2 acceptance (`r=0.914`, `-48.01h` discrepancy) in the Case File Dossier UI. |
| **Prototype A — Case 2 (Safeguard Inconclusive)** | `work/W15/plots/proto_A_case2_inconclusive_safeguard.png` | **`ILLUSTRATIVE / SYNTHETIC FIXTURE`** | Fictional £8,200 dashcam claim (`GC-2026-9104`) showing the deterministic null gate (`0.438 < 0.540`, `p=0.184`) visibly firing to force `INCONCLUSIVE`. |
| **Prototype A — Case 3 (W13 Speed & Splice)** | `work/W15/plots/proto_A_case3_w13_speed_splice.png` | **`ILLUSTRATIVE / SYNTHETIC FIXTURE`** | Fictional £41,000 loading-bay claim (`GC-2026-9310`) showing W13 speed-alteration (`53.120 Hz`, `alpha=1.0624x`) and `142.4°` splice jump at `t=28.0s`. |
| **Prototype B — Case 1 (Signal Lab Discrepancy)** | `work/W15/plots/proto_B_case1_discrepancy.png` | **`ILLUSTRATIVE / SYNTHETIC FIXTURE`** | Multi-pane Signal Lab workbench view of Case 1 with rolling-shutter ROI viewport, trace overlay, and 72h match landscape. |
| **Prototype B — Case 2 (Signal Lab Safeguard)** | `work/W15/plots/proto_B_case2_inconclusive_safeguard.png` | **`ILLUSTRATIVE / SYNTHETIC FIXTURE`** | Multi-pane Signal Lab workbench view of Case 2 showing `SAFEGUARD_TRIGGERED` and sub-threshold correlation landscape. |
| **Prototype B — Case 3 (Signal Lab W13 Tampering)** | `work/W15/plots/proto_B_case3_w13_speed_splice.png` | **`ILLUSTRATIVE / SYNTHETIC FIXTURE`** | Multi-pane Signal Lab workbench view of Case 3 with W13 carrier offset and splice marker on trace plot. |
| **4-Panel Forensic Telemetry Overview** | `work/W15/plots/fig_w15_forensic_telemetry_overview.png` | **`ILLUSTRATIVE / SYNTHETIC FIXTURE`** | High-DPI publication composite comparing (A) Argon Attempt 1 vs Attempt 2 trace, (B) Case 1 match landscape, (C) Case 2 safeguard abstention landscape, and (D) Case 3 W13 speed/splice carrier shift. |
| **Interface Contract Verification Metrics** | `work/W15/RESULTS.json` | **`REAL-MEASURED (Programmatic Audit)`** | Verified `4/4` scenario fixtures against `integration/interfaces.md` v1 schema and `10/10` mandatory UI elements in both `proto_A` and `proto_B`, plus `6/6` headless browser renders. |
