# Use case: insurance evidence corroboration

Curated from the worker-written use-case study ([full version](source/insurance_use_case.md), Gemini workers W16/W17; not independently re-verified). Every statement carries one of these labels:

- **[FACT]** — from a cited primary source. Grade C: sourced, not re-checked by the director unless noted.
- **[MEASURED]** — from this repository's own experiments, with a link.
- **[HYPOTHESIS]** — a product or workflow proposition that has not been tested with users.
- **[FICTIONAL]** — an illustrative scenario. No real person, company or claim.

## 1. Who the user is

- **[HYPOTHESIS]** The primary user is a UK insurance **Special Investigations Unit (SIU) investigator** or **complex commercial-property claims handler**. A secondary user is a commercial loss adjuster.
- Why this user, and not a trading desk or KYC: claims are investigated **weeks after** the event, by which point the NESO 1 s archive is published. The recordings are often indoor (plant rooms, warehouses, shops) near mains lighting and appliances. And the decision is a review before payment, not a real-time call. Each of these suits ENF's measured strengths ([EVIDENCE.md §3](EVIDENCE.md)).
- The director rejected the other framings (viral-video verification for trading, KYC liveness) on physics grounds: outdoor clips under 20 s, a same-day need, and only the 15 s reference available ([reviews/director_W17.md](../reviews/director_W17.md)).

## 2. The financial decision

- **[HYPOTHESIS]** A policyholder submits a phone or CCTV recording to support a mid-to-high-value claim. The investigator must decide whether to pay on the normal path or refer it for further investigation. The timing of the recording is often what decides cover, for example a loss filmed before policy inception.
- **[FACT, grade C]** The ABI reports £1.34bn of detected fraudulent general-insurance claims in 2025 across 93,900 claims, and £201m in property ([ABI press release, 6 Oct 2026](https://www.abi.org.uk/media-hub/news-post/fraudsters-target-bigger-payouts-as-insurers-detect-134-billion-of-bogus-claims), sourced by worker W16). There is **no published figure** for how many claims involve disputed recording timestamps, so we make no market-size claim for that subset.
- **[FACT, grade C]** Under FCA ICOBS 8.1.1R and Consumer Duty, an insurer must handle claims fairly and must not unreasonably reject them. Alleging fraud needs cogent evidence. **Product consequence:** GhostClock can only corroborate, abstain, or flag for human review. It never rejects or accuses ([RISK_CONTROLS.md](RISK_CONTROLS.md)).

## 3. The failure that would hurt the user most

A confident but wrong "this recording was made at a different time". It would push an investigator towards treating an honest claimant as a suspect. The measured controls for this are:

- **[MEASURED]** No-ENF recordings were never matched: 0/153 on the holdout ([C1](../experiments/c1_enfwhu_unseen_holdout/RESULTS.json)).
- **[MEASURED]** Calibrated statistics turn a spurious r = 0.76 into p ≈ 0.10, which gives `INCONCLUSIVE` ([W10](../experiments/w10_matcher_and_null_calibration/FINDINGS.md), grade B).
- **[MEASURED, weakness]** Real-ENF clips searched against the **wrong day** still produced a match in 28/270 = 10.4% of cases. The product therefore requires cross-day uniqueness and a human decision ([LIMITATIONS.md](LIMITATIONS.md)).

## 4. Fictional worked example (CLAIM-2026-88412)

> **[FICTIONAL] scenario, built on a REAL ENF-WHU holdout recording.** No real policyholder, company or personal data is involved. The audio and the 24 h grid reference are authentic ENF-WHU measurements (`H1/011`).

- A fictional bakery claims **£22,400** for a burst pipe at 20:30 on day D. The policy attached at 18:00 the same day. The supporting 5-min video was transcoded on upload, so its metadata shows only the upload time.
- GhostClock searches the full day blind. In the worker's scenario run, the claimed time scores r = −0.31, while one unique peak at 14:06:09 scores r = 0.9996. That disagrees with the claim by more than the 60 s tolerance, so the status is `MATERIAL_DISCREPANCY_REVIEW` and the case is **escalated to a human**. Automatic rejection is blocked in code.
- The output lists what would change the result: a documented device-clock offset, or the premises running on an isolated generator or UPS.
- **Cross-check [MEASURED]:** C1's frozen holdout trials on the same recording (three 5-min excerpts) give peak NCC 0.9996 and an absolute error of 0.20–0.21 s against ground truth ([trial table](../experiments/c1_enfwhu_unseen_holdout/trials/final_w16_q_clip05_holdout.parquet), rows `fid = 011, kind = h1_true, L = 300`). The scenario's specific excerpt, second-peak and timing values come from worker W16 and were **not** re-verified.

## 5. Investigator workflow (HYPOTHESIS)

1. Upload the original media. It is hashed on arrival.
2. GhostClock extracts audio and video ENF, picks the reference (NESO if published, otherwise Elexon), and searches blind.
3. The status and reasons are shown with the match landscape, the runner-up candidate and `what_would_change_this`.
4. The investigator decides: close the timing question, request more evidence (the original device file, a longer recording, the device clock), or refer the case. GhostClock's output is one input into that decision. It is never the decision.

Not yet validated with real investigators. A user study is future work.
