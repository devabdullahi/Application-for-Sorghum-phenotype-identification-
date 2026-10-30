package com.sorghum.calibration

import com.sorghum.imaging.NormalizedRect
import com.sorghum.imaging.PixelImage
import com.sorghum.imaging.Rgb
import com.sorghum.imaging.uniformImage
import kotlin.math.abs
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertIs
import kotlin.test.assertTrue

class ColourCardCalibrationTest {

    private val wholeImage = NormalizedRect(0f, 0f, 1f, 1f)
    private val defaultCard = SyntheticCard()
    private val defaultPhoto = renderCardPhoto(240, 200, defaultCard)

    private fun calibrate(
        photo: PixelImage = defaultPhoto,
        cardRegion: NormalizedRect = wholeImage,
        settings: ColourCardSettings = ColourCardSettings(),
    ) = calibrateWithColourCard(photo, cardRegion, settings)

    private fun calibrated(result: ColourCardCalibration) = assertIs<ColourCardCalibration.Calibrated>(result)

    private fun notFoundReason(result: ColourCardCalibration) = assertIs<ColourCardCalibration.NotFound>(result).reason

    // --- Found card ---------------------------------------------------------------------------

    @Test
    fun `finds the card and recovers reference colours under a cast`() {
        val result = calibrated(calibrate())

        assertEquals(ColorCheckerClassicMini.PATCH_COUNT, result.card.patches.size)
        for ((index, patch) in result.card.patches.withIndex()) {
            val reference = ColorCheckerClassicMini.referenceLinearRgb[index]
            // Patches outside the sRGB gamut were clipped by the "camera"; skip their exact check.
            if (!reference.isInUnitCube()) continue
            val corrected = result.correction.correct(patch.meanSrgb.toLinear())
            assertEquals(reference.red, corrected.red, 0.01, "patch $index red")
            assertEquals(reference.green, corrected.green, 0.01, "patch $index green")
            assertEquals(reference.blue, corrected.blue, 0.01, "patch $index blue")
        }
        assertTrue(result.correction.meanDeltaE < 1.5f, "mean delta E ${result.correction.meanDeltaE}")
    }

    @Test
    fun `pixels per mm comes from the patch pitch`() {
        val result = calibrated(calibrate())

        val expected = defaultCard.pitchXPx / ColorCheckerClassicMini.PATCH_PITCH_MM
        assertEquals(expected, result.pixelsPerMm, expected * 0.01f)
        assertEquals(defaultCard.pitchXPx.toFloat(), result.card.patchPitchPx, 0.25f)
    }

    @Test
    fun `sample rects sit inside the right patches`() {
        val result = calibrated(calibrate())

        for (row in 0 until 4) {
            for (column in 0 until 6) {
                val rect = result.card.patches[row * 6 + column].sampleRect
                val (expectedX, expectedY) = defaultCard.cellCentre(column, row)
                assertEquals(expectedX, (rect.left + rect.right) / 2.0, 1.5, "patch ($column, $row) x")
                assertEquals(expectedY, (rect.top + rect.bottom) / 2.0, 1.5, "patch ($column, $row) y")
                // The sample stays clear of the 2 px half-gap around the 24 px cell.
                assertTrue(rect.width in 4..18 && rect.height in 4..18, "patch ($column, $row) rect $rect")
            }
        }
    }

    @Test
    fun `finds the card turned upside down`() {
        assertRotationFound(180, darkSkinCell = Pair(5, 3), widthPx = 240, heightPx = 200)
    }

    @Test
    fun `finds the card turned a quarter clockwise`() {
        assertRotationFound(90, darkSkinCell = Pair(3, 0), widthPx = 200, heightPx = 240)
    }

    @Test
    fun `finds the card turned a quarter anticlockwise`() {
        assertRotationFound(270, darkSkinCell = Pair(0, 5), widthPx = 200, heightPx = 240)
    }

