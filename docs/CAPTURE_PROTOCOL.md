# Capture protocol

How to record evidence-grade ENF test clips. There are two parts: the director's one-page quick protocol, used for the venue recordings on 08 Nov 2026, followed by the full field protocol written by worker W09 (Gemini; not independently re-verified).

> **Outcome note.** The 18.4-min venue video (1080p60, fast shutter, mains ceiling lights) was dated blind from the light flicker to **within 2 s of the camera clock** ([experiments/team_recordings_venue](../experiments/team_recordings_venue/README.md)). Speech in the room masked the audio hum, so the flicker channel carried the evidence. The 49 s test clip was correctly declined as too short. Length and a fast shutter under mains lighting are what make this work.

---

## Part 1: GhostClock: quick capture protocol (director, 08 Nov 10:45; W09 will extend this)

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


---

## Part 2: GhostClock UK Field-Capture Protocol (`capture_protocol.md`)

**Owner**: Worker `W09` (Visual ROI, Camera Physics & Field-Capture Lead)  
**Target Region & Grid**: Great Britain (GB National Grid, nominal $f_{\text{grid}} = 50.000\text{ Hz}$, optical modulation $f_{\text{light}} = 2 f_{\text{grid}} = 100.000\text{ Hz}$)  
**Operational Date**: Sunday 8 November 2026 (UCL AgentVerse 2026 Final Build Day)  
**Cross-Worker Empirical Inputs**: `W01` (`work/W01/FINDINGS.md`), `W02` (`agents/status/W02.json`), `W11` (`work/W11/README.md`, `agents/status/W11.json`), `C4` (`work/C4/README.md`)

---

### 1. Executive Checklist (Read Before Pressing Record)

If you are filming a real UK test clip **today (Sunday 8 Nov 2026)** for the GhostClock live demo or blind benchmark, **every item in this box is binding**:

1. **Grid Reference Constraint Today (`W02` / `W11` Verified)**:
   - NESO 1-second historical CSVs have a **38.4-day publication latency** (`W02`: latest published file is September 2026, `fnew-2026-9.parquet`).
   - Therefore, any clip recorded **today (8 Nov 2026)** is matched against the **Elexon BMRS near-real-time feed** (`https://bmrs.elexon.co.uk/api-documentation/endpoint/system/frequency`), which has a **15-second cadence** and **57–142 s live latency**, unless paired with a local plug-in AC reference divider (`W12`).
2. **Minimum Recording Duration (`W01` / `W11` Verified)**:
   - Record for **$8\text{–}10\text{ minutes}$ ($\ge 480\text{–}600\text{ s}$) continuously**.
   - *Why*: `W01` (`work/W01/FINDINGS.md` §2.2) proved on authentic 24-hour grid data that at Elexon's $15\text{ s}$ cadence, Top-1 accuracy is **$0.0\%$ at $30\text{–}60\text{ s}$**, **$10.0\%$ at $120\text{ s}$**, **$95.0\%$ at $300\text{ s}$ ($5\text{ min}$)**, and **$100.0\%$ at $600\text{ s}$ ($10\text{ min}$)** with $0.0$ false shifts $\ge 0.90$.
3. **Optimal Recording Clock Window (`W11` Verified)**:
   - Start filming **5 minutes before the top or bottom of the hour** (e.g., `10:55–11:05 UTC` or `11:25–11:35 UTC`) so the recording straddles an **Elexon 30-minute electricity trading settlement boundary (`:00` or `:30`)**.
   - *Why*: `W11` (`agents/status/W11.json`) proved across $5.27 \times 10^6$ seconds of GB NESO data that generator dispatch ramps at `:00` and `:30` settlement boundaries increase grid frequency standard deviation by **$+44.61\%$ ($p = 5.41 \times 10^{-165}$)**, maximizing sequence uniqueness.
