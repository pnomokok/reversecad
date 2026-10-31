# Real cardboard part: two photos vs ruler (2026-10-31)

Numbers only, from the saved live runs (`outputs/e2e/live-20261031-161042-2ab58f` = TILTED,
`outputs/e2e/live-20261031-163850-973a0e` = PARALLEL). The photos stay in `data/private/`;
nothing was re-run for this report. All values are deterministic measurements (no LLM):
the used scale's table, color hole method, outline edges from the simplified 4-corner
polygon. Ruler: user-measured, ±0.5 mm; references below are midpoints (long 106.5 mm
of 106/107, short 96.0 mm of 95–97, holes Ø6, punch pairs 80 mm centre-to-centre).

## 1. Conditions

| Photo (2026-10-31) | Card long edge | mm/px | Tilt metric | Scale used |
|---|---|---|---|---|
| TILTED (16:09) | 1593.0 px | 0.05339 | 2.72% (warns) | homography |
| PARALLEL (16:36) | 1556.0 px | 0.05480 | 1.10% (passes) | simple |

Both cards are far above the 600 px low-resolution threshold (original quality, ~3× finer
than the old 430 px messenger photos), so no resolution warning on either.

## 2. Outline edges: app vs ruler

| Photo | Edge | App mm | Ruler mm | Diff mm | Diff % |
|---|---|---|---|---|---|
| TILTED | long 1 / long 2 | 110.82 / 110.12 | 106.5 | +4.32 / +3.62 | +4.1 / +3.4 |
| | short 1 / short 2 | 100.35 / 95.93 | 96.0 | +4.35 / −0.07 | +4.5 / −0.1 |
| | bbox | 111.13 × 100.71 | 106.5 × 96.0 | +4.63 / +4.71 | +4.3 / +4.9 |
| PARALLEL | long 1 / long 2 | 105.63 / 106.18 | 106.5 | −0.87 / −0.32 | −0.8 / −0.3 |
| | short 1 / short 2 | 95.83 / 93.57 | 96.0 | −0.17 / −2.43 | −0.2 / −2.5 |
| | bbox | 106.59 × 96.06 | 106.5 × 96.0 | +0.09 / +0.06 | +0.1 / +0.1 |

The TILTED short edges differ by 4.5% left vs right (100.35 vs 95.93 mm); the homography
overestimates the whole part by ~4–5% (the part sits away from the card, so the tilt
correction extrapolates). For reference, the same photo on the simple scale reads
bbox 108.33 × 97.00 mm (+1.7 / +1.0%) — closer, but the frozen rule picks homography
above 2% tilt, and the rule is not changed by this report. PARALLEL matches the ruler
within 1% except one short edge at −2.5% (hand-cut edge; outline vertex count is 6
there vs 5 on TILTED before simplification).

## 3. Holes: app vs ruler and punch

| Photo | Hole (TL / BL / TR / BR) | App Ø mm | Ruler | Diff mm | Diff % |
|---|---|---|---|---|---|
| TILTED | TL / BL / TR / BR | 6.06 / 6.10 / 6.28 / 6.30 | 6 | +0.06 … +0.30 | +1.0 … +5.0 |
| PARALLEL | TL / BL / TR / BR | 6.09 / 6.04 / 5.97 / 5.88 | 6 | +0.09 … −0.12 | +1.5 … −2.0 |

| Photo | Top-pair centres | vs 80 mm | Bottom-pair centres | vs 80 mm |
|---|---|---|---|---|
| TILTED | 82.28 | +2.28 (+2.9%) | 82.66 | +2.66 (+3.3%) |
| PARALLEL | 79.04 | −0.96 (−1.2%) | 78.72 | −1.28 (−1.6%) |

All 8 holes measured as clean circles (solidity ≥ 0.99 both photos).

## 4. Candidates and repair (from the run logs)

TILTED, exactly as logged in `5_summary_candidates_arcs_effort_medium.json`: all 5 Muse
Spark Open candidates compiled (IoU 0.9606–0.9608) and all 5 were rejected on hole
positions (limit 0.5 mm): hole 1 off 1.124–1.246 mm, hole 2 off 2.201–2.299 mm, hole 3
off 0.863–0.984 mm, hole 4 off 2.392–2.489 mm. Muse Wonder repair round 1 passed
(IoU 0.9953, every deviation within limits, 52.7 s, $0.174): "All candidates forced a
symmetric rectangular hole pattern (and rectangular outline), but the measured holes
form an asymmetric quadrilateral and the outline corners are skewed, causing hole
errors up to 2.45 mm." Result: `repair · Muse Wonder`.