    private fun assertRotationFound(rotationDegrees: Int, darkSkinCell: Pair<Int, Int>, widthPx: Int, heightPx: Int) {
        val card = SyntheticCard(rotationDegrees = rotationDegrees)

        val result = calibrated(calibrate(renderCardPhoto(widthPx, heightPx, card)))

        assertEquals(rotationDegrees, result.card.rotationDegrees)
        val darkSkin = result.card.patches[0].sampleRect
        val (expectedX, expectedY) = card.cellCentre(darkSkinCell.first, darkSkinCell.second)
        assertEquals(expectedX, (darkSkin.left + darkSkin.right) / 2.0, 1.5)
        assertEquals(expectedY, (darkSkin.top + darkSkin.bottom) / 2.0, 1.5)
        assertTrue(result.correction.meanDeltaE < 1.5f)
    }

    @Test
    fun `finds the card inside its hint region and ignores a leaf outside it`() {
        val card = SyntheticCard(leftPx = 250, topPx = 30)
        val leafStrip = { x: Int, _: Int -> if (x in 40..120) LEAF else null }
        val photo = renderCardPhoto(440, 200, card, occluder = leafStrip)
        val hint = NormalizedRect(0.5f, 0f, 1f, 1f)

        val result = calibrated(calibrate(photo, hint))

        val (expectedX, expectedY) = card.cellCentre(0, 0)
        val darkSkin = result.card.patches[0].sampleRect
        assertEquals(expectedX, (darkSkin.left + darkSkin.right) / 2.0, 1.5)
        assertEquals(expectedY, (darkSkin.top + darkSkin.bottom) / 2.0, 1.5)
    }

    // --- Card not found -------------------------------------------------------------------------

    @Test
    fun `empty board has no card`() {
        assertEquals(CardNotFoundReason.NO_GRID, notFoundReason(calibrate(uniformImage(240, 200, BOARD))))
    }

    @Test
    fun `card cut off by the hint region is not found`() {
        // The hint covers only the left half of the card, so a 6 x 4 grid cannot fit.
        val hint = NormalizedRect(0f, 0f, 0.4f, 1f)

        val result = calibrate(cardRegion = hint)

        assertIs<ColourCardCalibration.NotFound>(result)
    }

    @Test
    fun `leaf over part of a patch makes it non-uniform`() {
        // Cover the left half of patch (2, 1) with leaf.
        val (centreX, centreY) = defaultCard.cellCentre(2, 1)
        val occluder = { x: Int, y: Int ->
            if (x in (centreX - 12).toInt()..centreX.toInt() && abs(y - centreY) < 12) LEAF else null
        }

        val result = calibrate(renderCardPhoto(240, 200, defaultCard, occluder = occluder))

        assertEquals(CardNotFoundReason.PATCH_NOT_UNIFORM, notFoundReason(result))
    }

    @Test
    fun `occluder as bright as the patch but a different hue is still caught`() {
        // Same luma as the moderate red patch at (2, 1), but green: invisible to a brightness check.
        val patch = castPatchColour(referenceIndexAt(2, 1, 0))
        val sameBrightnessGreen = Rgb(patch.red - 60, patch.green + 31, patch.blue - 4)
        val (centreX, centreY) = defaultCard.cellCentre(2, 1)
        val occluder = { x: Int, y: Int ->
            if (x in (centreX - 12).toInt()..centreX.toInt() && abs(y - centreY) < 12) sameBrightnessGreen else null
        }

        val result = calibrate(renderCardPhoto(240, 200, defaultCard, occluder = occluder))

        assertEquals(CardNotFoundReason.PATCH_NOT_UNIFORM, notFoundReason(result))
    }