4. **Camera Settings (Defeat Smartphone Anti-Banding)**:
   - Use **Manual / Pro Video Mode** (Blackmagic Camera app on iPhone; Pro Video on Samsung; Manual app on Pixel).
   - Lock **Shutter Speed** to **$1/2000\text{ s}$ ($0.5\text{ ms}$)** (acceptable range: **$1/1000\text{ s}$ to $1/4000\text{ s}$**). **NEVER use Auto Exposure**, which locks shutter to $1/100\text{ s}$ ($10.0\text{ ms}$) in the UK and places an exact $\operatorname{sinc}(100 \times 0.01) = 0$ spectral zero on the $100\text{ Hz}$ flicker.
   - Lock **Frame Rate** to **$30.0\text{ fps}$ CFR** (or **$60.0\text{ fps}$ CFR**). Avoid UK default $25\text{ fps}$ / $50\text{ fps}$ PAL unless specifically testing pure rolling-shutter spatial extraction, because $100\text{ Hz} \bmod 25\text{ fps} = 0\text{ Hz}$ (DC collapse for frame-mean brightness).
   - Lock **ISO** ($100\text{–}400$) and **White Balance** ($4000\text{ K}$).

---

### 2. Camera Physics & Device Configuration (iPhone, Pixel, Samsung)

#### 2.1 Why Default Auto-Video Mode Fails in the UK
Under a $50\text{ Hz}$ AC grid, resistive and unsmoothed rectified lamps modulate optical intensity at twice the mains frequency:
$$I(t) = I_0 \left[ 1 + m \cos\left(2\pi (2 f_{\text{grid}}) t + \phi\right) \right], \quad f_{\text{light}} = 2 f_{\text{grid}} \approx 100\text{ Hz}$$
When a CMOS sensor integrates light over an exposure duration $T_{\text{exp}}$, the effective modulation amplitude is multiplied by the rectangular integration transfer function:
$$H(f_{\text{light}}, T_{\text{exp}}) = \operatorname{sinc}(f_{\text{light}} T_{\text{exp}}) = \frac{\sin(\pi f_{\text{light}} T_{\text{exp}})}{\pi f_{\text{light}} T_{\text{exp}}}$$
Modern smartphones (Apple iPhone, Google Pixel, Samsung Galaxy) use a dedicated ambient flicker sensor or ISP auto-exposure (AE) anti-banding table (`CONTROL_AE_ANTIBANDING_MODE_50HZ` / `AUTO` in Android Camera2) that forces $T_{\text{exp}} = k / 100\text{ s}$ ($10.0\text{ ms}, 20.0\text{ ms}, \dots$) whenever $50\text{ Hz}$ mains flicker is detected. At $T_{\text{exp}} = 10.0\text{ ms}$ ($1/100\text{ s}$), $\sin(\pi \cdot 100 \cdot 0.01) = \sin(\pi) = 0$, attenuating the $100\text{ Hz}$ optical ENF signal by **$-\infty\text{ dB}$** (`C4` measured median quality dropping from $45.5\text{ dB}$ to $3.9\text{ dB}$ when $T_{\text{exp}} = 10\text{ ms}$).

