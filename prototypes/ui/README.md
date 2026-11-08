# Investigator UI prototypes: ILLUSTRATIVE

> **ILLUSTRATIVE.** These two static HTML/JS prototypes were built by Gemini worker W15. Their bundled cases are **synthetic fixtures** and every screen is badged as such. They show the intended non-chat workbench for an SIU investigator. They are **not** measurements and not a working product, and they have not been independently re-verified.

- [proto_A/index.html](proto_A/index.html): the "Case file and investigation dossier" layout.
- [proto_B/index.html](proto_B/index.html): the "Signal lab and multi-modal workbench" layout.

Both open directly in a browser over `file://` with no server; append `?case=0` to `?case=3`. A **Load JSON** button accepts real outputs in the frozen interface format ([docs/INTERFACES.md](../../docs/INTERFACES.md)).

Built into both: a blinding notice (the claimed time is hidden until after the search), a null-calibrated match landscape, audio and video confidences that are never multiplied together, and a fixed human-review gate. GhostClock cannot deny a claim or accuse a claimant.

The generator scripts, fixtures, screenshots and storyboard are in [w15_source/](w15_source/README.md). Example screenshot: [proto_A, inconclusive safeguard](w15_source/plots/proto_A_case2_inconclusive_safeguard.png).
