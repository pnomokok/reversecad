# ReverseCAD: consultation summary

Status on 2026-10-28. The core is complete: photo → masks → measurements → candidate programs → checks → repair → result → completion of broken parts → editable model with STL/STEP/.py export. This note lists what we decided and why, what we measured, what is still open, and what we would like advice on. Details are in `CLAUDE.md` (working notes) and `README.md`.

## What the system does

One top-down photo of a flat part next to an ID-1 card (85.60 × 53.98 mm). SAM 3.1 finds the card and the part (the user clicks the part). Deterministic code measures the outline, corners, arcs and holes in millimeters. Muse Spark Open writes 10 candidate CadQuery programs from the measurement table and the part's silhouette. Each candidate is built in a separate process, compared with the photo's mask (IoU), and checked against the measurements. If none passes, Muse Wonder repairs. If the code finds signs that the part itself is broken, Muse Wonder suggests a completion that the user can apply or ignore.

## Decisions and why

| Decision | Reason |
|---|---|
| Scale from an ID-1 card lying **next to** the part, not a coin | A planar reference with known edges; scale is exact at the card and degrades with distance (4-10% errors with the part 1-2 card lengths away) |
| The part is picked by a **click** (SAM point prompt); naming it is the fallback | Click masks had 0.988-0.992 confidence on all scenes, names 0.72-0.88; about half of the model's name suggestions found nothing |
| **Homography only if the card looks tilted** (opposite edges differ > 2%), else the simple card scale | Homography was better in the two-card test (mean error 0.48% vs 0.86%) but worse on real photos with a small card far from the part. This is a temporary rule |
| Holes measured by **color inside SAM's outline**; the cropped SAM mask is the fallback | SAM fills or fragments small holes; color was the most accurate method in every synthetic scene (0.04-0.13 mm) |
| **The language model never measures**: every number comes from the table; the model chooses structure and parameter names | Measurement accuracy is code's job; the model's job is design intent |
| The model sees a **simplified outline** (least-squares edges, arcs fitted), plus the `partkit` helper library | Raw contours with torn edges made the model loop without returning code; partkit removed the CadQuery pitfalls (cumulative `.center()`, `polyline` dropping a point) |
| **Deviation limits**: outline max(1 mm, 2%); holes and features under 20 mm: 0.5 mm | IoU barely notices holes (plate without holes: IoU 0.963), so holes and corners need their own checks |
| Reasoning effort **medium** for Spark | Same topology and design intent as the default, 3-6× fewer tokens, 2-5× faster; low started losing design intent |
| **Baseline fallback**, clearly labeled | There is always a result, but it is marked as "measured shape, no design intent" |
| **Measurement side frozen** unless an error exceeds 5% | Stop tuning thresholds on a handful of photos; changes go to the model side |
| **Repair** (Muse Wonder) when no candidate passes or the best IoU < 0.90; at most 2 rounds | 0.90 is the project's success criterion for IoU; two rounds keep cost and time bounded |
| **Completion** only when code finds break cues; Wonder interprets, code finds evidence | Wonder is not called on intact parts; the cues are measurable (rough edge, missing material against the mirror image, gap or partial hole in a hole pattern) |
| A completion is checked with **CadQuery booleans** against the winner | It may add material or cut holes but must not remove the measured part (at most 3% of its volume) |
| The UI shows **only computed values**; "fit to measurements" is kept apart from "vs ground truth" | A candidate can fit the measurements to 0.03 mm and still be 0.9% off the true part, because the measurements carry the photo's error |
| Fast SAM mask decoder, **checked bit for bit** against the library on all 73 saved masks, with the library as fallback | Decoding took about 13 s per card answer; now 1.35 s |

## Measured numbers

**Measurement (deterministic code)**
- Second ID-1 card measured with the first as reference: mean error 0.48% (max 1.44%) with the homography, 0.86% with the simple scale.
- Real brass key (ruler 57 × 22.5 mm, elliptical hole 12 × 6): outline 56.6 × 23.2 mm (−0.7% / +2.9%), hole 11.8 × 6.2 mm (−1.9% / +3.0%).
- Real hand-cut cardboard (ruler 188 × 91): simple scale 191.6 × 93.7 (+1.9% / +2.9%), homography 195.7 × 96.7 (+4.1% / +6.3%).
- Synthetic scenes, holes by color: diameters within 0.15 mm, centers within 0.7 mm.

