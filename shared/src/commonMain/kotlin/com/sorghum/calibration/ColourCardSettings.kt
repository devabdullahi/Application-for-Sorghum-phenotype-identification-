package com.sorghum.calibration

/**
 * Thresholds and search tolerances for finding the colour card and trusting its fit.
 *
 * All values are initial guesses, tune on real photos of the board taken with the target
 * phones. Pixel values refer to the image passed to [calibrateWithColourCard].
 *
 * @param minGridFractionOfHint the patch grid must span at least this fraction of the card
 *   region along each axis. The capture layout draws the card slot to fit the card, so a grid
 *   much smaller than the slot is a regular texture (board weave, grain rows), not the card.
 *   Loose enough (0.3) that a card placed off-centre in a generous slot is still found.
 * @param gridBoundaryWindowFraction half-width, as a fraction of the patch pitch, of the band
 *   around each grid line where patch edges are expected. It must cover half the black gap
 *   between patches (about 0.06 of the pitch on the Mini) plus blur and a degree or two of card
 *   rotation, and must stay below 0.5 so patch interiors remain.
 * @param sampleFractionOfPitch side of the square sampled at each patch centre, as a fraction
 *   of the pitch. Patches fill about 85% of the pitch; sampling only the middle half keeps
 *   samples off the gaps despite small grid errors, blur and rotation.
 * @param minPatchPitchPx smallest accepted patch pitch (mean of both axes), in pixels; also the
 *   lower end of the grid search. Below about 6 px the sampled square is only a few pixels and
 *   edge blur reaches its centre, so the card is too small in the photo to trust.
 * @param minGridEdgeContrast how much more colour change, in 0–255 levels, the grid lines must
 *   carry than equally wide bands inside the patches (see [GridAxis.edgeContrast]). A blank
 *   board scores about 0; a card whose gaps step 40+ levels against the patches scores well
 *   above 10 even when it spans only half the region.
 * @param maxPitchMismatch largest allowed relative difference between the horizontal and
 *   vertical pitch, |x - y| / mean. Patches are square, so a larger difference means the card
 *   is seen at a slant (the level guidance should prevent this) or the grid is wrong; either way
 *   the mm scale would differ by direction.
 * @param maxPatchChannelStdDev largest allowed standard deviation of any colour channel (0–255)
 *   inside one patch sample (see [CardPatch.channelStdDev]). Sensor noise gives a few levels; a leaf, finger, shadow edge or glare spot over the
 *   patch gives far more, and its mean colour would then mislead the fit.
 * @param maxMeanDeltaE largest allowed mean CIE76 ΔE between corrected and reference patches.
 *   An affine fit on a good phone photo typically leaves a few ΔE (sensor non-linearity, pigment
 *   ageing); much more means the card is misread or partly covered. 6 is a first guess.
 */
data class ColourCardSettings(
    val minGridFractionOfHint: Float = 0.3f,
    val gridBoundaryWindowFraction: Float = 0.2f,
    val sampleFractionOfPitch: Float = 0.5f,
    val minPatchPitchPx: Float = 6f,
    val minGridEdgeContrast: Float = 10f,
    val maxPitchMismatch: Float = 0.1f,
    val maxPatchChannelStdDev: Float = 12f,
    val maxMeanDeltaE: Float = 6f,
) {
    init {
        require(minGridFractionOfHint > 0f && minGridFractionOfHint <= 1f) {
            "minGridFractionOfHint must be within (0, 1], was $minGridFractionOfHint"
        }
        require(gridBoundaryWindowFraction > 0f && gridBoundaryWindowFraction < 0.5f) {
            "gridBoundaryWindowFraction must be within (0, 0.5), was $gridBoundaryWindowFraction"
        }
        require(sampleFractionOfPitch > 0f && sampleFractionOfPitch <= 1f) {
            "sampleFractionOfPitch must be within (0, 1], was $sampleFractionOfPitch"
        }
        // At 3 px a pitch still has one interior pixel between two one-pixel boundary bands.
        require(minPatchPitchPx >= 3f) { "minPatchPitchPx must be at least 3, was $minPatchPitchPx" }
        require(minGridEdgeContrast >= 0f) { "minGridEdgeContrast must not be negative, was $minGridEdgeContrast" }
        require(maxPitchMismatch >= 0f) { "maxPitchMismatch must not be negative, was $maxPitchMismatch" }
        require(maxPatchChannelStdDev >= 0f) { "maxPatchChannelStdDev must not be negative, was $maxPatchChannelStdDev" }
        require(maxMeanDeltaE > 0f) { "maxMeanDeltaE must be positive, was $maxMeanDeltaE" }
    }
}
