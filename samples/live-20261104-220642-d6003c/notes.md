# live-20261104-220642-d6003c (BREAK1, real photo, the run in the demo video)

The live run recorded for the demo video on 2026-11-04, replayed here without API calls. Same part and
the same edited photo as live-20261103-224610-c8b8df (a cardboard plate, ruler 106.5 × 96.0 mm,
4 × Ø6 mm holes, one corner cut off, next to a transit card); the two photos are pixel-identical.

Photo edit before the runs: a QR code printed on the transit card was removed with a generative-erase
photo tool; nothing else was changed. The shipped JPEG carries no EXIF. Reviewed for personal data:
the card shows only transit branding and artwork, no name, number, chip or code.

Replays: 5 Muse Spark Open candidates (all rejected, reasons recorded), the Muse Wonder repair R1
(the winning result, with its diagnosis), break cues and the Muse Wonder completion suggestion. The
completion is undecided here (the video clicked Apply; that decision is not stored, so the card shows
as it first appeared). Ruler truth as in the older run (reports/real_parts.md).

`7_adapter_recorded/`: the matching-part steps of the same run. `voice.json` holds the spoken pattern's
transcript (Muse Voice Transcribe; read from the page, since the server does not save transcripts) and
the pattern Muse Spark Open parsed from it. `outline.json`, `outline.py` and `cand1-3` (programs and raw
responses) are the Muse Spark Open adapter outline search for that pattern (3 of 3 passed, winner 1).
Keyless replay serves this outline when the "2 × M5 · 60 mm" preset gives the same holes, thickness and
edge margin, labeled "Outline: Muse Spark Open · recorded".
