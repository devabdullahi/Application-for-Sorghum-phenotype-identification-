package com.sorghum.capture.sample

import com.sorghum.imaging.Rgb
import com.sorghum.imaging.pixelImage
import com.sorghum.imaging.uniformImage
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import kotlin.test.Test
import kotlin.test.assertFailsWith

class GreenCoverageTest {

    private val settings = GreenDetectionSettings()
    private val tolerance = 0.0001f

    private val leafGreen = Rgb(60, 140, 50)
    private val whiteBoard = Rgb(230, 230, 225)
    private val brownBoard = Rgb(120, 90, 60)
    private val darkGreenNoise = Rgb(5, 20, 5)

    // Excess green (2*120 - 100 - 80) / 300 = 0.2: halfway between the 0.1 threshold and 0.3.
    private val dullGreen = Rgb(100, 120, 80)

    @Test
    fun `leaf green is classified as plant`() {
        assertTrue(isPlant(leafGreen))
    }

    @Test
    fun `white and brown boards are not plant`() {
        assertFalse(isPlant(whiteBoard))
        assertFalse(isPlant(brownBoard))
    }

    @Test
    fun `very dark pixels are ignored even if greenish`() {
        assertFalse(isPlant(darkGreenNoise))
    }

    @Test
    fun `empty board has no coverage`() {
        val coverage = measureSampleCoverage(uniformImage(100, 100, whiteBoard), settings)

        assertEquals(0f, coverage.greenFraction, tolerance)
        assertEquals(0f, coverage.edgeGreenFraction, tolerance)
    }

    @Test
    fun `sample in the middle is covered but does not touch the edge`() {
        // Green square from 25 to 75 on a 100x100 white board: a quarter of the area.
        val image = pixelImage(100, 100) { x, y -> if (x in 25 until 75 && y in 25 until 75) leafGreen else whiteBoard }

        val coverage = measureSampleCoverage(image, settings)

        assertEquals(0.25f, coverage.greenFraction, tolerance)
        assertEquals(0f, coverage.edgeGreenFraction, tolerance)
    }

    @Test
    fun `sample crossing the left border shows up in the edge band`() {
        // Green strip along the whole left side, 10 pixels wide.
        val image = pixelImage(100, 100) { x, _ -> if (x < 10) leafGreen else whiteBoard }

        val coverage = measureSampleCoverage(image, settings)

        assertEquals(0.1f, coverage.greenFraction, tolerance)
        assertTrue(coverage.edgeGreenFraction > 0.2f)
    }

    @Test
    fun `tiny regions still get a one-pixel edge band`() {
        val coverage = measureSampleCoverage(uniformImage(2, 2, leafGreen), settings)

        assertEquals(1f, coverage.edgeGreenFraction, tolerance)
    }

    @Test
    fun `clearly green leaf has full confidence`() {
        val coverage = measureSampleCoverage(uniformImage(10, 10, leafGreen), settings)

        assertEquals(1f, coverage.greenConfidence, tolerance)
    }

    @Test
    fun `dull green halfway past the threshold has half confidence`() {
        val coverage = measureSampleCoverage(uniformImage(10, 10, dullGreen), settings)

        assertEquals(1f, coverage.greenFraction, tolerance)
        assertEquals(0.5f, coverage.greenConfidence, tolerance)
    }

    @Test
    fun `confidence averages over green pixels only and not the board`() {
        // Left half clear leaf, right quarter dull green, rest white board.
        val image = pixelImage(100, 100) { x, _ ->
            when {
                x < 50 -> leafGreen
                x < 75 -> dullGreen
                else -> whiteBoard
            }
        }

        val coverage = measureSampleCoverage(image, settings)

        // (50 * 1.0 + 25 * 0.5) / 75 green columns.
        assertEquals(0.8333f, coverage.greenConfidence, tolerance)
    }

    @Test
    fun `no green pixels means zero confidence`() {
        val coverage = measureSampleCoverage(uniformImage(10, 10, whiteBoard), settings)

        assertEquals(0f, coverage.greenConfidence, tolerance)
    }

    @Test
    fun `full-confidence level must be above the threshold`() {
        assertFailsWith<IllegalArgumentException> { GreenDetectionSettings(minExcessGreen = 0.2f, fullConfidenceExcessGreen = 0.2f) }
    }

    private fun isPlant(colour: Rgb) = isPlantPixel(colour.red, colour.green, colour.blue, settings)
}