PARALLEL logged the same pattern: 5/5 rejected on hole positions (0.898–2.742 mm),
repair round 1 passed (IoU 0.9829): "the measured holes are asymmetric by up to
~2.7 mm". So the Spark failures come from the hand-punched asymmetric layout, not
from the tilt — the tilt only shifts the millimetres.

## 5. Verdict

The parallel shot measures within ~1.5% of ruler and punch on every feature but one
hand-cut edge. The tilted shot reads 3–5% large under the homography it triggered;
the new tilt warning (threshold 2%) flags exactly this photo. No measurement code or
tolerance was changed for these findings.

## 6. Break restorations vs the intact photo (deterministic check, no LLM)

BREAK1 = corner cut off, holes intact (`live-20261031-173851-7490f8`, photo 17:09);
BREAK2 = same corner cut through a hole (`live-20261031-175232-b9869e`, photo 17:50).
Each run's applied completion was built and fitted rigidly to the intact measurement
table (rotation and mirror searched, lowest RMS kept) using the holes that were never
broken: all 4 for BREAK1 (fit RMS 0.145 mm, −0.1°, no mirror), 3 for BREAK2 (fit RMS
0.711 mm, −0.0°, no mirror).

| Run | Restored extents mm | Intact mm | Diff mm (%) | Max outline dev after fit (mean) |
|---|---|---|---|---|
| BREAK1 | 106.54 × 96.53 | 106.59 × 96.06 | −0.05 / +0.47 (−0.0 / +0.5) | 1.55 mm (0.62) |
| BREAK2 | 107.52 × 97.18 | 106.59 × 96.06 | +0.93 / +1.12 (+0.9 / +1.2) | 2.13 mm (0.60) |

BREAK2's restored hole sits 6.19 mm from the intact hole's centre; its diameter 6.11
vs 5.97 mm (+0.14, +2.3%) is fine. The 6 mm miss is real, not a fitting artefact: the
intact part's own holes are hand-punched asymmetric (left |x| ≈ 41–42 mm, right ≈
37–38 mm), so mirroring the top-left hole across u = 0 cannot land on the true
top-right hole. The same asymmetry is what rejected every Spark candidate's hole
positions on the intact photo (§4).

## 7. BREAK1 restored corner is a clean rectangle

The completion used one parameter (`restored_corner_length` = 14) for an asymmetric
cut (ruler legs 15–16 and 13 mm). After Apply the built outline has 4 points, all
turns exactly 90°, and its area equals its bounding box (10284.3 mm²): a clean
rectangle with no sliver. Reason: with `chamfer` == `restored_corner_length`, the
restored point lands exactly on the corner — the intersection of the extended bottom
and right edges — and the collinear middle point merges away. The cut's asymmetry
only moves where the winner drew the break line, not the restored corner. No change
needed.

## 8. Deterministic restored-hole position on BREAK2

Same §6 alignment (3-hole fit, RMS 0.711 mm). The code tries arc fit, neighbour
alignment, then the mirror fallback:

| Method | Position mm | Centre err vs intact (36.85, 37.28) | Shown as |
|---|---|---|---|
| (a) arc fit | (37.27, 37.62), 60° of inlier circle | 0.60 mm | Measured |
| (b) aligned with neighbours | (38.74, 38.94): x from the BR-column hole, y from the TL-row hole | 2.56 mm | Estimated |
| (c) mirrored | (42.66, 39.16): Wonder's mirror of the top-left hole | 6.19 mm | Estimated |

Method (a) is chosen. Diameter is the shared 6.11 vs 5.97 mm (+0.14) under every
method. The ragged arc shows only 40° around the true centre (torn points fall outside
the band) but 60° around the fitted one — exactly the acceptance bar; the fit is
stable (neighbouring starts converge to the same centre or refuse). The mirror misses
by 6 mm because the hand-punched layout is itself asymmetric.