| Exposure Shutter $T_{\text{exp}}$ | Duration (ms) | $|\operatorname{sinc}(100\text{ Hz} \cdot T_{\text{exp}})|$ | Gain Loss (dB) | Verdict for 50 Hz UK Capture |
| :--- | :---: | :---: | :---: | :--- |
| **$1/4000\text{ s}$** | $0.25\text{ ms}$ | $0.9990$ | $-0.01\text{ dB}$ | **Ideal** (requires bright lamp/wall to avoid underexposure) |
| **$1/2000\text{ s}$** | $0.50\text{ ms}$ | $0.9959$ | $-0.04\text{ dB}$ | **Recommended Default** (strong banding, low motion blur) |
| **$1/1000\text{ s}$** | $1.00\text{ ms}$ | $0.9836$ | $-0.14\text{ dB}$ | **Recommended Indoor** (excellent SNR at moderate ISO 200–400) |
| **$1/500\text{ s}$** | $2.00\text{ ms}$ | $0.9355$ | $-0.58\text{ dB}$ | **Good** (suitable for dimmer indoor rooms) |
| **$1/250\text{ s}$** | $4.00\text{ ms}$ | $0.7568$ | $-2.42\text{ dB}$ | **Acceptable Minimum** (do not go slower than $1/250\text{ s}$) |
| **$1/120\text{ s}$** (US Auto) | $8.33\text{ ms}$ | $0.1913$ | $-14.36\text{ dB}$ | **Poor** (severe attenuation at $100\text{ Hz}$; null at $120\text{ Hz}$) |
| **$1/100\text{ s}$** (UK Auto) | $10.00\text{ ms}$ | **$0.0000$** | **$-\infty\text{ dB}$** | **FATAL NULL** (default UK smartphone anti-banding lock) |
| **$1/50\text{ s}$** (UK Auto) | $20.00\text{ ms}$ | **$0.0000$** | **$-\infty\text{ dB}$** | **FATAL NULL** (second harmonic anti-banding lock) |

#### 2.2 Step-by-Step Device Setup

##### A. iPhone (iPhone 12 / 13 / 14 / 15 / 16 Pro or standard)
Apple's stock Camera app does **not** allow manual shutter speed locking and aggressively enables Variable Frame Rate (VFR) and $1/100\text{ s}$ anti-banding.
1. Install the free **Blackmagic Camera** app (or Final Cut Camera / Halide / ProMovie) from the iOS App Store.
2. Open **Settings $\to$ Camera** inside Blackmagic Camera:
   - **Codec**: `H.264` or `Apple ProRes 422` (if storage permits; otherwise `H.264` High Bitrate $\ge 20\text{ Mbps}$).
   - **Frame Rate**: **`30.00 fps`** (or **`60.00 fps`**). Ensure "Auto Frame Rate" / VFR is **OFF**.
   - **Resolution**: **`1080p` (`1920x1080`)** or **`720p` (`1280x720`)**. (Avoid 4K if storage/upload speed is constrained; $1080\text{p}$ has full vertical row readout).
3. On the main viewfinder HUD:
   - Tap **Shutter** $\to$ set to **`1/2000`** (or **`1/1000`**) and tap the **Lock** icon (`AVCaptureExposureModeCustom`).
   - Tap **ISO** $\to$ adjust between **`160` and `400`** so the wall is mid-bright (histogram centered at $40\text{–}75\%$, zero highlight clipping) and tap **Lock**.
   - Tap **WB** (White Balance) $\to$ set to **`4000K`** and tap **Lock**.
   - Tap the wall region on screen to lock **Manual Focus (MF)**.

##### B. Samsung Galaxy (S22 / S23 / S24 / S25)
1. Open the stock **Camera** app $\to$ swipe to **More** $\to$ select **Pro Video**.
2. Top bar: set resolution to **`FHD 30`** (`1920x1080 @ 30.0 fps`). In Camera Settings, turn **Auto FPS = OFF** and **Video Stabilization = OFF** (electronic stabilization warps rolling-shutter row geometry!).
3. Bottom controls:
   - Tap **SPEED (Shutter)** $\to$ dial to **`1/2000`** or **`1/1000`**. (In Android Camera2, setting manual `SENSOR_EXPOSURE_TIME` automatically overrides `CONTROL_AE_ANTIBANDING_MODE`).
   - Tap **ISO** $\to$ set manually to **`200`–`400`**.
   - Tap **WB** $\to$ lock at **`4000K`**.

##### C. Google Pixel (Pixel 7 / 8 / 9 Pro)
1. On Pixel 8 Pro / 9 Pro: open Camera $\to$ **Video** $\to$ **Pro Controls** (or use **Blackmagic Camera for Android** / **Open Camera** with Camera2 API enabled).
2. Set Frame Rate to **`30 fps`**, Video Stabilization **OFF**, Shutter Speed **`1/1000 s`–`1/2000 s`**, ISO **Locked (`200`–`400`)**.

