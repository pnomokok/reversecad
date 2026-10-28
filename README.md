# ReverseCAD

ReverseCAD turns one top-down photo of a flat part into an **editable CAD program with real millimeter dimensions**. Put the part next to a bank card, click the part, and get CadQuery code whose parameters (length, hole diameter, edge margin, tab width, ...) can be changed with sliders, plus STL and STEP files.

Built for the Meta Global AI Developer Hackathon with Meta's SAM 3.1, Muse Spark Open and Muse Wonder.

## How it works

1. **Photo**: the part lies next to an ID-1 card (bank or transit card, 85.60 × 53.98 mm), shot from above.
2. **Masks (SAM 3.1)**: the card is found by name, the part by the user's click (a SAM point prompt).
3. **Measurements (deterministic code, no language model)**: the card gives the pixel-to-millimeter scale; the code measures the outline, its corners and arcs, and every hole (circle, rectangle, slot, ellipse or polygon) in millimeters.
4. **Candidates (Muse Spark Open on Baseten)**: the model gets the measurement table and the part's black-and-white silhouette and writes several CadQuery programs, asked in turn with three approaches (fewest parameters, feature based, symmetry first). It decides the structure and the parameter names; every number comes from the table. The live search stops once three passing candidates build the same shape.
5. **Checks**: each program is screened (only `cadquery`, `math` and the helper library `partkit` may be imported), built in a separate process, rendered from above and compared with the photo's mask (IoU), and checked against the measurements (holes within 0.5 mm, outline within max(1 mm, 2%)).
6. **Repair (Muse Wonder)**: if no program passes every check, Wonder sees the failed programs with their difference images and rejection reasons, explains what is wrong and writes a corrected program, which goes through the same checks (at most 2 rounds).
7. **Result**: the best program wins. If none passes, a baseline built straight from the measurements is returned, clearly marked as `fallback: measured shape, no design intent`, and the app says why (for example "The edges are irregular; the measured shape is shown.").
8. **Completion (Muse Wonder)**: if the code finds signs that the part itself is broken (a zigzag edge, material missing against its mirror image, a gap or a half hole in a hole pattern), Wonder suggests how the intact part was designed. The suggestion is a separate, checked program. The card says which added numbers are measured and which are estimated, asks for the estimated ones (with a suggested value) and asks whether to add features the photo cannot show; the user applies or ignores it.

## Meta models

| Model | What it does here | Files |
|---|---|---|
| **SAM 3.1** (Meta Model API) | Finds the card by name and the part by the user's click (point prompt); a second, zoomed-in request on the part | `sam_client.py`, `e2e_pipeline.py` (`find_masks`, `segment_crop`) |
| **Muse Spark Open** (Baseten, `meta-models/muse-spark-open-1026`, reasoning effort `medium`) | Writes the candidate CadQuery programs from the measurement table and the part's silhouette; suggests SAM names for the part if the click finds nothing | `candidates.py`, `prompt_suggestions.py`, `baseten_client.py` |
| **Muse Wonder** (Meta Model API, `muse-wonder-1.0`, reasoning effort `medium`): repair | When no candidate passes: diagnoses the failed programs from their code, difference images and rejection reasons, and writes a corrected program | `repair.py`, `repair_inputs.py` |
| **Muse Wonder**: completion of broken parts | Only when the code finds break cues: reads the cues, the rectified photo and the winning program, and suggests the missing part (a parameter or feature) with its reason | `completion.py`, `break_cues.py` |

## Quick start

Tested with **Python 3.13 on Windows 11**. The web page loads three.js from a CDN, so the browser needs internet access.

```powershell
git clone https://github.com/pnomokok/reversecad.git
cd reversecad
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt     # CadQuery is large: a few minutes
.venv\Scripts\python.exe -m uvicorn webapp.server:app
```

On macOS or Linux use `.venv/bin/python` instead of `.venv\Scripts\python.exe` (not tested there yet).

Open **http://127.0.0.1:8000**. Three saved synthetic runs replay **without API keys**: `A_light` (an 80 × 40 mm plate with four holes, the whole flow), `A_light_repair` (only broken candidates, repaired by Muse Wonder) and `D_tab_broken` (a part with a snapped-off tab and Muse Wonder's completion card).

### Live mode (your own photos)

Live mode calls the models, so it needs API keys:

```powershell
copy .env.example .env      # then write your keys into .env
```

| Variable | What for |
|---|---|
| `MODEL_API_KEY` | Meta Model API (SAM 3.1, Muse Wonder) |
| `BASETEN_API_KEY` | Baseten (Muse Spark Open, model `meta-models/muse-spark-open-1026`) |

