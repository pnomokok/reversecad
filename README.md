# ReverseCAD

ReverseCAD turns one top-down photo of a flat part into an **editable CAD program with real millimeter dimensions**. Put the part next to a bank card, click the part, and get CadQuery code whose parameters (length, hole diameter, edge margin, tab width, ...) can be changed with sliders, plus STL and STEP files.

Built for the Meta Global AI Developer Hackathon with Meta's SAM 3.1 and Muse Spark Open.

## How it works

1. **Photo**: the part lies next to an ID-1 card (bank or transit card, 85.60 × 53.98 mm), shot from above.
2. **Masks (SAM 3.1)**: the card is found by name, the part by the user's click (a SAM point prompt).
3. **Measurements (deterministic code, no language model)**: the card gives the pixel-to-millimeter scale; the code measures the outline, its corners and arcs, and every hole (circle, rectangle, slot, ellipse or polygon) in millimeters.
4. **Candidates (Muse Spark Open on Baseten)**: the model gets the measurement table and the part's black-and-white silhouette and writes several CadQuery programs. It decides the structure and the parameter names; every number comes from the table.
5. **Checks**: each program is screened (only `cadquery`, `math` and the helper library `partkit` may be imported), built in a separate process, rendered from above and compared with the photo's mask (IoU), and checked against the measurements (holes within 0.5 mm, outline within max(1 mm, 2%)).
6. **Result**: the best program wins. If none passes, a baseline built straight from the measurements is returned, clearly marked as `fallback: measured shape, no design intent`.

## Meta models

| Model | What it does here | Files |
|---|---|---|
| **SAM 3.1** (Meta Model API) | Finds the card by name and the part by the user's click (point prompt); a second, zoomed-in request on the part | `sam_client.py`, `e2e_pipeline.py` (`find_masks`, `segment_crop`) |
| **Muse Spark Open** (Baseten, `meta-models/muse-spark-open-1026`, reasoning effort `medium`) | Writes the candidate CadQuery programs from the measurement table and the part's silhouette; suggests SAM names for the part if the click finds nothing | `candidates.py`, `prompt_suggestions.py`, `baseten_client.py` |

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

Open **http://127.0.0.1:8000**. The saved sample run `A_light` (a synthetic 80 × 40 mm plate with four holes) replays the whole flow **without API keys**.

### Live mode (your own photos)

Live mode calls the models, so it needs API keys:

```powershell
copy .env.example .env      # then write your keys into .env
```

| Variable | What for |
|---|---|
| `MODEL_API_KEY` | Meta Model API (SAM 3.1) |
| `BASETEN_API_KEY` | Baseten (Muse Spark Open, model `meta-models/muse-spark-open-1026`) |

`.env` is in `.gitignore` and never committed. Check the setup with `.venv\Scripts\python.exe check_env.py` (it reports keys as set or missing, never their values).

**What leaves your machine:** the photo goes to SAM (Meta). The candidate requests send only the part's black-and-white top-down mask, never the photo. Only if your click finds nothing is the photo also sent to Muse Spark Open, to suggest names for the part.

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
| `compare_rounds.py` | Compile rate, correct topology, tokens and time per candidate round | no |
| `make_sample.py A_light` | Copies a synthetic run into `samples/` in compact form | no |
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
| Design intent of the winner vs the baseline | 5-8 named parameters instead of 15-23; shared hole diameter, symmetry and edge margins kept when a dimension changes |
| Reasoning effort | `medium` (the default here) keeps the default level's quality at 3-6× fewer tokens |
| Live run, end to end (3 candidates) | about 45 s |

Details, including what did not work and why, are in [CLAUDE.md](CLAUDE.md) (the project's working notes).

## Known limits

- **Transparent materials and blind holes** look like through-holes from above (tested on a blister pack); a single top view cannot tell them apart.
- **Hand-cut or torn parts** are hard: on a hand-cut cardboard part no candidate passed and the result was the measured baseline.
- **Flat, prismatic parts only** (plates, brackets, covers, tabs); thickness is entered by the user.
- **SAM mask decoding is slow**: the parser library decodes masks in pure Python, about 15 s for a card-sized mask; the app shows progress while it runs.
- The scale rule is temporary: the homography is used only when the card looks tilted (opposite edges differ by more than 2%), otherwise the simple card scale.

## Project layout

| Path | Contents |
|---|---|
| `sam_client.py`, `homography.py`, `measure.py`, `part_measurements.py`, `refine_holes.py` | Masks, scale and the measurement table |
| `model_view.py`, `candidates.py`, `partkit.py`, `prompt_suggestions.py` | What the model sees, the prompt, and the helper library the programs use |
| `run_candidate.py`, `candidate_runner.py`, `build_worker.py` | Screened execution of generated programs in separate processes |
| `iou.py`, `deviation_check.py`, `design_intent.py`, `baseline_cad.py` | Scoring, limits, design-intent test and the no-model baseline |
| `e2e_pipeline.py` | The whole pipeline for one scene or photo |
| `webapp/` | FastAPI back end (`server.py`, `replay.py`, `live.py`, `builder.py`) and the page (`static/`; all styling variables in `tokens.css`) |
| `parts/`, `synthetic_scene.py` | Template test parts with ground truth and their synthetic photos |
| `samples/` | A compact saved run for replay without API keys |
| `tests/` | pytest suite |

## License

MIT, see [LICENSE](LICENSE).
