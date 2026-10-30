package com.sorghum.segmentation

import com.sorghum.imaging.PhotoType
import com.sorghum.imaging.Rgb
import com.sorghum.imaging.pixelImage
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class SampleDetectionTest {

    private val settings = SampleDetectionSettings()
    private val tolerance = 0.0001f

    private val whiteBoard = Rgb(230, 230, 225)
    private val leafGreen = Rgb(60, 140, 50)
    private val brownPanicle = Rgb(120, 80, 50)

    /** A [size]x[size] board with a centred square of [sample] covering the middle half of each side. */
    private fun boardWithCentredSquare(size: Int, sample: Rgb) = pixelImage(size, size) { x, y ->
        val isInside = x in size / 4 until size * 3 / 4 && y in size / 4 until size * 3 / 4
        if (isInside) sample else whiteBoard
    }

    @Test
    fun `leaf photos use the green mask`() {
        val image = boardWithCentredSquare(40, leafGreen)

        val mask = detectSampleMask(image, PhotoType.LEAF, settings)

        val greenCoverage = measureSampleCoverage(image, settings.green)
        assertEquals(greenCoverage.greenFraction, mask.sampleFraction, tolerance)
        assertEquals(0.25f, mask.sampleFraction, tolerance)
    }

    @Test
    fun `a brown panicle is invisible to the leaf detector but found by the panicle detector`() {
        val image = boardWithCentredSquare(40, brownPanicle)

        val asLeaf = detectSampleMask(image, PhotoType.LEAF, settings)
        val asPanicle = detectSampleMask(image, PhotoType.PANICLE, settings)

        assertEquals(0f, asLeaf.sampleFraction, tolerance)
        assertEquals(0.25f, asPanicle.sampleFraction, tolerance)
    }

    @Test
    fun `grain photos use the contrast mask`() {
        val image = boardWithCentredSquare(40, brownPanicle)

        val mask = detectSampleMask(image, PhotoType.GRAIN, settings)

        assertEquals(measureContrastMask(image, settings.contrast).sampleFraction, mask.sampleFraction, tolerance)
        assertEquals(0.25f, mask.sampleFraction, tolerance)
    }

    @Test
    fun `live and post-capture sizes give the same coverage for the same scene`() {
        // The same scene at the live analysis size and the quality-check size must agree, because
        // live guidance and the post-capture check share this one detector.
        for (photoType in PhotoType.entries) {
            val sample = if (photoType == PhotoType.LEAF) leafGreen else brownPanicle
            val live = detectSampleMask(boardWithCentredSquare(LIVE_ANALYSIS_LONG_SIDE_PIXELS, sample), photoType, settings)
            val postCapture = detectSampleMask(boardWithCentredSquare(640, sample), photoType, settings)

            assertEquals(live.sampleFraction, postCapture.sampleFraction, tolerance, "$photoType")
            assertEquals(live.edgeSampleFraction, postCapture.edgeSampleFraction, tolerance, "$photoType")
        }
    }

    @Test
    fun `green mask marks the same pixels that the green coverage counts`() {
        val image = pixelImage(10, 10) { x, _ -> if (x < 3) leafGreen else whiteBoard }

        val mask = measureGreenMask(image, settings.green)

        assertTrue(mask.isSampleAt(0, 5))
        assertFalse(mask.isSampleAt(3, 5))
        assertEquals(measureSampleCoverage(image, settings.green), mask.toSampleCoverage())
    }
}