`.env` is in `.gitignore` and never committed. Check the setup with `.venv\Scripts\python.exe check_env.py` (it reports keys as set or missing, never their values).

**What leaves your machine:**
- The photo goes to SAM (Meta).
- The candidate requests (Muse Spark Open) send only the part's black-and-white top-down mask, never the photo. Only if your click finds nothing is the photo also sent to Muse Spark Open, to suggest names for the part.
- A repair (Muse Wonder) sends the mask, the failed programs' code and their black, white, red and blue difference images; no photo.
- A completion (Muse Wonder) sends the part's top-down mask, the winning program and its silhouette; no photo (the mask gave the same results as the photo on all four test parts). It only runs when the code finds signs of a break.

Every model call is logged per run with its tokens and estimated cost (`usage.jsonl`, shown on the search screen).

## Taking a photo

- Put an ID-1 card (bank card, transit card) **right next to the part**: the scale is exact at the card and gets worse with distance from it.
- Shoot straight down from 60-70 cm with 2× zoom, the part and the card fully in the frame.
- A dark, even background with a lighter part works best; a dark part on a lighter background works too.
- Send photos at **original quality** (messenger apps shrink them; 1080 × 1920 left the card only about 430 px long).
- Cover any personal data on the card; only its edges are needed.

## Using the app

1. **Photo**: pick a saved run or upload a photo, click the part (not a hole), enter its thickness (a top view cannot show it).
2. **Measurements**: card, outline and holes are drawn over the photo with their sizes; the table shows the numbers the model will get.
3. **Candidates**: programs arrive one by one with their silhouette, IoU, parameter count and, if rejected, why.
4. **Model**: the result in 3D; one slider per named parameter rebuilds the part when released (about 0.3 s).
5. **Download**: STL (mesh), STEP (solid) or the CadQuery program (`.py`) with the slider values as its defaults.

## Command-line scripts

All scripts run from the repository root with the virtual environment's Python. Model answers are cached under `outputs/` (git-ignored), so re-running is free.

| Script | What it does | Calls APIs |
|---|---|---|
| `run_template_scenes.py [A_light B C D E] [--effort=low]` | Synthetic scenes of the template parts end to end, with ground truth, baseline and design-intent checks | yes (cached) |
| `run_real_photos.py [carton key blister]` | The pipeline on real photos in `data/private/` (git-ignored), compared with ruler values | yes (cached) |
| `run_repair_tests.py` | The repair loop on deliberately broken candidates and the cardboard (`outputs/repair_tests/`) | yes (Muse Wonder) |
| `run_broken_scenes.py` | Synthetic broken parts end to end, then a completion suggestion compared with the true design | yes |
| `compare_rounds.py` | Compile rate, correct topology, tokens and time per candidate round | no |
| `make_sample.py A_light A_light_repair D_tab_broken` | Copies synthetic runs into `samples/` in compact form | no |
| `make_repair_run.py` | Builds the `A_light_repair` run (A_light with only broken candidates) | yes (Muse Wonder) |
| `compare_completion_inputs.py` | Completion from the photo vs from the mask only, against the true design | yes (Muse Wonder) |
| `try_sam.py`, `try_two_cards.py`, `try_homography.py`, `try_baseten.py` | The measurement experiments recorded in `CLAUDE.md` | some |

## Tests

```powershell
.venv\Scripts\python.exe -m pytest
```

The tests never call an API. A few need runs saved under `outputs/` and are skipped in a fresh clone; the sample run in `samples/` covers the web app.

## Results so far

