# Director review: W17 (pitch framing / rubric / Q&A), 2026-11-08 ~10:00
Status claimed DONE. Deliverables exist with real content (rubric matrix 30 KB, deck+script 29 KB, 28-question hostile Q&A 42 KB).

**Accept (useful):**
- Recommended framing: primary = insurance SIU / complex-claims investigator; supporting = commercial loss adjuster. The reasoning is sound: claims are investigated after the event, indoor plant/warehouse recordings, a review-before-payment decision, and immune to the "alpha paradox".
- The physics argument against the trading-desk viral-video and KYC-liveness framings (outdoor, <20 s clips, same-day need, 15 s reference) is correct and worth having in the Q&A bank.
- Both rubric weightings are handled.

**Reject / downgrade before anything reaches the deck:**
1. The "Monte Carlo framing tournament" scores (92.36, 94.7% P(rank 1), etc.) are perturbations of **subjective hand-assigned weights**. They are NOT measurements. Grade **D**. Never show those numbers to judges as quantitative evidence; it is exactly the "inflated number" the organisers warn against.
2. Several figures are unverified or circular: ABI £1.34bn / £201m is marked "SOURCE-VERIFIED" but cites the ChatGPT log, not abi.org.uk (W16 must verify at source); the "£2,000–5,000 per forensic lab case" and "~£0.08/clip" are unmeasured; "W14 guards G1–G6" and Gemini `processing="agentic"` are referenced before they exist or are verified.
3. Missing nuance that undercuts the "days/weeks later → NESO 1 s available" argument: NESO's 1 s archive is published with ~38 days' latency (W02 measured). Claims investigated within ~5 weeks have only Elexon 15 s data, so the 15 s feasibility result (C2/W11) matters for the PRIMARY use case, not just the live demo.
Action: the final deck is built from measured results only; W17's script/Q&A are a draft to be re-anchored on the measured numbers.