    @Test
    fun `leaf over a whole row of patches spoils the colour fit`() {
        // A uniform leaf covers the top patch row, gaps included, so every patch is still
        // uniform but six of them have the wrong colour.
        val (_, rowCentreY) = defaultCard.cellCentre(0, 0)
        val occluder = { x: Int, y: Int ->
            if (x in 36..179 && abs(y - rowCentreY) < 12) LEAF else null
        }

        val result = calibrate(renderCardPhoto(240, 200, defaultCard, occluder = occluder))

        assertEquals(CardNotFoundReason.POOR_COLOUR_FIT, notFoundReason(result))
    }

    // --- Threshold boundaries -------------------------------------------------------------------

    @Test
    fun `grid edge contrast at and either side of the minimum`() {
        val contrast = calibrated(calibrate()).card.gridEdgeContrast

        assertIs<ColourCardCalibration.Calibrated>(calibrate(settings = ColourCardSettings(minGridEdgeContrast = contrast)))
        assertIs<ColourCardCalibration.Calibrated>(calibrate(settings = ColourCardSettings(minGridEdgeContrast = contrast * 0.999f)))
        assertEquals(
            CardNotFoundReason.NO_GRID,
            notFoundReason(calibrate(settings = ColourCardSettings(minGridEdgeContrast = contrast * 1.001f))),
        )
    }

    @Test
    fun `patch uniformity at and either side of the maximum`() {
        val noisyPhoto = renderCardPhoto(240, 200, defaultCard, noiseLevels = 4)
        val worstStdDev = calibrated(calibrate(noisyPhoto)).card.patches.maxOf { it.channelStdDev }
        assertTrue(worstStdDev > 3f, "noise should show, was $worstStdDev")

        assertIs<ColourCardCalibration.Calibrated>(
            calibrate(noisyPhoto, settings = ColourCardSettings(maxPatchChannelStdDev = worstStdDev)),
        )
        assertIs<ColourCardCalibration.Calibrated>(
            calibrate(noisyPhoto, settings = ColourCardSettings(maxPatchChannelStdDev = worstStdDev * 1.001f)),
        )
        assertEquals(
            CardNotFoundReason.PATCH_NOT_UNIFORM,
            notFoundReason(calibrate(noisyPhoto, settings = ColourCardSettings(maxPatchChannelStdDev = worstStdDev * 0.999f))),
        )
    }

    @Test
    fun `colour fit residual at and either side of the maximum`() {
        val residual = calibrated(calibrate()).correction.meanDeltaE
        assertTrue(residual > 0f, "clipping and 8-bit rounding leave some residual")

        assertIs<ColourCardCalibration.Calibrated>(calibrate(settings = ColourCardSettings(maxMeanDeltaE = residual)))
        assertIs<ColourCardCalibration.Calibrated>(calibrate(settings = ColourCardSettings(maxMeanDeltaE = residual * 1.001f)))
        assertEquals(
            CardNotFoundReason.POOR_COLOUR_FIT,
            notFoundReason(calibrate(settings = ColourCardSettings(maxMeanDeltaE = residual * 0.999f))),
        )
    }

    @Test
    fun `colour fit gate fails closed on a non-finite residual`() {
        val settings = ColourCardSettings(maxMeanDeltaE = 6f)

        assertTrue(isColourFitAcceptable(6f, settings))
        assertTrue(isColourFitAcceptable(5.99f, settings))
        assertFalse(isColourFitAcceptable(6.01f, settings))
        assertFalse(isColourFitAcceptable(Float.NaN, settings))
        assertFalse(isColourFitAcceptable(Float.POSITIVE_INFINITY, settings))
    }