---

### 3. Lighting Selection & The 5-Second Pre-Capture Flicker Test

#### 3.1 Which Lamps Carry 100 Hz ENF vs. Which Lamps Fail (IEEE Std 1789-2015)

| Lamp / Luminaire Type | Driver Topology | Typical $100\text{ Hz}$ Modulation Depth (%) | Optical ENF Usability | Field Identification Tip |
| :--- | :--- | :---: | :---: | :--- |
| **Mains Halogen / Incandescent Bulb** | Direct $230\text{ V}$ AC resistive filament | $10\% \text{ – } 25\%$ | **EXCELLENT (Gold Standard)** | Warm glass bulb, oven lamp, desk halogen, or security floodlight. Thermal inertia smooths higher harmonics, leaving a pure $100\text{ Hz}$ sinusoid. |
| **Magnetic-Ballast Fluorescent Tube** | Inductive choke + AC discharge | $25\% \text{ – } 45\%$ | **EXCELLENT** | Older office/corridor/garage strip lights (often emit audible $50/100\text{ Hz}$ buzz). |
| **Inexpensive AC Filament / Capacitor-Dropper LED** | Full-wave bridge rectifier + small/no electrolytic smoothing capacitor | $30\% \text{ – } 100\%$ | **EXCELLENT** | Clear-glass "vintage Edison filament" mains LED bulbs or budget utility LEDs without heavy base drivers. |
| **High-Frequency Electronic-Ballast Fluorescent** | Rectified DC $\to$ $25\text{–}50\text{ kHz}$ resonant inverter | $< 3\%$ at $100\text{ Hz}$ | **WEAK / UNRELIABLE** | Modern silent office troffers; residual $100\text{ Hz}$ envelope depends on bulk capacitor ripple. |
| **Premium Constant-Current SMPS LED** | Two-stage PFC + active DC current regulator | $< 1\%$ | **NONE (Negative Control)** | Expensive "Flicker-Free" studio/architectural LEDs, Apple/BenQ monitors. |
| **USB / Battery / DC Desk Lamp** | $5\text{ V}$ DC or PWM ($>500\text{ Hz}$) | $0.0\%$ | **NONE (Negative Control)** | Any rechargeable or laptop-powered light has zero grid connection. |

#### 3.2 The 5-Second Pre-Capture Verification Trick
Before filming a 10-minute clip, **verify that your lamp actually flickers at 100 Hz**:
1. Point your phone at the illuminated wall with shutter set to **$1/2000\text{ s}$** (or switch briefly to **240 fps Slow-Mo** mode).
2. Look at the live viewfinder screen:
   - **If you see slow horizontal dark/bright bars scrolling up or down the wall** (or a $20\text{ Hz}$ shimmer in $240\text{ fps}$ mode), the lamp has strong $100\text{ Hz}$ AC modulation — **PROCEED**.
   - **If the wall looks completely solid and uniform at $1/2000\text{ s}$**, the lamp has a smoothed DC driver — **SWITCH LAMPS** (use a mains halogen desk lamp, oven/appliance bulb, or cheap filament LED).

---

### 4. Scene Composition & Audio-Hum Co-Capture

#### 4.1 Visual Scene Framing (Maximizing `W09` ROI Usability Score)
1. **Mount the phone on a tripod, shelf, or heavy book stack**. Do **not** hold the phone by hand (`W09` penalizes frame-to-frame motion residual $\sigma_{\text{motion}}$ exponentially via $\exp(-\sigma_{\text{motion}}/3.0)$).
2. **Orientation**: Landscape (`1920x1080`), so the CMOS rolling-shutter readout scans vertically across the $H = 1080$ rows ($T_{\text{ro}} \approx 14\text{–}28\text{ ms}$, capturing $1.4\text{–}2.8$ full cycles of $100\text{ Hz}$ flicker per frame).
3. **Wall / Ceiling Target**: Frame the scene so **at least 60% of the image** covers a matte, plain, light-colored wall or ceiling $0.5\text{–}2.0\text{ m}$ from the AC lamp.
4. **Avoid**:
   - **Direct view of the bare bulb** or specular reflections (`mean_luma >= 250` clips the ADC to $255$, zeroing out AC modulation).
   - **Daylight windows** in the same frame (sunlight is DC and dilutes the AC modulation depth $m$, or saturates tiles). Close curtains/blinds if filming during daytime.

