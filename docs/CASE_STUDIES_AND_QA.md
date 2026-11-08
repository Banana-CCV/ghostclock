# GhostClock: case studies (last slide) + finance Q&A prep
*Compiled 8 Nov 2026 from four research tracks (full tables and sources: [docs/research/](research/): insurance_cases.md, court_enf_cases.md, markets_cases.md, deepfake_cases.md). ✅ = source opened and key facts checked against it. ⚠️ = secondary or search-only: say "reported".*

---

## A. LAST-SLIDE OPTIONS (pick 3)

### 1. "The CCTV clock was wrong", a theft claim lost on timing ✅ DIRECT
**Financial Ombudsman Service, DRN-4534311 (Mrs M v One Insurance, 23 Feb 2024).** The policy required the car to be garaged from **10 pm to 6 am**. The claimant first said the theft happened at 3 am, then said her **CCTV clock was incorrect** and the theft was before 10 pm. Nobody could prove the real time, so the decline stood. *An independent clock in the footage itself, the grid, is exactly what was missing.*
→ https://financial-ombudsman.org.uk/decision/DRN-4534311.pdf

### 2. "Eleven seconds", a claim decided by the length of a clip ✅ DIRECT
**FOS DRN-4256057 (Mr A v Wakam, 20 Jul 2023).** Doorbell footage showed the car driven away **"a matter of eleven seconds"** after the thief reached it. The insurer said that was implausible for a locked car and declined; an expert disagreed; the ombudsman **upheld the complaint** and Wakam had to reconsider. *When money turns on seconds of consumer footage, both sides need proof the clip is continuous and real-speed.*
→ https://www.financial-ombudsman.org.uk/decision/DRN-4256057.pdf

### 3. "Courts already trust the grid" ✅ (UK ENF precedent)
**Met Police ENF analysis was "pivotal" in a 2010 UK murder conviction:** it proved a seized voice recording authentic after the defence claimed it was concocted. The Met's Penge lab had logged grid frequency for five years (The Register, 1 Jun 2010 ✅). Also reported: a 2012 Croydon gun-supply trial, where ENF rebutted a claim that an undercover recording was spliced; 3 convicted, 33 years ⚠️. *The science is accepted; it has never been productised for the claims desk.*
→ https://www.theregister.com/2010/06/01/enf_met_police/

### 4. "Metadata isn't evidence" (supporting) ✅ / ⚠️
- **FOS DRN-3332271 (UKI, 24 Feb 2022):** a fraud finding based only on photo date/time metadata was **overturned**; fraud markers removed, £300 compensation ✅.
- **AFCA v Youi (Australia, reported Feb 2026):** cover bought about **10 minutes after the crash**; photo metadata had been altered ⚠️.
*Our venue test never read metadata and still recovered the start time within 2 s.*

**Context numbers for the slide footer** (say "reported"):
- **ABI:** £1.34bn of detected UK insurance fraud in 2025, 93,900 cases, average £14,300 (via Insurance Business, 6 Oct 2026 ⚠️).
- **Verisk survey (Mar 2026):** 99% of insurers have encountered manipulated or AI-altered documentation; only 58% are very confident detecting edits to real photos or videos ⚠️.
- **Aviva:** £233m of suspect claims in 2025, with a growing number of AI-generated images ⚠️.

**Suggested slide headline:** *"Claims are already being won and lost on seconds of footage nobody can verify."* Three tiles: **10 pm** (the clock was wrong) · **11 seconds** (decided by a clip) · **2010** (courts already trust the grid). Footer: the ABI fraud figure.

---

## B. FINANCE Q&A: likely hard questions and honest answers

**1. "Who pays, and why?"**
Insurer SIU teams and commercial loss adjusters, per case. The decision it improves is **"refer this evidence for specialist review before paying, or not"**. It costs a fraction of a manual expert engagement, and it triages which recordings deserve one. The costs we measured: **5 real Argon investigations used 129,993 tokens (~26k per case) and 40–165 s per model call**; the signal processing runs locally in seconds to minutes.

**2. "How big is the problem?"**
UK detected insurance fraud was £1.34bn in 2025 (ABI, reported), with an average detected case of £14,300. Insurers themselves say manipulated media is rising: 99% have encountered it, and only 58% are confident detecting edited photos or videos (Verisk, reported). We **don't** claim a £ figure GhostClock would save; that needs real claims outcomes we don't have. We show the decision and our measured error rates.

