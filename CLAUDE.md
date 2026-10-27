# ReverseCAD

A Meta Global AI Developer Hackathon project. From a photo of a part, it generates a 3D model with **real millimeter dimensions** that is **editable (parametric)**. The output is not a dead mesh but CadQuery code whose parameters can be changed.

## Working with me

- I'm new to coding. At every step, briefly explain what you are doing and why, in simple language.
- Explain things to me in Turkish in chat. Code identifiers, comments, repo files and commit messages are in English (international hackathon).
- Tell me first whenever you need to install, delete, or run something long.
- Keep code in small, separate files; start each file with a short description of what it does.
- API keys live only in the `.env` file, and `.env` is in `.gitignore`. Never write keys into code or output.
- Strip the EXIF data (GPS location, camera info, etc.) from every photo before it goes into the repo. Test photos that may contain personal information (card details, location) stay in `data/private/`, which is git-ignored.
- Don't move to the next step before finishing the current one. Each step ends with a small test or output showing it works.

## Pipeline

1. **Input:** A photo taken from above of the part with a credit card (85.60 × 53.98 mm) next to it. (Later: two canonical shots, from the top and from the side.)
2. **Mask:** Meta SAM 3.1 extracts the masks of the card and the part using a text prompt (`credit card`, `bracket`, etc.).
3. **Scale and measurement:** Deterministic Python code finds the `mm_per_pixel` ratio from the card mask; it computes the part's bounding box, hole diameters and center coordinates in millimeters. If needed, it builds a homography from the card's four corners (`cv2.getPerspectiveTransform`) and rectifies the image to orthographic.
4. **Candidate generation:** Muse Spark Open (via Baseten) takes the image + measurement table and writes 10-30 different candidate CadQuery programs.
5. **Validation:** Each candidate is compiled, its orthographic silhouette is rendered, and IoU against the SAM mask is measured.
6. **Selection:** The candidate with the highest IoU wins. If the threshold isn't met, the XOR difference image is fed back to the model and a second generation is produced.
7. **Output:** The winning model is displayed and can be downloaded as STL/STEP; parameters can be changed with sliders and recompiled instantly.

## Three critical engineering decisions

1. **Scale comes from a planar reference.** Not a coin, but a credit card or a square with known edges. The photo is taken from 60-70 cm away, with zoom, at a perpendicular angle (to reduce parallax error).
2. **Alignment is done via canonical shots; camera pose is not estimated.** The SAM mask and the rendered silhouette are both moved to their centroid and rotated to their principal axis (PCA or `cv2.minAreaRect`); then IoU is computed. Rendering is always **orthographic**.
3. **Code provides the measurements, the model provides the topology.** The language model does not count pixels or calculate millimeters. Numbers come from the measurement table; the model is asked only for the structure: is it an L-bracket or a plate, where are the holes, is there a chamfer.

## Scope

Only flat-faced, prismatic parts with holes: brackets, plates, covers, simple tabs, fixtures. Curved and organic parts are out of scope.

## Models

| Model | Where | Use |
|---|---|---|
| SAM 3.1 | Meta Model API | Mask extraction, validation |
| Muse Spark Open | Baseten, model name exactly `meta-models/muse-spark-open-1026` (the docs omit `-1026`; we always add it) | Parallel candidate code generation |
| Muse Wonder | Meta Model API | Geometric reasoning for hard candidates (next phase) |
| Muse Voice Transcribe | Meta Model API | Voice editing (nice to have) |

