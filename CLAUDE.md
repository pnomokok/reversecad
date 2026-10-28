# ReverseCAD

A Meta Global AI Developer Hackathon project. From a photo of a part, it generates a 3D model with **real millimeter dimensions** that is **editable (parametric)**. The output is not a dead mesh but CadQuery code whose parameters can be changed.

## Working with me

- I'm new to coding. At every step, briefly explain what you are doing and why, in simple language.
- Explain things to me in Turkish in chat. Code identifiers, comments, repo files and commit messages are in English (international hackathon).
- Tell me first whenever you need to install, delete, or run something long.
- Keep code in small, separate files; start each file with a short description of what it does.
- API keys live only in the `.env` file, and `.env` is in `.gitignore`. Never write keys into code or output.
- Strip the EXIF data (GPS location, camera info, etc.) from every photo before it goes into the repo. Test photos that may contain personal information (card details, location) stay in `data/private/`, which is git-ignored.
- **The measurement side is frozen** (decided 2026-10-27): scale and homography rule, hole finding, shape thresholds. Do not change them unless a measured error exceeds 5%. Changes go to the model side (prompt, model view, partkit, checks).
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

1. **Scale comes from a planar reference.** Not a coin, but a credit card or a square with known edges. The photo is taken from 60-70 cm away, with zoom, at a perpendicular angle (to reduce parallax error). **Put the card right next to the part**: scale (and the homography) is exact at the card and degrades with distance from it; on real photos with the part 1-2 card lengths away, errors reached 4-10%. Send photos at original quality (WhatsApp-compressed 1080 × 1920 photos left the card only about 430 px long).
2. **Alignment is done via canonical shots; camera pose is not estimated.** The SAM mask and the rendered silhouette are both moved to their centroid and rotated to their principal axis (PCA or `cv2.minAreaRect`); then IoU is computed. Rendering is always **orthographic**.
3. **Code provides the measurements, the model provides the topology.** The language model does not count pixels or calculate millimeters. Numbers come from the measurement table; the model is asked only for the structure: is it an L-bracket or a plate, where are the holes, is there a chamfer.

## Scope

Only flat-faced, prismatic parts with holes: brackets, plates, covers, simple tabs, fixtures. Curved and organic parts are out of scope.

**Known limit: transparent materials and blind holes cannot be told apart from through-holes in a single top-down photo.** Anything through which the background shows (a clear dome, a blind pocket under clear plastic) looks like a through-hole from above. Tested on a blister pack whose pockets are closed by clear domes: every hole method reported the pockets as through-holes. Telling them apart needs a second view (side shot) or the user's input.

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

## How to call Muse Wonder

From the user's summary of Meta's docs plus one trial call (2026-10-28).

