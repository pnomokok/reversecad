# Synthetic appearance test: the frozen pipeline on non-plate looks (2026-11-03)

**SYNTHETIC — renders, not photos of real materials.** Sixteen scenes rendered from
template parts A (4-hole plate), C (flat L), D (tabbed part) and E (rectangular hole +
slot), each in four painted appearances. Nothing was re-run: every scene ran once, as listed.

## Method

Same settings as `run_appearance_scenes.py` (mirrors `run_template_scenes.py`): 10 Muse Spark
Open candidates at medium reasoning effort, simulated click for SAM (name search only if
the click fails), Muse Wonder repair only if no candidate passes every check. The pipeline
(measurement, prompts, checks) was not touched for this test.

Appearances (`synthetic_appearance.py`) are plain painted approximations — no claim of
physical realism: **brushed** (light grey, directional streaks, one soft specular band),
**black_plastic** (near-black with faint mottling, low contrast to the background),
**wood** (warm base with wavy grain lines), **glossy_white** (bright white, one soft
highlight blob beside each hole). Card, background, tilt, blur and noise are shared with the
default scene — only the part surface differs (pinned by `tests/test_synthetic_appearance.py`).

## Per-scene results against the true design

Errors are signed where a direction exists. "Holes" is found/true with the used method's
shapes; Ø/center errors are the max over matched holes. IoU-design compares the result
program against the true design; IoU-mask is the pipeline's own score against the SAM mask.

| Scene | SAM part (source, conf) | Holes | L err % | W err % | Hole Ø err mm | Hole ctr err mm | Method | Result | Repair | IoU design | IoU mask | Cost $ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A_brushed | yes, click 0.992 | 4/4 circles | −0.61 | +1.27 | 0.06 | 0.66 | color | candidate | no | 0.9806 | 0.9895 | 0.1156 |
| A_black_plastic | yes, click 0.992 | 4/4 circles | −0.70 | +1.23 | 0.06 | 0.67 | color | candidate | no | 0.9805 | 0.9881 | 0.1099 |
| A_wood | yes, click 0.992 | 4/4 circles | −0.69 | +1.38 | 0.07 | 0.57 | color | candidate | no | 0.9806 | 0.9898 | 0.1157 |
| A_glossy_white | yes, click 0.992 | 4/4 circles | −0.65 | +1.30 | 0.05 | 0.65 | color | candidate | no | 0.9789 | 0.9889 | 0.1125 |
| C_brushed | yes, click 0.988 | 2/2 circles | −0.39 | +1.32 | 0.07 | 0.39 | color | candidate | no | 0.9768 | 0.9836 | 0.2074 |
| C_black_plastic | yes, click 0.988 | 2/2 circles | −0.49 | +1.02 | 0.07 | 0.30 | color | candidate | no | 0.9777 | 0.9827 | 0.2362 |
| C_wood | yes, click 0.992 | 2/2 circles | −0.47 | +1.18 | 0.05 | 0.29 | color | candidate | no | 0.9762 | 0.9830 | 0.2780 |
| C_glossy_white | yes, click 0.992 | 2/2 circles | −0.36 | +1.30 | 0.05 | 0.40 | color | candidate | no | 0.9755 | 0.9843 | 0.2110 |
| D_brushed | yes, click 0.988 | 2/2 circles | −0.80 | +1.24 | 0.05 | 0.23 | color | candidate | no | 0.9726 | 0.9866 | 0.1673 |
| D_black_plastic | yes, click 0.984 | 2/2 circles | −0.68 | +1.11 | 0.04 | 0.23 | color | candidate | no | 0.9802 | 0.9846 | 0.1636 |
| D_wood | yes, click 0.988 | 2/2 circles | −0.78 | +1.08 | 0.05 | 0.24 | color | candidate | no | 0.9791 | 0.9882 | 0.1545 |
| D_glossy_white | yes, click 0.988 | 2/2 circles | −0.76 | +1.19 | 0.04 | 0.21 | color | candidate | no | 0.9755 | 0.9884 | 0.1653 |
| E_brushed | yes, click 0.988 | 2/2 rect+slot | −0.76 | +1.18 | 0.04 | 0.27 | color | candidate | no | 0.9797 | 0.9855 | 0.1144 |
| E_black_plastic | yes, click 0.988 | 2/2 rect+slot | −0.67 | +1.10 | 0.07 | 0.25 | color | candidate | no | 0.9810 | 0.9867 | 0.1153 |
| E_wood | yes, click 0.984 | 2/2 rect+slot | −0.70 | +1.18 | 0.07 | 0.26 | color | candidate | no | 0.9785 | 0.9862 | 0.1086 |
| E_glossy_white | yes, click 0.992 | 2/2 rect+slot | −0.63 | +1.12 | 0.04 | 0.27 | color | candidate | no | 0.9797 | 0.9853 | 0.1068 |

Totals: 16/16 design found by candidate (160/160 compiled, 160/160 correct topology), no
repair, no fallback. Cost $2.4821 (Spark Open at its unverified price; SAM $0.12 of it).

## Summary

**What held: everything.** SAM found every part by click at 0.984–0.992 — the same
confidence as the light-plate scenes — including the near-black part on the dark
background. The color hole method returned exact counts and shapes in all 16 scenes
(E's rectangle and slot correct 4/4; mask IoU vs truth 0.989–0.993) and was selected
every time. Outline errors stayed under 1.5% (−0.8…−0.4% length, +1.0…+1.4% width),
hole diameters within 0.074 mm, centers within 0.67 mm, result-vs-design IoU 0.973–0.981.

**What broke: nothing in the pipeline's own verdicts.** Two observations, both
appearance-independent: SAM's own hole masks still fragment or fill (0–13 holes on the
SAM methods across scenes, e.g. 13 fragments on E_black_plastic's crop, 0 on E_wood's),
which the hole check routed around exactly as designed; and A's hole centers read
~0.6 mm off in all four appearances (C/D/E ≤ 0.4 mm) — a scene-geometry effect of that
part's distant holes under the simple card scale, not an appearance effect.

**Why:** the only stages that ever see the textured photo are SAM segmentation and the
color hole finder; the candidates see the binary mask plus the measurement table, so
they are appearance-invariant by construction. SAM segments by region, not material, and
the color method re-samples the part and background tones per photo — both held for these
four looks.

**Caveats (read before generalizing):** flat painted renders only — no real specular
glare washing out a hole, no cast shadows, no texture relief, no knots or brushed-groove
depth; the black part still kept ~20 gray levels of contrast against the background; the
gloss highlights never covered a hole; intact parts only (no breaks). Real materials need
real photos (see `reports/real_parts.md`). Runs live in `outputs/e2e/A_*` etc. (git-ignored,
shown as "Synthetic" in the local Parts gallery); rerun with
`.venv\Scripts\python.exe run_appearance_scenes.py`.