Environment variables: `BASETEN_API_KEY`, `MODEL_API_KEY` (Meta Model API key; Meta's docs use this name). Both in `.env`.

## How to call Muse Spark Open

From Baseten's docs plus our first calls (`baseten_client.py`, `try_baseten.py`).

- OpenAI-compatible Chat Completions API: `base_url="https://inference.baseten.co/v1"`, `api_key=BASETEN_API_KEY`, `model="meta-models/muse-spark-open-1026"` (the hackathon key only works with this name).
- Accepts text, image, audio and video; returns text. Images go in as base64 data URLs (`image_url` content part).
- The model always reasons. The reasoning arrives in `choices[0].message.reasoning_content`, the answer in `choices[0].message.content`. Reasoning tokens count toward `max_tokens` (first calls: 65-85% of output tokens were reasoning), so keep `max_tokens` generous and check `finish_reason == "stop"`.
- An image of about 840 × 440 px cost about 475 prompt tokens; `usage.prompt_tokens_details.image_tokens` comes back empty.
- Code prompts must say: fixed function name, no `show_object(...)` (CQ-editor only; raises `NameError` in our code), a single ```python block. In image prompts, say "white = part, black = background" (the model read the render's black margin as a "thick border").

## How to call SAM 3.1

Summary of Meta's docs. Source: Meta Model API docs, "Segment Anything Model" pages.

**Request**
- OpenAI-compatible Responses API: `base_url="https://api.meta.ai/v1"`, `api_key=os.environ["MODEL_API_KEY"]`, `model="sam-3.1"`. In Python, the `openai` package is used.
- A single user message: one `input_text` (the object's name) + one `input_image`.
- A local photo is passed in the `image_url` field as a **base64 data URL**: `data:image/jpeg;base64,...`
- The prompt must be a short English noun phrase: `credit card`, `key`, `metal bracket`. Don't write commands or questions ("segment the card" often returns empty).
- **One object per request.** Send two separate requests for the card and the part. A comma-separated list ("card, key") returns zero results.
- Recommended settings: `stream=True`, `metadata={"mask_encoding": "one_bit", "include_confidence": "true"}`. Metadata values are strings (`"true"`, not a JSON boolean).
- Price: $0.0025 per image.

**Response**
- Comes as text, with a special syntax. Example: `<0f>0<|box;x1=353;y1=382;x2=453;y2=427;w=537;h=561;c=0.96|><|mask;x=0;y=0;c=0.96;data=46,101,!...|>`
- The box (`box`) is in the source photo's pixels; `x2`, `y2` are inclusive. `w`, `h` are the photo's size.
- The mask (`mask`) is not full photo size but a smaller raster: `data=<height>,<width>,...`. It covers **the inside of the box** and is placed on the full photo at the box's top-left corner (`x1`, `y1`). The parser exposes this as the mask record's `bounds`. **The raster's long side is capped at 1024 px:** for larger objects it arrives downscaled (a 750 × 1181 card box came with a 650 × 1024 mask) and must be stretched to the box size before placing (`place_mask` in `sam_client.py`). Without that the card mask was cut off and the key measured +14%.
- If there is no match, the response is empty; this is not an error but a normal result, handle it separately in code.
- When the same request is repeated, box and mask edges may vary slightly. Account for this in measurement tests.

**Parsing: don't write it by hand, use the library**
- `pip install meta-sam-parser` (Python ≥ 3.10, no dependencies; import name `meta_sam_parser`). Since we'll use the confidence score, the version must be at least 0.0.6.
- Mask decoding: `decode_mask_to_raster` (0/1 values, row-major, length height × width), `decode_mask_to_rle` (COCO RLE), `decode_mask_to_svg_path`.
- The names of the stream-parsing functions reflect the TypeScript version (in TypeScript, `parseImageStream`, `recordsOfKind`). Check the exact Python names from the package itself; don't guess. In Python (checked, v0.1.0): `parser = image_segmentation_format().create_parser()`, `parser.push(text)`, `parser.finish(CompletedOutcome()).result.records` (`SegmentationBoxRecord` with half-open `left/top/right/bottom`, `SegmentationMaskRecord` with `mask`, `bounds`, `confidence`). The async `parse_responses_stream` also exists; we collect the stream text synchronously instead (`sam_client.py`).
- Prompt wording matters: `credit card` returned nothing for the sample's transit card (Bursakart, same ID-1 size); `card` works.
- Repeatability: three identical requests returned identical boxes, masks and confidences. Identical input bytes give identical output; variation should be measured with separate photos of the same scene.

**Phone photo trap: EXIF orientation**
Phone photos are often saved sideways and rotated via an EXIF tag. SAM gives coordinates according to the orientation the photo **appears on screen**. Before sending a photo, apply `ImageOps.exif_transpose` with Pillow, and use the corrected version both for SAM and in your own measurement code; otherwise the mask and the photo end up 90 degrees off.

**May be useful later**
- Box and point prompts: if we know where an object is, we can have it masked by giving a box/point instead of a name (`build_object_prompt`). A name and a box cannot be used together in one request.
- Video support: MP4/MOV, objects are tracked across frames with the same ID. For now we work with a single photo.

## Success criteria

| Metric | Target |
|---|---|
| Dimension error (model vs ruler) | Under 5% on average |
| Silhouette IoU | Above 90% |
| Success rate (runs passing the threshold) | Above 70% |
| Compile success on parameter change | Above 95% |

## Hackathon rules

- Only code written during the hackathon.
- The repo is public and a single piece; the jury must be able to run the demo themselves (setup steps must be clear in the README).

## Status

- [x] Scale test (manual): key + card photo, SAM masks separated cleanly; computed length 56-57 mm, ruler 55-56 mm, difference about 1-3%. Sample photo: `data/private/ornek_anahtar.jpg` (git-ignored, not in the repo)
- [x] Python environment, git, `.gitignore`, `.env` (`.venv` + `requirements.txt`, check: `.venv\Scripts\python.exe check_env.py`)
- [x] Hand-written simple CadQuery part + orthographic silhouette render (`parts/holed_plate.py`, `render_silhouette.py`, tests: `.venv\Scripts\python.exe -m pytest`). A holed plate was chosen over an L-bracket: from above, an L-bracket's silhouette is just a rectangle and the "L" is lost (that belongs to alignment and multi-view validation), while a holed plate shows both the outer edge and the holes.
- [x] IoU function (centering + alignment) and its tests (`iou.py`). Scale is normalized from known mm/px, never fitted (a 10% larger plate scores 0.83). Tries 0/180 degrees x mirrored and reports the winner. **Known weakness:** small holes barely move IoU (plate without holes 0.963, wrong orientation of an asymmetric plate about 0.90), so IoU alone cannot validate holes; hole count/diameter/position must be checked separately against the measurement table.
- [x] First call to Baseten (`try_baseten.py`): text → CadQuery code and image → shape description both work; outputs in `outputs/baseten/`.
- [x] Calling SAM 3.1 from code (`sam_client.py`, `measure.py`, `overlay.py`, `try_sam.py`). Key vs ruler 55-56 mm over four photos in `data/private/`:

  | Photo | Key | Error vs 55.5 mm |
  |---|---|---|
  | original | 55.60 mm | +0.18% |
  | camera closer | 55.02 mm | -0.87% |
  | blurred | 55.23 mm | -0.48% |
  | positions swapped, key rotated, camera farther | 57.98 mm | **+4.47%** |

  Blur and camera distance are handled. The swapped shot's error is **not** camera tilt (an earlier rough corner estimate said 1.29% left-right; line-fitted corners give 0.19%). Not yet measured: pure repeat shots with nothing moved.
- [x] Homography from the card's corners (`homography.py`, offline comparison `try_homography.py`). Corners come from lines fitted to the straight middle of each card side (rounded corners). Tilt check is now opposite card edges (left vs right, top vs bottom) > 2%, replacing the long-vs-short ratio check. Synthetic tilted scene: recovers the key within 0.5% where the simple scale is off by more than 2%, even below the 2% warning. On the four real photos it does **not** help:

  | Photo | Key distance from card (card lengths) | Before | After |
  |---|---|---|---|
  | original | 0.94 | +0.18% | +2.53% |
  | closer | 0.83 | -0.87% | +0.44% |
  | swapped | 1.53 | +4.47% | +4.31% |
  | blurred | 0.82 | -0.48% | +0.82% |

  The largest error is at the largest distance (only one far point, so not conclusive); suspected cause: lens distortion with the key and card at opposite edges of the frame, which a homography cannot fix. All corrected card outlines measure 0.1-0.5 mm larger than 85.60 × 53.98. The Bursakart is ID-1: ruler 85 × 54 mm and it lines up with a bank card. **Key ground truth:** the earlier 55-56 mm came from an on-screen ruler; a physical ruler gives **57 mm** (±0.5 mm reading). Against 57 mm the homography is better on every photo (-0.2%, -2.2%, +1.6%, -1.8%; mean absolute error 1.5% vs 2.7% for the simple scale), but the ruler's own uncertainty is about 1%. 

  **Decisive test with a part of exactly known size** (`try_two_cards.py`): the user's school card (ID-1, personal data painted out) next to the Bursakart, each card measured using the other as the scale, 3 photos × 2 directions × long and short side:

  | Photo | Card distance | Simple scale | Homography |
  |---|---|---|---|
  | both at frame center | 1.2 | -1.32 … +1.45% | -1.44 … +0.24% |
  | opposite frame edges | 1.6 | -0.84 … +0.60% | -0.58 … +1.00% |
  | rotated 90° | 1.2 | -1.11 … +1.45% | -0.03 … +0.68% |
  | **mean absolute error** | | **0.86%** (max 1.45%) | **0.48%** (max 1.44%) |

  **Decision: the homography is the default measurement method.** Lens distortion is small (at most ~1% at opposite frame edges; no lens correction needed). Rotation is handled. Each photo's two directions mirror each other (the reference card's own mask error flips sign), so the error of a single measurement is roughly half of these numbers. The key's +1.6% in the swapped photo fits within this plus the ruler's ±1%.
- [x] End-to-end skeleton on a **synthetic scene** (first version; now `e2e_pipeline.py` + `run_template_scenes.py`, outputs in `outputs/e2e/<scene>/`): photo → SAM → homography measurements → 5 Muse Spark Open candidates → compile in a separate process → silhouette → IoU → best.
  - Scene (`synthetic_scene.py`): the CadQuery 80 × 40 plate (4 × Ø6, 8 mm in), rotated 8°, next to a card on dark fabric, slight tilt (card top-bottom 1.30%), blur and noise.
  - SAM: `credit card` found the synthetic card; `plate` found nothing, `metal plate` worked.
  - **SAM fills or fragments small holes** (6 mm ≈ 55 px): 7 "holes" measured. Fix: `refine_holes.py` keeps SAM's outer outline and finds holes from brightness inside it (Otsu; assumes the part is lighter than the background). Result: 4 holes, Ø 6.08-6.09 mm, centers within 0.23 mm, outline 80.38 × 40.24 mm, mask IoU vs truth 0.974 → 0.990.
  - Muse Spark Open: with `max_tokens=8000` all 5 candidates spent everything on reasoning (the 7-hole table and an ambiguous "thickness along +Z") and returned no code. With a clean table, "bottom face at Z = 0" and `max_tokens=16000`: 5/5 returned code (2.7-4k output tokens), 5/5 compiled, all IoU 0.9923 (true-part ceiling 0.9916; candidates use the measured numbers, which fit the mask slightly better).
  - Candidate code is screened before running (`candidates.check_code`: only cadquery/math imports, no open/exec/eval/show_object) and run in a separate process with a timeout (`run_candidate.py`).
  - All 5 candidates are geometrically identical: for a plate the table fixes everything. Candidate variety will only matter for parts whose topology is ambiguous.
- [x] Hole methods, prompt suggestions, structurally different parts (`run_template_scenes.py`; template parts in `parts/template_parts.py`: A 80 × 40 plate, B asymmetric plate, C flat L, D tabbed part).
  - **Holes, three methods** (max diameter / center error vs truth):

    | Scene | SAM on full photo | SAM on crop | Color |
    |---|---|---|---|
    | A light | 0 holes (all filled) | 0.17 / 0.24 mm | 0.08 / 0.21 mm |
    | A dark part | 2 broken holes | 0.20 / 0.14 mm | 0.06 / 0.14 mm |
    | B | 0.13 / 0.10 mm | 0.19 / 0.06 mm | 0.11 / 0.10 mm |
    | C | 0.10 / 0.15 mm | crop found nothing | 0.04 / 0.13 mm |
    | D | 0 holes (all filled) | crop found nothing | 0.12 / 0.14 mm |

    Pipeline uses the crop mask unless it fails or a hole looks wrong (roundness < 0.85, Ø < 1.5 mm), then color. The color method now samples the background from a ring outside the outline and the part color from inside, so it also works for parts darker than the background.
  - **Prompt suggestions** (Muse Spark Open names the part, every suggestion is tried on SAM, the most confident mask wins): about half the suggestions find nothing; the model called B a "banknote" and D a "camera icon" (D still segmented as "camera icon", 0.82). If no suggestion works, fixed fallbacks are tried (`metal plate`, `plate`, `flat metal part`); B was found by `flat metal part`.
  - The measurement table now includes the outline's corners (`outline.polygon_mm`, lines fitted per edge and intersected), so L arms and tabs come from code, not from the model reading pixels.
  - **Candidates, 10 per part** (correct topology = corner count, hole count, every hole within 3 mm and ±25% diameter; mirroring allowed):

    | Part | Compiled | Correct topology | Cause of failures |
    |---|---|---|---|
    | B, first prompt | 10/10 | 7/10 | 3 used `.center()` for holes; it is cumulative, so the 2nd hole moved by the 1st one's offset (IoU still 0.95) |
    | B, with a `pushPoints` hint | 10/10 | 10/10 | |
    | C | 10/10 | 10/10 | |
    | D | 9/10 | 7/10 | 2 used `moveTo(p0).polyline(p[1:])`; `polyline` drops the current point by default, so the outline lost a corner and the closing edge cut through the tab's hole; 1 ran out of 16000 tokens |

    Best IoU 0.993-0.994 for every part; the topology check catches errors that IoU passes.
  - **No geometric variety, only code variety:** all candidate files differ as text and use different CadQuery calls, but every correct one gives the same shape, because the table fixes every number (corners and holes). The wrong ones are CadQuery API pitfalls, not alternative readings of the part. Variety would need ambiguity the table does not resolve (e.g. hidden features, chamfers, multi-view parts).
  - With a `polyline(points).close()` hint (no `moveTo` + `polyline`), D went from 7/10 to 10/10.
- [x] Click selection, baseline and design intent (`run_template_scenes.py`; table in `outputs/e2e/design_intent_table.json`).
  - **Part selection by click:** SAM point prompt (`sam_client.point_prompt`, built with `build_object_prompt`) at a simulated click (the pixel deepest inside the part). Found the part in all 5 scenes with confidence 0.988-0.992 (names: 0.72-0.88). Finding by name (suggestions, then fallbacks) is kept as the fallback; it is only asked when the click fails.
  - **Hole methods with click masks:** the cropped SAM mask failed the hole check in A light (10 "holes") and A dark (7), so color was used there. Where the crop passed (B, C, D) its diameters were 0.2-0.4 mm too large, while color stayed within 0.04-0.12 mm. Color has been the most accurate method in every scene so far.
  - **Baseline without a language model** (`baseline_cad.py`): extrudes the measured corner polygon and cuts the measured holes; every corner and hole is its own parameter.
  - **Design-intent test** (`design_intent.py`): changes parameters and rebuilds. Shared hole diameter: one parameter resizes every hole of an equal-size group and nothing else. Length +10 mm: the true part's symmetry is kept (mirror IoU ≥ 0.98) and off-axis holes keep their distance to the nearer end. Symmetry axes come from the truth automatically (A both, B top-bottom, C none, D left-right).
  - **Results, winner (correct topology first, then IoU, then fewer parameters) vs baseline:**

    | Part | Correct topology | Parameters (winner / baseline) | Shared hole diameter | Symmetric after length change | Edge margin kept | IoU (winner / baseline) |
    |---|---|---|---|---|---|---|
    | A | 10/10 | 5 / 21 (−76%) | yes / no | yes / no | yes / no | 0.9890 / 0.9949 |
    | B | 10/10 | 7 / 15 (−53%) | n/a (different sizes) | yes / no | no / no | 0.9928 / 0.9937 |
    | C | 8/10 (2 ran out of tokens) | 6 / 19 (−68%) | yes / no | n/a (not symmetric) | yes / no | 0.9836 / 0.9908 |
    | D | 10/10 | 7 / 23 (−70%) | n/a (different sizes) | yes / no | n/a (holes on the axis) | 0.9791 / 0.9824 |

    The baseline has no length parameter at all, so it fails every intent check. Its IoU is slightly higher because it copies the measurement noise; in A it even beats the true part (0.9905). The design-intent prompt also produced real variety for the first time: one B candidate rounded to the template's design values (60 × 30, hole_spacing 28, offset 2) and three D candidates rounded the holes to 6.0 / 10.0. B's "edge margin kept: no" is debatable: the winner places the holes from the center, which is also a valid intent for an asymmetric plate. The longer prompt costs tokens: 2 of C's 10 candidates used all 16000 tokens on reasoning.
- [ ] End-to-end on a real photo of a holed part
