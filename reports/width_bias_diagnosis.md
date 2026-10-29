# Width bias on real photos: diagnosis (2026-10-29)

Read-only diagnosis; no measurement code was changed. Inputs: the saved SAM answers for `key`, `carton` and `blister` (photos stay in `data/private/`), measured with the pipeline's own functions. All three runs used the **simple scale** (card tilt below the 2% rule). Ruler reading uncertainty is about ±0.5 mm.

## 1. Ruler vs measured (simple scale, chosen hole method)

| Photo | Feature (long / short axis) | Ruler mm | Measured mm | Error mm | Error % |
|---|---|---|---|---|---|
| key (SAM crop) | outline | 57 / 22.5 | 56.61 / 23.16 | −0.39 / +0.66 | −0.7 / **+2.9** |
| | hole (ellipse) | 12 / 6 | 11.77 / 6.18 | −0.23 / +0.18 | −1.9 / +3.0 |
| carton (color) | outline | 188 / 91 | 191.61 / 93.65 | +3.61 / +2.65 | +1.9 / **+2.9** |
| | hole 1 | 20 / 8 | 19.69 / 8.45 | −0.31 / +0.45 | −1.5 / +5.6 |
| | hole 2 | 13 / 7 | 13.40 / 7.23 | +0.40 / +0.23 | +3.1 / +3.3 |
| blister (color) | outline | 70.5 / 52 | 72.80 / 55.39 | +2.30 / +3.39 | +3.3 / **+6.5** |
| | pockets 1-4 (Ø23) | 23 / 23 | 22.80 / 21.10, 24.61 / 22.91, 20.88 (circle), 22.66 / 20.84 | −2.2 … +1.6 | −9.4 … +7.0 |

The blister pockets are clear domes with reflecting rims (crescent-shaped masks); they are not a usable size test.

## 2. Card alone, and 3. part orientation

| Photo | Card px, long / short (line fit) | px/mm long / short | Long vs short | Opposite edges L-R / T-B | Part axis vs card long edge |
|---|---|---|---|---|---|
| key | 581.0 / 363.3 | 6.787 / 6.730 | +0.84% | −0.86% / +0.08% | 13.3° |
| carton | 425.8 / 268.5 | 4.975 / 4.975 | 0.00% | +0.39% / +0.41% | 0.8° |
| blister | 429.9 / 270.8 | 5.022 / 5.016 | +0.12% | +0.24% / +0.62% | 3.8° |

With the card's `minAreaRect` (what the simple scale uses) the long/short difference is +0.17%, −0.32% and −0.12%. The rectangle is 0.2-1.4% larger than the line-fitted card, so at 270-430 px the card's own edge definition is uncertain by up to about 1%. In all three photos the part's width runs along the card's short edge (the image's vertical), so "width" and "one image direction" are confounded.

## 4. Hypotheses

**B, anisotropic scale: not supported.** (a) The card shows no direction-dependent scale beyond 0.84%, with mixed signs. (b) The per-axis card scale changes the outline width by at most 0.15 mm (key 23.18, carton 93.50, blister 55.36 mm). (c) The key's hole has its long axis at 78.5° to the key, so it runs along the stretched direction, yet it comes out **−1.9%** where B predicts +2.9%. (d) The typical extents (median per column / row, deskewed, instead of the outline's maximum) have nearly the **same percentage error on both axes**: carton 190.3 / 92.4 mm (+1.2% / +1.5%), blister crop mask 72.0 / 53.0 mm (+2.1% / +1.9%).

**A, edge/shadow bias: only partly.** The mask boundaries sit on the strongest image edge within ±1 px (≈0.2 mm) on every side, and no clear shadows are visible. Holes do not shrink consistently (carton: 3 of 4 hole axes grow). The width-specific excess does come from the boundary, but from local outliers on the long edges rather than a uniform offset:
- carton: the torn long edge's peaks add 1.3 mm (max 93.65 vs median 92.4 mm);
- blister: the full SAM mask spills about 3 px (0.6 mm) past the bottom edge (under the part, which rests on its domes) and is 2.0 mm wider than the crop mask (55.39 vs 53.41).

A common, roughly isotropic +1-2% (carton, blister) sits underneath and fits neither A nor B. Likely sources: the part raised above the card's plane (blister on its domes) and the ~1% card-edge uncertainty. A fixed mm excess also reads as a larger % on the shorter axis, which is part of why the error "shows up in the width".

**Key: not conclusive.** The width is +0.66 mm (4.5 px) at every measuring direction (minimum over all angles 23.29 mm, full mask), while the length is −0.39 mm. Both are near the ruler's ±0.5 mm.

**Would another scale remove it? No.** Width error with simple / per-axis / full homography: key +2.9 / +3.0 / +4.3%, carton +2.9 / +2.7 / +6.3%, blister +6.5 / +6.5 / +9.7%. The homography makes every width worse; the per-axis scale changes nothing.

**Verdict:** the numbers reject B and support a boundary effect (A) only in a modified form: outliers on the long edges plus an isotropic 1-2% magnification. Only the blister (a stress-test part resting on its domes, full SAM outline) exceeds 5%. Nothing points at the frozen scale rule itself. Suggested checks before any change: caliper-measured flat parts lying directly on the table, photos at original resolution (card ≥ 900 px), and median extents logged next to the maximum extent.