#### 4.2 Safe Audio-Hum Co-Capture (Zero Wiring Modification)
To allow multimodal corroboration (`W06`/`W07` audio + `W08`/`C4` video) — while respecting Scientific Rule #3 that audio and video sense the **same** environment and must never have their confidences multiplied — include a clean acoustic mains hum source in the room:
1. **Safe Sources (No Electrical Modification)**:
   - A domestic **refrigerator or freezer** during its active compressor cycle.
   - An **AC mains-powered desk fan** or extractor fan.
   - An external **ferromagnetic AC wall-wart transformer** (e.g., guitar pedal power supply, older halogen desk lamp base, or doorbell/intercom transformer) resting on a wooden desk or hollow box (which acts as an acoustic sounding board for $100\text{ Hz}$ magnetostriction hum).
2. **Microphone Placement & Harmonic Physics (`W01` Verified)**:
   - Place the recording phone **$0.3\text{–}0.8\text{ m}$** from the hum source.
   - `W01` (`work/W01/FINDINGS.md` §1.1) proved that smartphone hardware high-pass filters cut off frequencies below $80\text{–}95\text{ Hz}$, making the $50\text{ Hz}$ fundamental unusable ($r = 0.0215$). However, magnetostriction and rectifier acoustics are rich in **$100\text{ Hz}$ (2nd harmonic)** and **$150\text{–}350\text{ Hz}$ (3rd–7th harmonics)**, where `W01`/`W07`'s GHSA clique estimator achieves $r = 0.9340$.
   - Ensure iOS **"Voice Isolation"** / Android **"Clear Calling" / Audio Zoom** is **OFF**; record standard stereo/mono PCM or high-bitrate AAC (`48 kHz`). Keep the room quiet (avoid talking over the middle of the clip).

---

### 5. Independent Ground-Truth Clock & Blinding Procedure

To satisfy the Finance Track's **Traceable Reasoning (25%)** and **Testing on Unseen Data (25%)** rubrics without metadata leakage (Scientific Rule #8):

#### 5.1 Head-and-Tail Optical UTC Slate (`time.is`)
Internal phone system clocks and MP4 `creation_time` tags can drift by $1\text{–}30\text{ s}$, and crystal oscillators drift by $10\text{–}100\text{ ppm}$ (`C4` measured $+87\text{ ppm}$ timebase bias on Zenodo `MOV2`). We establish independent sub-second UTC ground truth **and** crystal drift calibration using a second device:
1. On a **second phone or laptop** ("Clock Device"), open **`https://time.is/UTC`** (or an NTP/GPS clock app displaying UTC `HH:MM:SS.d` and sync offset $< \pm 20\text{ ms}$).
2. **Start Recording (`t = 0 s`)** on the primary camera phone.
3. **Head Slate (`t = 2 s` to `t = 12 s`)**: Hold the Clock Device in front of the lens for 10 seconds so the exact UTC timestamp is clearly visible in the video frames.
4. **Main Blinded Capture (`t = 15 s` to `t = 615 s`)**: Remove the Clock Device completely from the scene. Leave the camera untouched on its tripod filming the static AC-lit wall for **10 full minutes ($600\text{ s}$)**.
5. **Tail Slate (`t = 618 s` to `t = 628 s`)**: Hold the Clock Device in front of the lens again for the final 10 seconds before stopping the recording.
   - *Why both Head and Tail slates*: Comparing the optical UTC elapsed time $\Delta t_{\text{UTC}}$ between frame $n_{\text{head}}$ and frame $n_{\text{tail}}$ against the container PTS elapsed time $\Delta t_{\text{PTS}}$ measures the exact camera clock drift $\epsilon_{\text{ppm}} = 10^6 (\Delta t_{\text{PTS}} - \Delta t_{\text{UTC}}) / \Delta t_{\text{UTC}}$ independently of the grid!

