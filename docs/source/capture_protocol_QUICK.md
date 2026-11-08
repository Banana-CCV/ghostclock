# GhostClock: quick capture protocol (director, 08 Nov 10:45; W09 will extend this)

**Why these rules:** C2 measured that dating a clip **against today's public Elexon 15 s feed** needs **≥10 min** of usable ENF, and **20 min** is safer (P(correct within ±15 s) ≈ 0.95 at 10 min vs 0.99 at 20 min, semi-synthetic, n=1000). Shorter clips can only be dated against 1 s data (NESO, published ~6 weeks later) or our own live reference station (W12, in progress).

## Clip A: "the hero recording" (the most important one)
1. **Place:** indoors, away from windows/daylight. Ideally a room with **old-style mains lighting** (halogen, incandescent, fluorescent tubes; cheap LED bulbs sometimes flicker too) **and** a humming mains appliance nearby (fridge, desk fan, extractor, old transformer, aquarium pump). Do NOT open or modify any electrical device.
2. **Check flicker first:** point a phone camera at the lamp. Visible rolling dark bands on screen (or in slow-motion mode) mean the light flickers, which is good. No bands means the audio hum is the main signal.
3. **Phone:** on a stand/tripod, **completely still**, filming a plain lit wall/ceiling region plus the lamp. Use **30 fps or 60 fps (NOT 25 fps)**: at 25 fps the 100 Hz flicker aliases to 0 Hz and is unrecoverable. If there's a "Pro" mode, lock exposure and set a fast shutter (1/500–1/2000 s) to defeat anti-flicker.
4. **Duration: 20 minutes** (minimum 10). Keep talking to a minimum; silence near the hum source is best.
5. **Ground truth, kept OUT of the analysis:** at the very start and the very end, briefly show a second phone displaying **https://time.is** (NTP-synced, with seconds) to the camera. A teammate writes down the start/end times. We crop these seconds out of the analysis copy so the agent never sees them.
6. **Keep the original file** untouched (AirDrop/USB, not WhatsApp, which recompresses). We'll hash it (SHA-256) on arrival.

## Clip B: negative control (makes the honest-abstention demo real)
- 5–10 min **outdoors in daylight** or in a room lit only by daylight / a DC LED panel, with no appliances. Expected result: **INCONCLUSIVE / NO_GRID_SIGNAL**.

## Clip C (optional): short clip for the speed-tamper demo
- 30–60 s indoors near the hum source. We will speed it up ×1.75 ourselves (labelled as a staged manipulation) to show the no-reference speed check (C3/W13).

## Blinding
- Name the files with opaque IDs (e.g. `case_A.mp4`) and keep the true times in a separate note held by one teammate. Don't put dates in filenames.
- Copy originals into `<WORKSPACE>\datasets\raw\team_recordings\` (any folder is fine; tell the director where).