    @Test
    fun `pitch mismatch at and either side of the maximum`() {
        // Patches 24 px wide and 27 px tall: the card is seen at a slant.
        val slanted = renderCardPhoto(240, 220, SyntheticCard(pitchYPx = 27))
        val mismatch = calibrated(calibrate(slanted, settings = ColourCardSettings(maxPitchMismatch = 0.5f))).card.pitchMismatch
        assertEquals(3f / 25.5f, mismatch, 0.01f)

        assertIs<ColourCardCalibration.Calibrated>(calibrate(slanted, settings = ColourCardSettings(maxPitchMismatch = mismatch)))
        assertIs<ColourCardCalibration.Calibrated>(
            calibrate(slanted, settings = ColourCardSettings(maxPitchMismatch = mismatch * 1.001f)),
        )
        assertEquals(
            CardNotFoundReason.UNEVEN_GRID,
            notFoundReason(calibrate(slanted, settings = ColourCardSettings(maxPitchMismatch = mismatch * 0.999f))),
        )
    }

    @Test
    fun `minimum patch pitch at and either side of the card's pitch`() {
        val small = renderCardPhoto(160, 120, SyntheticCard(pitchXPx = 12, pitchYPx = 12, gapPx = 2, frameMarginPx = 4, leftPx = 20, topPx = 20))
        val pitch = calibrated(calibrate(small, settings = ColourCardSettings(minPatchPitchPx = 6f))).card.patchPitchPx
        assertEquals(12f, pitch, 0.25f)

        assertIs<ColourCardCalibration.Calibrated>(calibrate(small, settings = ColourCardSettings(minPatchPitchPx = pitch)))
        assertIs<ColourCardCalibration.Calibrated>(calibrate(small, settings = ColourCardSettings(minPatchPitchPx = pitch * 0.999f)))
        // Just above: the true grid is refused. The other layout's (wrong) grid may then get
        // further before failing, so only "not found" is certain, not which reason.
        assertIs<ColourCardCalibration.NotFound>(calibrate(small, settings = ColourCardSettings(minPatchPitchPx = pitch * 1.001f)))
    }

    @Test
    fun `minimum grid fraction of the hint separates a card from a small texture`() {
        // 240 x 160 px hint; a 6 x 4 grid with 20 px pitch spans half of it both ways. The
        // refined pitch is sub-pixel, so the exact boundary is not hand-checkable; test either
        // side of it with a clear margin instead.
        fun photoWithPitch(pitchPx: Int) = renderCardPhoto(240, 160, SyntheticCard(pitchXPx = pitchPx, pitchYPx = pitchPx, leftPx = 20, topPx = 20))
        val settings = ColourCardSettings(minGridFractionOfHint = 0.5f)

        assertIs<ColourCardCalibration.Calibrated>(calibrate(photoWithPitch(21), settings = settings))
        assertIs<ColourCardCalibration.NotFound>(calibrate(photoWithPitch(18), settings = settings))
    }

    // --- Settings validation ------------------------------------------------------------------

    @Test
    fun `settings reject out-of-range values`() {
        assertFailsWith<IllegalArgumentException> { ColourCardSettings(minGridFractionOfHint = 0f) }
        assertFailsWith<IllegalArgumentException> { ColourCardSettings(minGridFractionOfHint = 1.1f) }
        assertFailsWith<IllegalArgumentException> { ColourCardSettings(gridBoundaryWindowFraction = 0.5f) }
        assertFailsWith<IllegalArgumentException> { ColourCardSettings(sampleFractionOfPitch = 0f) }
        assertFailsWith<IllegalArgumentException> { ColourCardSettings(sampleFractionOfPitch = 1.1f) }
        assertFailsWith<IllegalArgumentException> { ColourCardSettings(minPatchPitchPx = 2.9f) }
        assertFailsWith<IllegalArgumentException> { ColourCardSettings(minGridEdgeContrast = -1f) }
        assertFailsWith<IllegalArgumentException> { ColourCardSettings(maxPitchMismatch = -0.1f) }
        assertFailsWith<IllegalArgumentException> { ColourCardSettings(maxPatchChannelStdDev = -1f) }
        assertFailsWith<IllegalArgumentException> { ColourCardSettings(maxMeanDeltaE = 0f) }
    }
}

private fun LinearRgb.isInUnitCube(): Boolean = listOf(red, green, blue).all { it in 0.0..1.0 }
