package com.sorghum.capture.sample

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class GreenCoverageTest {

    private val settings = GreenDetectionSettings()
    private val tolerance = 0.0001f

    private val leafGreen = argb(60, 140, 50)
    private val whiteBoard = argb(230, 230, 225)
    private val brownBoard = argb(120, 90, 60)
    private val darkGreenNoise = argb(5, 20, 5)

    // Excess green (2*120 - 100 - 80) / 300 = 0.2: halfway between the 0.1 threshold and 0.3.
    private val dullGreen = argb(100, 120, 80)

    @Test
    fun `leaf green is classified as plant`() {
        assertTrue(isPlantPixel(leafGreen, settings))
    }

    @Test
    fun `white and brown boards are not plant`() {
        assertFalse(isPlantPixel(whiteBoard, settings))
        assertFalse(isPlantPixel(brownBoard, settings))
    }

    @Test
    fun `very dark pixels are ignored even if greenish`() {
        assertFalse(isPlantPixel(darkGreenNoise, settings))
    }

    @Test
    fun `empty board has no coverage`() {
        val coverage = measureSampleCoverage(IntArray(100 * 100) { whiteBoard }, 100, 100, settings)

        assertEquals(0f, coverage.greenFraction, tolerance)
        assertEquals(0f, coverage.edgeGreenFraction, tolerance)
    }

    @Test
    fun `sample in the middle is covered but does not touch the edge`() {
        // Green square from 25 to 75 on a 100x100 white board: a quarter of the area.
        val pixels = image(100, 100) { x, y -> if (x in 25 until 75 && y in 25 until 75) leafGreen else whiteBoard }

        val coverage = measureSampleCoverage(pixels, 100, 100, settings)

        assertEquals(0.25f, coverage.greenFraction, tolerance)
        assertEquals(0f, coverage.edgeGreenFraction, tolerance)
    }

    @Test
    fun `sample crossing the left border shows up in the edge band`() {
        // Green strip along the whole left side, 10 pixels wide.
        val pixels = image(100, 100) { x, _ -> if (x < 10) leafGreen else whiteBoard }

        val coverage = measureSampleCoverage(pixels, 100, 100, settings)

        assertEquals(0.1f, coverage.greenFraction, tolerance)
        assertTrue(coverage.edgeGreenFraction > 0.2f)
    }

    @Test
    fun `tiny regions still get a one-pixel edge band`() {
        val coverage = measureSampleCoverage(IntArray(4) { leafGreen }, 2, 2, settings)

        assertEquals(1f, coverage.edgeGreenFraction, tolerance)
    }

    @Test
    fun `clearly green leaf has full confidence`() {
        val coverage = measureSampleCoverage(IntArray(100) { leafGreen }, 10, 10, settings)

        assertEquals(1f, coverage.greenConfidence, tolerance)
    }

    @Test
    fun `dull green halfway past the threshold has half confidence`() {
        val coverage = measureSampleCoverage(IntArray(100) { dullGreen }, 10, 10, settings)

        assertEquals(1f, coverage.greenFraction, tolerance)
        assertEquals(0.5f, coverage.greenConfidence, tolerance)
    }

    @Test
    fun `confidence averages over green pixels only, not the board`() {
        // Left half clear leaf, right quarter dull green, rest white board.
        val pixels = image(100, 100) { x, _ ->
            when {
                x < 50 -> leafGreen
                x < 75 -> dullGreen
                else -> whiteBoard
            }
        }

        val coverage = measureSampleCoverage(pixels, 100, 100, settings)

        // (50 * 1.0 + 25 * 0.5) / 75 green columns.
        assertEquals(0.8333f, coverage.greenConfidence, tolerance)
    }

    @Test
    fun `no green pixels means zero confidence`() {
        val coverage = measureSampleCoverage(IntArray(100) { whiteBoard }, 10, 10, settings)

        assertEquals(0f, coverage.greenConfidence, tolerance)
    }

    @Test(expected = IllegalArgumentException::class)
    fun `full-confidence level must be above the threshold`() {
        GreenDetectionSettings(minExcessGreen = 0.2f, fullConfidenceExcessGreen = 0.2f)
    }

    @Test(expected = IllegalArgumentException::class)
    fun `rejects pixel arrays that do not match the size`() {
        measureSampleCoverage(IntArray(10), 4, 4, settings)
    }

    private fun image(width: Int, height: Int, pixelAt: (x: Int, y: Int) -> Int): IntArray =
        IntArray(width * height) { index -> pixelAt(index % width, index / width) }

    private fun argb(red: Int, green: Int, blue: Int): Int =
        (0xFF shl 24) or (red shl 16) or (green shl 8) or blue
}