| What | Result |
|---|---|
| Scale: a second ID-1 card measured with the first as reference | mean error 0.48% (max 1.44%) |
| Holes on synthetic scenes (color method) | diameter within 0.15 mm, centers within 0.7 mm |
| Real photo: brass key next to a card (ruler: 57 × 22.5 mm, elliptical hole 12 × 6 mm) | outline 56.6 × 23.2 mm (−0.7% / +2.9%), hole measured as an ellipse 11.8 × 6.2 mm (−1.9% / +3.0%) |
| Candidates on synthetic parts A-D (plate, asymmetric plate, L plate, tabbed part), 10 each | 100% compiled with correct topology, IoU 0.98-0.99 |
| Selected model vs ground truth, synthetic plate `A_light` (true 80 × 40 mm, 4 × Ø6 mm) | 79.30 × 40.20 mm (−0.9% / +0.5%), hole diameters within 0.02 mm; fit to measurements 0.03 mm |
| Repair with Muse Wonder: 6 deliberately broken candidates on the **synthetic** parts A, C and D (a hole moved 4 mm, a corner cut 8 mm) and one **real** photo (hand-cut cardboard, no candidate returned code) | 6 of 7 cases repaired, all 6 synthetic ones in the first round, each diagnosis naming the injected fault; the cardboard failed twice by 0.6-0.8 mm; $0.04-0.08 and 9-25 s per synthetic repair, $0.61 in total |
| Completion with Muse Wonder on 4 **synthetic** broken parts with a known design (A with a chipped corner, A broken through a hole, A with a hole never drilled, D with its tab snapped off) | 4/4 suggestions valid and closer to the true design (IoU 0.78-0.97 before, 0.87-0.98 after; the three A parts reach about 0.98). D is partly right: the tab is restored 3 mm too long, and the 6 mm hole that was in the lost tab is not invented, since nothing in the photo shows it. The card asks for both; answered with the true values, D reaches IoU 0.974 with both holes |
| **300 random synthetic parts** (plates, L's, tabbed bodies, 77 broken), whole pipeline, against their true design | design found for 295 (98.3%); intact parts: right topology 220/223, length and width errors at most 1.33% (median 0.73% / 0.57%), hole diameters within 0.27 mm (median 0.05 mm); broken parts: break cues found 48/77, and 43 of the 46 with an applied completion end with the right topology; $25.29 in total, about $0.08 and 2 minutes per part |
| Design intent of the winner vs the baseline | 5-8 named parameters instead of 15-23; shared hole diameter, symmetry and edge margins kept when a dimension changes |
| Reasoning effort | `medium` (the default here) keeps the default level's quality at 3-6× fewer tokens |
| Live run, end to end (3 candidates) | about 45 s |

Two different numbers appear in the app. **Fit to measurements** is how closely a candidate follows the measured outline (the largest distance from a measured corner or arc point to the candidate's outline); it says nothing about whether the measurements were right. **vs ground truth** compares the model with the part's true size and is only shown for synthetic scenes, where that size is known; it includes the photo measurement's own error.

Details, including what did not work and why, are in [CLAUDE.md](CLAUDE.md) (the project's working notes).

## Known limits

- **Transparent materials and blind holes** look like through-holes from above (tested on a blister pack); a single top view cannot tell them apart.
- **Hand-cut or torn parts** are hard: on a hand-cut cardboard part no candidate passed and the result was the measured baseline.
- **Flat, prismatic parts only** (plates, brackets, covers, tabs); thickness is entered by the user.
- **Repair and completion are tested mostly on synthetic parts**: the only real case so far (the cardboard) was not repaired, and completion has not been tried on a real broken part.
- **A completion can only restore what the photo hints at**: features lost with the broken piece (such as a hole in a snapped-off tab) are not suggested.
- The scale rule is temporary: the homography is used only when the card looks tilted (opposite edges differ by more than 2%), otherwise the simple card scale.
- **On real photos the width comes out 3-5% too large** (key +3.1%, cardboard +3.0%); lengths are within −0.7% to +3.3%. Not yet explained; to be checked on more real parts.

## Project layout

| Path | Contents |
|---|---|
| `sam_client.py`, `homography.py`, `measure.py`, `part_measurements.py`, `refine_holes.py` | Masks, scale and the measurement table |
| `model_view.py`, `candidates.py`, `partkit.py`, `prompt_suggestions.py` | What the model sees, the prompt, and the helper library the programs use |
| `run_candidate.py`, `candidate_runner.py`, `build_worker.py` | Screened execution of generated programs in separate processes |
| `iou.py`, `deviation_check.py`, `design_intent.py`, `baseline_cad.py` | Scoring, limits, design-intent test and the no-model baseline |
| `e2e_pipeline.py` | The whole pipeline for one scene or photo |
| `repair.py`, `repair_inputs.py`, `break_cues.py`, `completion.py` | Muse Wonder: repair of failed candidates, break cues and completion suggestions |
| `sam_decode.py`, `usage_ledger.py` | Fast SAM mask decoding (identical to the library's), per-run model usage and cost |
| `webapp/` | FastAPI back end (`server.py`, `replay.py`, `live.py`, `builder.py`) and the page (`static/`; all styling variables in `tokens.css`) |
| `parts/`, `synthetic_scene.py` | Template test parts with ground truth, broken versions with their intact design, and their synthetic photos |
| `samples/` | Compact saved synthetic runs for replay without API keys (the whole flow, a repair, a completion) |
| `tests/` | pytest suite |

## License

MIT, see [LICENSE](LICENSE).