**3. "What's the cost of being wrong? Do you deny claims?"**
Never. The worst a case can get is `MATERIAL_DISCREPANCY_REVIEW`, a referral to a human. That matters financially: FOS overturned a fraud finding built on metadata (DRN-3332271, compensation plus markers removed), and FCA ICOBS 8 forbids unreasonably rejecting claims. A false accusation costs money, reputation and regulator attention, so we built the gates to abstain first.

**4. "Why not just use the file's timestamp or metadata?"**
Metadata is editable: FOS said exactly that when it overturned UKI's fraud finding, and the Youi case involved altered metadata. Our venue test never read metadata and still found the start time to within 2 s of the camera clock, from the lights alone, across 36 h of grid history.

**5. "If this works, why aren't insurers already doing it?"**
The science exists: the Met Police has used ENF in court since about 2010. It has stayed a bespoke forensic-lab service. The hard parts are knowing *whether* a clip carries usable signal, extracting it, getting clean reference data (we found and fixed timezone-shifted months and flat-filled outages in the national archive), and calibrating so you don't accuse innocent people. GhostClock automates the triage and the calibration, and keeps a human in the decision.

**6. "What's your false-positive rate?" (the quant question)**
On unseen data (45 recordings, 15 days, frozen settings, run once), 5-minute clips: answered 78%, **every answer correct to ±5 s (105/105)**, and no-ENF clips falsely matched **0/153**. The known weakness, stated plainly: against the **wrong day's** reference it still issued a match **10.4%** of the time (28/270). That's why the product requires uniqueness across all candidate days and a human sign-off. Naive statistics would have called a wrong-day match p ≈ 10⁻⁵⁸; our calibrated null says p ≈ 0.10, so the result is INCONCLUSIVE.

**7. "Multiple comparisons: you searched 36 hours, of course you found a peak."**
Yes, which is why we compare against the best score **anywhere** in 36 h (0.826) and on 7 wrong days (≤ 0.847), not just the zero line. The match scored 0.979. The p-value is floored at 1/8 by having only 7 null days, so we argue from the margin, and say so.

**8. "Can a fraudster fake the hum?"**
In principle, yes: ENF injection is a known anti-forensic attack. It's corroboration, not proof. Faking it convincingly means forging the right grid trace for the right time, consistently across hum and light, which raises the cost of fraud considerably. A red-team study is started, not finished.

**9. "What if there's no hum or no lights?"**
GhostClock abstains and says what evidence would help (e.g. a longer or indoor recording). On our 49 s venue clip it correctly refused to date it. Outdoor-only or very short clips are out of scope, and we say so.

**10. "What about deepfakes, like the $25m Arup case?"**
Honest answer: GhostClock wouldn't have stopped Arup. It was a **live** video call, and call audio strips the mains hum. Our scope is **stored recordings submitted as evidence**: claim footage, dashcam, CCTV, doorbell. A replayed or synthetic clip usually carries no ENF, or the wrong date's ENF, so we flag it rather than certify it.

**11. "Is this a trading signal? Markets react to fake media."** (the alpha paradox)
No. Markets do react to fake or stale media within seconds: the fake AP tweet erased about $136.5bn of S&P value (2013), and UAL fell more than 75% intraday on a six-year-old story (2008). But those were text, and ENF only applies to recordings with a mains signal. We're a verification utility; one insurer using it doesn't make it less useful to the next, so there's no alpha to decay.

**12. "Same-day verification? Live use?"**
Against the live public grid feed (15 s cadence, about 1–2 min behind real time), a clip needs **at least 10–20 minutes** (P(correct) 0.95 at 10 min, 0.99 at 20 min; independently reproduced). The 1 s national archive arrives about 5–6 weeks later, which suits insurance, where claims are investigated weeks after the event.

**13. "What does Gemini actually add, if the maths decides?"**
Argon directs the investigation (which sensor, which harmonics, which window) and writes the human-readable explanation, with every number checked against tool outputs. The code gate sets the status; in our case e it **overrode** Argon to flag a false claimed time. Honest ablation: on 5 cases a fixed pipeline reached the same statuses. Argon's value is auditable investigation and explanation at claims-desk scale, not higher accuracy.

**Avoid saying** (debunked during research):
- "$500bn Pentagon-image crash": the real dip was about 0.3% and recovered in roughly 10 minutes.
- "Reuters was fined for a 2-second early release": it was a 2013 agreement to stop, with no penalty found.
- "A deepfake CEO video crashed a stock": none is documented.
- "Appeal courts approved ENF": only trial-level use is documented.