**Candidates (Muse Spark Open)**
- Synthetic parts A-D, 10 candidates each: 100% compiled with the correct topology, IoU 0.98-0.99.
- Design intent: 5-8 named parameters instead of 15-23 for the baseline; shared hole diameter, symmetry and edge margins are kept when a dimension changes.
- Candidates differ as code but not as geometry: on these parts the table fixes every number.
- Synthetic A_light against the true part: 79.30 × 40.20 vs 80 × 40 mm (−0.9% / +0.5%), holes within 0.02 mm; fit to measurements 0.03 mm.
- The cardboard is the hard case: in the newest round no candidate returned code (all used the 16,000-token budget).

**Repair (Muse Wonder, medium effort)**: 7 cases, 6 synthetic (a hole moved 4 mm or a corner cut 8 mm on parts A, C and D) and 1 real (the cardboard).
- 6/7 repaired, all synthetic cases in round 1; every diagnosis named the injected fault.
- The cardboard failed twice by 0.6-0.8 mm (an arc, then a corner; a hole rounded to 19.0 mm where 19.69 was measured and the ruler says 20).
- Cost and time: $0.04-0.08 and 9-25 s per synthetic repair, $0.25 and 84 s for the cardboard, $0.61 in total.

**Completion (Muse Wonder)**: 4 synthetic broken parts with a known design. IoU is measured against the true design, before (the winner) and after (the completion).

| Part | Before | After |
|---|---|---|
| A, chipped corner | 0.918 | 0.980 |
| A, broken through a hole | 0.859 | 0.975 |
| A, hole never drilled | 0.968 | 0.980 |
| D, tab snapped off | 0.784 | 0.874 |

- All four suggestions were valid. About 0.98 is the ceiling set by the photo measurement itself: the intact A_light winner scores 0.989 against its design.
- D is only partly right. The tab was restored 3 mm too long, and the 6 mm hole that was in the lost tab was not invented.
- Break cues raised no false alarm on the intact parts A-E, on the saved SAM-based scenes or on the key. The cardboard's torn edges are flagged, which is correct.

**Cost and time per run**
- A synthetic broken-part run with 10 candidates and a completion: $0.20-0.35. This includes Spark Open at an unverified price of $1.25 / $4.25 per million tokens.
- A live run with 3 candidates takes about 45 s end to end.

## Open problems

1. **Few real photos.** Three real photos so far (key, cardboard, blister pack). No real broken part has been tried. The repair and completion results are almost all synthetic.
2. **Hand-cut and torn parts.** The cardboard fails at every stage by a small margin. The 0.5 mm limit for small features may be stricter than such parts can meet.
3. **Scale rule.** The tilt-based switch between homography and simple scale is temporary. Neither is best on every photo; the outline width on real photos is 2.9-4.9% too large.
4. **Little candidate variety.** Ten candidates converge to the same geometry. Parallel search may be paying for redundancy.
5. **Completion without evidence.** When the break removed information (the tab's length, a hole in the lost tab), the suggestion either guesses (3 mm too long) or omits it. The card does not yet say which parts of a suggestion are measured and which are guessed.
6. **A single top view.** Thickness is entered by the user. Blind holes and clear materials look like through-holes (blister pack). The planned side shot is not built.
7. **Demo without keys.** The repository has only one sample run (A_light) for replay. The repair and completion runs live under `outputs/` (git-ignored), so a jury without API keys cannot see them.
8. **Unverified prices and reasoning.** Spark Open's price comes from a third-party listing. Muse Wonder returns no reasoning text, only its token count.
9. **Privacy.** A completion sends the rectified photo to Muse Wonder. Every other model request after SAM sends only masks.

## Questions for the consultation

1. Should the deviation limits scale with the measured roughness of an edge, so hand-cut parts can pass, or is failing them the honest result?
2. Given the low geometric variety, should we cut the candidates from 10 to 3-5 and spend the budget on repair, or create variety on purpose (different prompts, different parameterizations)?
3. How would you choose between homography and simple scale per photo? Is there a better single rule (for example card size in pixels, or the part's distance from the card)?
4. For a completion with missing evidence: should the card ask the user for the unknown dimension (for example "tab length?") instead of letting the model guess? And should a feature that cannot be seen (the tab's hole) be offered as an optional question?
5. Is IoU ≥ 0.90 the right trigger for repair, given that IoU hardly reacts to holes? Would a combined score (IoU plus deviation pass) be better?
6. Which real broken parts are worth photographing in the remaining time to test completion honestly?
7. For the demo: should we add compact samples of a repaired run and a broken-part run so the jury can replay them without keys?
8. Is sending the photo to Muse Wonder for completion acceptable, or should completion also work from the mask only (and how much would it lose)?
9. Is a side shot (thickness, blind holes) worth building before the deadline, or should it stay a known limit?
