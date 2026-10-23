# ADR-0008: Colour card and calibration method

Status: Proposed (ASSUMPTION — confirm with the product owner) · Date: 2026-10-23

## Context
Measured colour traits (midrib colour, glume colour, grain colour) need colours that do not depend on the phone or the light. Seed size needs a mm scale. ARCHITECTURE.md §3.2 gives both jobs to `calibration` ("port PlantCV method") and §4.3 says a photo without a usable card is rejected. Risk R5 (corrected phone colour may still not match descriptor states) stays open and is measured later on reference samples.

The card must sit on the photo board next to the sample, be sold with published reference values, and be cheap enough for field teams.

## Options
1. **Calibrite (formerly X-Rite) ColorChecker Classic Mini.** 24 patches, 4 x 6, the same patches as the full Classic. Target 63.5 x 108 mm, colour chip area 57 x 86 mm (X-Rite spec sheet). Fits beside a leaf section or grain sample on a phone-photo board.
2. **ColorChecker Classic (full size).** Same patches, 279 x 216 mm. Too large for a board photographed from phone distance with the sample.
3. **ColorChecker Passport Photo 2.** Same 24 patches in a 125 x 90 mm folding case with extra targets. Costs more; the case hinge and extra targets complicate detection.
4. **A home-printed chart.** Free, but printer and paper vary, so reference values would have to be measured per print with a spectrophotometer we do not have.

Fit method (PlantCV `transform` module, read 2026-10-23):
- `affine_color_correction`: per output channel, least squares (Moore-Penrose pseudo-inverse) on the design matrix [R G B 1], i.e. a 3x4 affine transform, on gamma-encoded values / 255.
- `calc_transformation_matrix`: a 9-term polynomial (R, G, B, squares, cubes) without offset.

## Decision
- **Card: ColorChecker Classic Mini** (option 1), post-November 2014 formulation.
- **Reference values:** L\*a\*b\* (D50) from X-Rite (2016), "New color specifications for ColorChecker SG and Classic Charts", as tabulated in colour-science (`DATA_COLORCHECKER24_AFTER_NOV2014_CIE_LAB`). They are stored once in `ColorCheckerClassicMini.referenceLabD50`; linear sRGB targets are derived in code (Bradford D50 -> D65, IEC 61966-2-1 matrix, Lindbloom's published matrices). The Wikipedia sRGB table is not used: it is the pre-2014 pigment set.
- **Fit:** PlantCV's affine model (3x4, least squares on [R G B 1]), but **in linear sRGB**, not on gamma-encoded values. Camera white balance, exposure and channel cross-talk are linear in linear light, so a 3x4 matrix can undo them there; on encoded values it cannot. The offset absorbs flare and black level. The polynomial model was rejected: 24 patches give too few points for a 9-term fit to stay stable outside the card's colours.
- **Fit quality:** mean CIE76 ΔE (D50) between corrected and reference patches. Above `ColourCardSettings.maxMeanDeltaE` (6, initial guess) the photo is rejected.
- **Detection:** the card lies in a fixed slot on the board. The capture layout passes that slot as a `NormalizedRect`; `calibration` finds the regular 4 x 6 grid of colour edges inside it with two 1-D searches, samples the middle of each patch, rejects non-uniform patches, and tries the card's four 90° orientations, keeping the one with the lowest fit residual. No orientation mark is needed.
- **Scale:** pixels per mm = measured patch pitch / `ColorCheckerClassicMini.PATCH_PITCH_MM` (14.3 mm, from the 57 x 86 mm chip area / 4 x 6 patches).

## Consequences
- Every board needs a Classic Mini in a marked slot (one card per team).
- Colours inside `shared/` after this step are `correctedLinearRgb` floats 0..1, as ARCHITECTURE.md §3.3 requires.
- Not-found photos are rejected with a reason: no grid, uneven grid (card tilted), non-uniform patch (covered, glare), or poor colour fit.
- Detection assumes the card is roughly square to the photo and inside its slot. A card at an arbitrary angle, or anywhere on the board, would need a quadrilateral detector; we add one only if field photos show the slot is impractical.
- Pre-2014 cards differ from the reference by a few ΔE. Teams must use a current card.

## ASSUMPTION — confirm
- The Classic Mini is acceptable to field teams (cost, availability), and a card on every board is acceptable (also listed in ARCHITECTURE.md §9).
- `PATCH_PITCH_MM = 14.3` is derived from the published chip area, not measured. Measure the team's cards with a ruler (centre of patch 1 to centre of patch 6, divide by 5) before trusting any mm trait.
- The capture layout can reserve a card slot on the board and pass it to `calibration`.
- All `ColourCardSettings` thresholds are initial guesses until tuned on real board photos.