#### 5.2 Deterministic Cropping, Metadata Stripping & Double-Blind Custody
The **Red-Team Custodian** (a teammate who does **not** run the GhostClock analysis) performs these steps before handing files to the Blue-Team Investigator:

1. **Hash the Immutable Original**:
   ```powershell
   Get-FileHash -Algorithm SHA256 raw_master_capture.mp4
   ```
   Record `raw_sha256`, the visually read `true_analysis_start_utc` (the exact UTC second corresponding to `t = 15.000 s`), device model, shutter speed, and lighting type in a private sealed file `custodian_ground_truth_sealed.json` stored **outside** the agent's workspace.
2. **Trim Slates & Strip All Container/EXIF Metadata**:
   Run `ffmpeg` to cut only the clean 600-second interior window (`00:00:15` to `00:10:15`), strip all metadata tags (`-map_metadata -1`), and assign an opaque blinded filename (`GC_BLIND_01.mp4`):
   ```powershell
   ffmpeg -ss 00:00:15 -to 00:10:15 -i raw_master_capture.mp4 -map_metadata -1 -c:v libx264 -crf 18 -preset fast -c:a aac -b:a 192k GC_BLIND_01.mp4
   Get-FileHash -Algorithm SHA256 GC_BLIND_01.mp4
   ```
   *(Note: If zero re-encoding is desired and keyframe alignment permits, use `-c copy`; if re-encoding, use `-crf 18` and `-vsync cfr` so rolling-shutter bands are preserved without VFR jitter).*
3. **Hand Off Only the Blinded File**:
   The investigator agent (`W18`) receives only `GC_BLIND_01.mp4` and a broad candidate search window (e.g., a 24-hour or 48-hour window), with zero access to `raw_master_capture.mp4` or `custodian_ground_truth_sealed.json`.

---

### 6. Mandatory Negative Controls (Record Today Alongside Positives)

To prove our risk controls trigger honestly (`INCONCLUSIVE` abstention on uninformative media rather than hallucinating a timestamp), film these three **2-minute negative control clips** using the exact same blinding procedure:

| Control ID | Condition | Camera & Scene Setup | Expected `W09` (`roi_screen.py`) & `W18` Agent Outcome |
| :--- | :--- | :--- | :--- |
| **`GC_NEG_01_DAYLIGHT`** | **Outdoor Daylight + Airplane Mode** | Film an outdoor brick wall or courtyard under natural daylight, away from buildings/transformers, with phone in **Airplane Mode**, $30\text{ fps}$, shutter $1/2000\text{ s}$. | `overall_usable = False` (`alias_pnr_db < 3 dB`, `rs_band_snr_db < 2 dB`); Agent issues **`INCONCLUSIVE`** (`no_enf_detected`). |
| **`GC_NEG_02_DC_LED`** | **Indoor Battery / Constant-Current DC LED** | In a dark room with curtains closed and room mains lights OFF, illuminate the wall using only a **battery-powered LED torch or laptop screen**; film at $30\text{ fps}$, shutter $1/1000\text{ s}$. | `overall_usable = False`; proves GhostClock does not mistake bright indoor static walls for AC grid flicker. |
| **`GC_NEG_03_ANTIBANDING`** | **UK Auto-Exposure Sinc Null ($1/100\text{ s}$)** | Under the **exact same positive AC halogen/fluorescent lamp**, lock shutter speed to **$1/100\text{ s}$ ($10.0\text{ ms}$)** (or use default stock Camera app Auto mode). | `overall_usable = False`; demonstrates on-screen to judges why smartphone anti-banding kills ENF and why GhostClock's physics screener catches it before matching. |