- Model name exactly `muse-wonder-1.0` (checked in `GET https://api.meta.ai/v1/models` with `MODEL_API_KEY`; the same list has `sam-3.1`, `muse-spark-1.3`, `muse-image-1.0`, `muse-voice-transcribe-1.0`).
- Same requests and endpoints as Muse Spark on the Meta Model API: Responses, Chat Completions and Messages; only the model name differs. `base_url="https://api.meta.ai/v1"`, `api_key=MODEL_API_KEY`.
- Input: text, images, video, audio and PDF; context 1,048,576 tokens. Reasoning levels from `minimal` to `max` (`max` does not turn on Wonder Full).
- Trial call (Chat Completions, `reasoning_effort="low"`, two 320 px PNGs as base64 data URLs in `image_url` parts plus a short question): accepted, 8.9 s. **Both images were seen** (it described the tilted mask and the axis-aligned XOR image with its red and blue fringes separately).
- Response fields: the answer is in `choices[0].message.content`. **No reasoning text is returned** (no `reasoning_content`, unlike Spark on Baseten), but reasoning is counted: `usage.completion_tokens_details.reasoning_tokens` (727 of 806 completion tokens at `low`). `usage.prompt_tokens` was 237 for the two small images and the question; `prompt_tokens_details.image_tokens` comes back empty.
- Price (project document): $4 per million input tokens, $20 per million output tokens; completion tokens include the reasoning tokens. The trial call cost about $0.017.

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
- **Decoding speed** (`sam_decode.py`): the library's pure-Python decoder took about 6 s per card mask, and its stream parser already decodes every mask once just to validate it, so `parse_detections` decoded each mask twice (about 13 s for the card). `sam_decode` is a tightened copy of the library's one_bit decoder (context shifted from the previous pixel, range decoder in local variables, no re-encode check; numpy only for base85, since the adaptive range coder is sequential). The parser's validation uses it too, and the result is cached for the second decode. Card answer: 12.9 s → 1.35 s. Exactness: identical rasters to the library on all 73 masks in the 62 saved SAM answers (`FULL_SAM_CHECK=1 pytest tests/test_sam_decode.py`); anything else (another encoding, a leftover or missing byte, a bad character) falls back to the library, which also keeps its errors for broken payloads.
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
  - **Hole methods with click masks:** the cropped SAM mask failed the hole check in A light (10 "holes") and A dark (7), so color was used there. Where the crop passed (B, C, D) its diameters were 0.2-0.4 mm too large, while color stayed within 0.04-0.12 mm. Color has been the most accurate method in every scene so far. **Now color is the primary hole method and the cropped SAM mask the fallback** (used when color's holes fail the roundness/size check).
  - **Cropped SAM holes are systematically too large** where the crop passed the check (B, C, D): 6 of 6 holes, +0.11 to +0.43 mm, mean +0.27 mm, roughly 3% of the diameter. The outer outline is not affected (all three methods share the same +0.2-0.4 mm outline error, which comes from SAM's full-photo outline), so it is not a scale error: SAM pulls hole edges into the material. Based on 6 synthetic holes only; check on real photos.
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
- [x] Non-circular holes. Each hole is classified by overlap with ideal shapes built from its own size and angle: equal-area circle, rectangle (minimum-area rectangle), slot (same rectangle with semicircular ends); below 0.9 overlap it is a polygon given by its corners. A simple area-ratio threshold cannot separate a slot from a rectangle (a 20 × 6 slot fills 94% of its rectangle). The table gives circle: diameter; rectangle/slot: length (end to end), width, angle from the u axis; polygon: corners. The hole check (`holes_look_right`) now rejects polygons, solidity < 0.9 and holes under 1.5 mm, instead of anything not round. Template part E: 70 × 40 plate, 16 × 8 rectangular hole at (20, 20), 20 × 6 slot at (50, 20). Scene E: color method 0.13 mm max equivalent-diameter error, 10/10 candidates correct topology; the winner uses exactly the design values (70 × 40, 16 × 8, 20 × 6, hole_spacing 30 symmetric about the center) and reaches the true part's IoU (0.9922). 8 parameters vs 19 for the baseline.
- [x] partkit round (`partkit.py`, `model_view.py`, `compare_rounds.py`; candidates in `candidates_kit/`).
  - **Model view of the table:** the measurement table is unchanged; the model gets a simplified outline: approxPolyDP at the outline's deviation limit, corners turning less than 40° removed (a torn edge zigzags with shallow turns, designed features turn sharply) unless a neighboring edge is a smooth arc (round notch), each edge the least-squares line through its points, coordinates re-centered on that outline's bounding box. Cardboard: 23 corners → 7 (torn edge one line, notch kept as 3 corners); C, D, E unchanged.
  - **Deviation limits:** outline length/width max(1 mm, 2%); holes (size and position) and corners of features with an edge under 20 mm: 0.5 mm; every corner the model was shown must lie that close to the candidate's outline.
  - **partkit:** tested helpers with absolute coordinates (plate, outline_from_points, symmetric_points, grid_points, hole_pattern, cut_circle/rectangle/slot/ellipse/polygon, semicircle_notch, tab); the prompt lists them, generated from the docstrings, instead of the pitfall hints. The tests rebuild template parts A-E with them.
  - **Earlier round vs partkit round** (10 candidates each; earlier = design-intent prompt with pitfall hints; batch time = first request to last answer, 5 requests at a time):

    | Part | Compiled | Correct topology | Within limits | Hit 16k tokens | Mean output tokens | Batch time | Winner params / IoU |
    |---|---|---|---|---|---|---|---|
    | A | 10 → 10 | 10 → 10 | – → 10 | 0 → 0 | 5086 → 5182 | 59 → 62 s | 5 / 0.989 → 5 / 0.988 |
    | B | 10 → 10 | 10 → 10 | – → 10 | 0 → 0 | 8164 → 7692 | 93 → 90 s | 7 / 0.993 → 7 / 0.987 |
    | C | 8 → 10 | 8 → 10 | – → 10 | 2 → 0 | 13424 → 11763 | 146 → 135 s | 6 / 0.984 → 6 / 0.978 |
    | D | 10 → 10 | 10 → 10 | – → 10 | 0 → 0 | 10720 → 11145 | 107 → 104 s | 7 / 0.979 → 7 / 0.987 |
    | cardboard | 3 → **0** | n/a | 2 → 0 | 7 → **10** | 15008 → 16000 | 164 → 171 s | 13 / 0.953 → none |

    Mean request time in the partkit round: 29-58 s for A-D, 82 s for the cardboard. The A-D scenes also switched from the homography to the simple scale between the rounds, so IoU differences of about 0.005 are not from the prompt.
  - **Cardboard failed completely:** all 10 candidates spent the 16000 tokens fitting numbers by hand. The notch is shown as 3 corners from least-squares intersections, which do not lie on one circle (the tip is about 2.5 mm inside the arc through the other two), and its corners get the 0.5 mm limit, so no clean arc can pass; the model noticed and kept trying centers and radii. It also could not decide between the 3.3° tilt of the least-squares top edge and the straight edge in the image. These are contradictions in the model view and limits, not in the measurements.
- [x] Arcs and a contradiction rule (candidates in `candidates_arcs/`).
  - **Arcs in the model view** (`model_view.find_arcs`): runs of 1-6 simplified edges whose contour points fit a circle (rms residual ≤ 0.3 mm, at least 45°, radius ≤ half the part width) become one arc, given as "the edge from corner i to corner j is an arc with center and radius". The simplified outline keeps corners on both sides of a rounded corner (two edges around a corner tested together). Tested: a notched plate (r 8 → 8.05), a plate with r 5 rounded corners (4 arcs, 4.74-5.34), A-E unchanged (no arcs); the cardboard's notch is now one arc (r 10.9, center just outside the edge). The deviation check measures points along each arc against the candidate's outline (0.5 mm for arcs under 20 mm across).
  - **Contradiction rule in the prompt:** if limits contradict each other or the image, write the nearest clean shape with a `# exceeds: ...` comment and decide quickly.
  - **Three rounds compared** (`compare_rounds.py`):

    | Part | Compiled (intent → partkit → arcs) | Hit 16k tokens | Mean output tokens | Batch time |
    |---|---|---|---|---|
    | A | 10 → 10 → 10 | 0 → 0 → 0 | 5086 → 5182 → 4627 | 59 → 62 → 51 s |
    | B | 10 → 10 → 10 | 0 → 0 → 0 | 8164 → 7692 → 8480 | 93 → 90 → 106 s |
    | C | 8 → 10 → 9 | 2 → 0 → 1 | 13424 → 11763 → 10765 | 146 → 135 → 110 s |
    | D | 10 → 10 → 10 | 0 → 0 → 0 | 10720 → 11145 → 9662 | 107 → 104 → 90 s |
    | cardboard (clean → partkit → arcs) | 3 → 0 → 0 | 7 → 10 → 10 | 15008 → 16000 → 16000 | 164 → 171 → 182 s |

    A-D: nothing broke; every compiled candidate has the correct topology and is within the deviation limits; winners keep their parameter counts and design-intent results. The cardboard stays a hard input (decision: no special tuning): with the notch as an arc the model no longer fits circles through corners, and it does consider the `# exceeds` comment, but it still spends all 16000 tokens on the tilted least-squares top edge and on fitting the hand-cut polygon holes into rectangles within 0.5 mm.
- [x] Safety net: if no candidate passes, the result is the baseline, marked `result_source: "fallback: measured shape, no design intent"` in the summary (the cardboard now ends this way).
- [x] **Reasoning effort.** Baseten accepts `reasoning_effort` for Muse Spark Open and validates it (`minimal, low, medium, high, xhigh, max, none`); Groq and LM Studio document xhigh as the model's default. A-D, 10 candidates each (`run_template_scenes.py ... --effort=low`):

  | Part | Level | Correct topology | Within limits | Mean output tokens | Batch time | Winner params / design intent |
  |---|---|---|---|---|---|---|
  | A | default / medium / low | 10 / 10 / 10 | 10 / 10 / 9 | 4627 / 1490 / 647 | 51 / 23 / 15 s | 5 / 5 / 6, all checks pass at every level |
  | B | default / medium / low | 10 / 10 / 10 | 10 / 10 / 10 | 8480 / 1758 / 665 | 106 / 23 / 13 s | 8 / 8 / 8, same |
  | C | default / medium / low | 9 / 10 / 10 | 9 / 10 / 10 | 10765 / 4050 / 2694 | 110 / 49 / 35 s | 6 / 7 / **11**; low loses the edge margin |
  | D | default / medium / low | 10 / 10 / 10 | 10 / 10 / 10 | 9662 / 2875 / 1508 | 90 / 34 / 20 s | 7 / 7 / 7, same |

  Medium keeps the topology and the design intent of the default at 3-6× fewer tokens and 2-5× less time; low is cheaper still but starts to lose design intent (C: 11 parameters, edge margin not kept). Two batches (C and D, once each) failed with Baseten connection errors and were re-run.
- [x] Web app skeleton, parts 1-3 (`webapp/`; run with `.venv\Scripts\python.exe -m uvicorn webapp.server:app`, open http://127.0.0.1:8000). Replays saved runs from `outputs/e2e/`, no API calls. Styles: `webapp/static/tokens.css` holds every color/size/font as a CSS variable, `app.css` only uses them (a test checks app.css has no raw colors).
  - Screen 1-2: saved run, click, thickness; card, part and holes drawn over the photo with labels; measurement table. Decoding SAM's mask text is pure Python and took about 15 s for a card, so the decoded card mask is saved as `3_mask_card.png` (pipeline runs write it too) and the analysis is cached.
  - Screen 3: candidates as server-sent events into a grid with silhouette, IoU, parameters, status and rejection reasons; the winner (or the fallback) is marked.
  - Screen 4: three.js viewer (three@0.160.0 from jsDelivr) and one slider per named numeric parameter; releasing a slider rebuilds the part. Builds go to one long-running `build_worker.py` process (CadQuery loads once; it is started when the server starts): a rebuild takes about 0.3 s instead of 8.7 s with a new process per build. Programs are still screened with `check_code`; a hanging job kills the worker and the next job starts a new one.
- [x] Web app parts 4-6: download (STL, STEP, the CadQuery program with slider values as defaults); live mode on uploaded photos (`webapp/live.py`, saved as `outputs/e2e/live-*` runs, candidates checked as they arrive, about 45 s end to end with 3 candidates); README with setup and run steps. `samples/A_light` (0.79 MB, made by `make_sample.py`; synthetic scenes only) lets a fresh clone replay the whole flow without API keys, since `outputs/` is git-ignored.
- [ ] End-to-end on real photos (`run_real_photos.py`, `e2e_pipeline.run_photo`; no ground truth, compared with the user's ruler; outputs in `outputs/real/`). Photos arrived as 1080 × 1920 compressed JPEGs (card about 430-580 px long, 0.15-0.2 mm/px). Ellipse added as a hole shape (the key's hole).
  - **Key** (ruler 57 × 22.5 mm, hole 12 × 6): outline 56.9 × 23.6 mm (−0.2% / +4.9%). Hole, all three methods call it an ellipse at 79° to the key: SAM full 11.31 × 5.87, SAM crop 11.90 × 6.17 (used), color 12.35 × 6.32. Color also found a false hole: a darker, tarnished area of the brass head read as background (solidity 0.845, so the hole check rejected color and the crop was used). Here the crop's hole is smaller than color's, unlike the synthetic scenes.
  - **Cardboard** (ruler 188 × 91 mm, holes 20 × 8 and 13 × 7): SAM full and crop split each hole into 2-4 fragments (dark hole interiors with torn fibers and shadow). Color found both holes cleanly: 20.0 × 8.6 and 13.8 × 7.5 mm, but as polygons (rectangle match 0.85-0.88, below 0.9: hand-cut corners). **Outline: homography 195.7 × 96.7 (+4.1% / +6.3%), simple card scale 191.6 × 93.6 (+1.9% / +2.9%).** The card is small in this photo (430 px) and the part is wide and far from it, so small card-corner errors get extrapolated by the homography; for the key, next to the card, both agree. The width also includes the torn edge's highest peaks.
  - **All 10 cardboard candidates spent 16000 tokens reasoning and returned no code.** The torn edge gave a 28-corner outline, and the prompt asks for both few design parameters and a match within 0.5 mm, which cannot both hold; the model went back and forth (e.g. whether the wavy edge is rotation or pixel noise) without deciding. Needs a rule for irregular edges before re-running.
  - **Blister** (stress test, ruler 70.5 × 52 mm, 4 pockets Ø23; the pockets are blind, closed by clear domes): the photo may only go to SAM, so it runs with `suggest=False` (never sent to Muse Spark Open), no candidates, and all outputs stay in `data/private/blister_run/`. Click selection worked (0.926). **Every method calls the pockets through-holes** (see the known limit under Scope). SAM full: ragged pockets, the middle one merged with the print, printed letters taken as holes (9 "holes"). SAM crop: four clean round pockets, but they touch, so they merge into one 49 × 46 mm "hole". Color (used): the four pockets separately (the middle one a clean Ø21.4 circle, the others crescents because the clear rims reflect light) plus 6 false holes from dark print (10 "holes"). Outline: homography 74.0 × 57.0 (+4.9% / +9.7%), simple scale 72.8 × 55.4 (+3.3% / +6.5%); the blister also rests on its domes, above the card's plane.
  - **Homography vs simple scale on real photos:** with a small card (430 px) and the part 1-2 card lengths away, the homography was worse in both such photos (cardboard, blister); next to the card (key) both agree. In the earlier two-card test (cards about 900 px) the homography was better.
  - **Temporary scale rule** (`e2e_pipeline.pixel_to_mm_scales`): homography only if the card's opposite edges differ by more than 2%, else the simple mean card scale; both tables are saved in `3_measurements.json` and both outlines are printed. All three real photos (tilt ≤ 0.9%) and all synthetic scenes (tilt 1.3%) now use the simple scale. Real photos, simple vs homography: cardboard 191.6 × 93.7 vs 195.7 × 96.7 (ruler 188 × 91), key 56.6 × 23.2 vs 56.9 × 23.6 (57 × 22.5), blister 72.8 × 55.4 vs 74.0 × 57.0 (70.5 × 52). Synthetic scenes lose a little: outline errors 0.3-0.6 mm with the simple scale vs 0.0-0.5 mm with the homography, hole errors 0.05-0.08 vs 0.04-0.13 mm, all under 1%.
  - **Clean design shapes allowed, with a deviation limit** (`deviation_check.py`): the prompt lets the model replace irregular (torn, hand-cut) edges with the clean shape a designer meant, but every dimension must stay within max(1 mm, 2% of that dimension) of the measurements (hole positions: 2% of the part's length); candidates that stray further are rejected, and the winner's measured and chosen values are printed side by side.
  - **Cardboard re-run (hard input: hand-cut, torn edge, hand-cut rectangular holes that measure as polygons; the rectangle threshold stays at 0.9):** 3/10 candidates returned code (7 still used all 16000 tokens), 2 passed the deviation check, 1 was rejected. Winner (IoU 0.953 against the photo mask): a clean 191.6 × 93.65 rectangle (the torn edge squared off to its outermost extent), a clean semicircular notch (r 8.6) on the short edge, and both holes as clean rectangles. Measured vs chosen: holes 19.69 × 8.45 → 18.9 × 8.2 and 13.40 × 7.23 → 13.6 × 7.3 mm (ruler 20 × 8 and 13 × 7); all deviations within the limits. The rejected candidate drew the notch with `threePointArc` and then called `polyline`, which again drops the current point and broke the outline (IoU 0.015); the deviation check caught it.
- [x] **Usage ledger** (`usage_ledger.py`): every real model call (cached answers are not calls) is appended to `<run>/usage.jsonl`; run summaries (`5_summary_*.json`, "usage") and the search screen show calls, tokens or images, seconds and estimated dollars per model. Prices: SAM $0.0025 per image (Meta docs), Muse Wonder $4 / $20 per million input / output tokens (project document), Muse Spark Open $1.25 / $4.25 (third-party listing, **unverified**, to be checked in the Baseten dashboard).
- [x] **Repair loop with Muse Wonder** (`repair.py`, inputs in `repair_inputs.py`, test `run_repair_tests.py`, outputs in `outputs/repair_tests/`). Runs when no candidate passes every check (pipeline, live mode; decided at the consultation, 2026-10-28; before that a best IoU under 0.90 also triggered it). Wonder gets the model view of the table, the part's mask and, for the best 2-3 failed candidates, code + XOR image + rejection reasons; it answers with a short diagnosis and one partkit program, which goes through the same checks. At most 2 rounds; the second round also sees the first repair. Reasoning effort medium. Shown in the verification stream as "repair round · Muse Wonder"; a passing repair is candidate R1/R2 in the grid.

  | Case | Passed | Round | Diagnosis names the fault | IoU | Wonder time | Cost |
  |---|---|---|---|---|---|---|
  | A_light, hole moved 4 mm | yes | 1 | yes ("shifted about 4 mm in u") | 0.988 | 11.5 s | $0.043 |
  | A_light, corner cut 8 mm | yes | 1 | yes ("chamfered/missing corner") | 0.988 | 9.4 s | $0.039 |
  | C, hole moved 4 mm | yes | 1 | yes ("about 4.1 mm off, not centered in the left arm") | 0.978 | 22.3 s | $0.080 |
  | C, corner cut 8 mm | yes | 1 | yes (spurious point, 7 corners instead of 6) | 0.978 | 24.6 s | $0.074 |
  | D, hole moved 4 mm | yes | 1 | yes ("shifting it ~4 mm in u") | 0.985 | 13.9 s | $0.052 |
  | D, corner cut 8 mm | yes | 1 | yes (spurious corner, 9 instead of 8) | 0.984 | 22.7 s | $0.072 |
  | Cardboard (no candidate returned code) | no | – | n/a; both diagnoses accurate (no code; arc as chords, hole too short) | 0.952, 0.953 | 84.2 s | $0.247 |

  6/7 cases (86%) produced a passing program, all in round 1; total $0.61, 189 s of Wonder time. The cardboard stays a hard input: both repairs were within 0.6-0.8 mm of passing (arc 0.82 mm off, then a corner 0.6 mm off; hole 1 rounded to 19.0 / 18.9 mm where 19.69 was measured and the ruler says 20).
- [x] **Break cues and completion with Muse Wonder** (`break_cues.py`, `completion.py`, broken parts in `parts/broken_parts.py`, test `run_broken_scenes.py`, report `outputs/e2e/broken_report.json`). Code computes the cues from the measurement table: rough edges (an edge that fits neither a line nor an arc, rms > 0.15 mm), missing material against the mirror image next to a rough edge, gaps in a mirrored hole pattern (missing hole: material there; partial hole: the outline follows part of the expected circle). No cues on intact A-E, on the saved SAM-based scenes or on the key; the cardboard's torn edges are flagged. Wonder is called only when cues exist; it sees the cues, the rectified photo, the winner's silhouette and code, and answers broken yes/no, a suggestion, a rationale and the completed program. The completion is checked with CadQuery booleans against the winner (must change something; may add material and cut holes, but remove at most 3% of the winner's volume). Edit screen: "Possible break detected · suggested by Muse Wonder" card under the sliders with Apply / Ignore; the added material is drawn orange and see-through; Apply makes the completed program the result (Undo reverts).

  | Broken part | Cues | Suggestion (Wonder) | IoU vs true design: winner → completion | Holes vs design | Wonder time / cost | Run cost (all models) |
  |---|---|---|---|---|---|---|
  | A, corner chipped | rough edge, missing material | restore the corner (the winner had modeled it as a chamfer) | 0.918 → 0.980 | 4 / 4 | 13.9 s / $0.044 | $0.21 |
  | A, broken through a hole | rough edge, partial hole | restore the corner and the fourth hole with the shared diameter and margins | 0.859 → 0.975 | 3 → 4 / 4 | 16.2 s / $0.052 | $0.25 |
  | A, hole never drilled | missing hole | add the missing hole with the existing diameter and margins | 0.968 → 0.980 | 3 → 4 / 4 | 14.3 s / $0.041 | $0.20 |
  | D, tab snapped off | rough edge | restore the tab at the measured width, new parameter tab_length | 0.784 → 0.874 | 1 / 2 | 54.8 s / $0.127 | $0.35 |

  All four suggestions were valid and moved the model toward the true design; the three A cases reach about 0.98, the ceiling set by the photo's own measurement (the intact A_light winner scores 0.989 against its design). D is only partly right: the tab is restored 3 mm too long (40.1 mm overall instead of 37) and its 6 mm hole, invisible in the broken photo, is not added. Run costs include Spark Open at its unverified price.
- [x] **Consultation decisions (2026-10-28)**, all done:
  1. Hand-cut parts: the limits stay. When the result falls back to the measured shape, the app says why in plain words: "The edges are irregular; the measured shape is shown." (rough-edge cue present) or "No candidate passed every check; the measured shape is shown."
  2. Candidates take three approaches in turn (`candidates.STYLES`: fewest parameters, feature based, symmetry first). Live mode stops the search once 3 candidates that passed every check build the same shape (`e2e_pipeline.search_settled`; requests not yet started are cancelled). The pipeline scripts still request all candidates, to keep measuring.
  3. Scale rule stays frozen. **Note: on real photos the width comes out systematically 3-5% too large** (simple scale: key +3.1%, cardboard +3.0%, blister +6.5% while resting on its domes; the lengths are −0.7% to +3.3%). To be examined with the hardware-store parts.
  4. Completion card: Wonder sorts what it adds into measured (with evidence), estimated (a question with a suggested value) and optional (a feature nothing shows, off by default, asked as a yes/no with a suggested value). The user's answers become the completed program's defaults (`6_completion/applied.py`). D_tab_broken: suggested values IoU 0.874 against the true design; answering the questions with the truth (tab 10 mm out, hole 6 mm) gives **0.974**, both holes, 37.3 mm overall (true 37).
  5. Repair runs only when no candidate passes every check (the IoU < 0.90 trigger is gone). The winner is chosen only among candidates that passed every check (deviation limits and, when the truth is known, topology).
  6. `samples/` holds `A_light_repair` (A_light with only two deliberately broken candidates; Muse Wonder repaired them in round 1: IoU 0.988, 5 parameters, $0.04) and `D_tab_broken` (completion card). Synthetic, JPEG without EXIF (checked), 0.7 MB each.
  7. Completion from the mask only vs the photo (`compare_completion_inputs.py`): same validity and identical IoU against the true design on all 4 broken parts (difference 0.000), similar cost ($0.05-0.07 per call). **The mask is now the default**; the photo no longer goes to Muse Wonder.
