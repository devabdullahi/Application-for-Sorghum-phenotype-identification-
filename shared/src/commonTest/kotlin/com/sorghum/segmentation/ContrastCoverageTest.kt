package com.sorghum.segmentation

import com.sorghum.imaging.Rgb
import com.sorghum.imaging.pixelImage
import com.sorghum.imaging.uniformImage
import kotlin.math.roundToInt
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class ContrastCoverageTest {

    private val settings = ContrastDetectionSettings()
    private val tolerance = 0.0001f

    private val whiteBoard = Rgb(230, 230, 225)
    private val greyBoard = Rgb(150, 150, 150)
    private val blackBoard = Rgb(35, 35, 35)

    private val tanPanicle = Rgb(190, 150, 100)
    private val redBrownPanicle = Rgb(140, 60, 40)
    private val creamPanicle = Rgb(230, 215, 180)
    private val leafGreen = Rgb(60, 140, 50)

    @Test
    fun `empty board has no coverage`() {
        val coverage = measureContrastCoverage(uniformImage(100, 100, whiteBoard), settings)

        assertEquals(0f, coverage.sampleFraction, tolerance)
        assertEquals(0f, coverage.edgeSampleFraction, tolerance)
    }

    @Test
    fun `red-brown panicle on a white board is found`() {
        val coverage = measureContrastCoverage(centredSquare(redBrownPanicle, on = whiteBoard), settings)

        assertEquals(0.25f, coverage.sampleFraction, tolerance)
        assertEquals(0f, coverage.edgeSampleFraction, tolerance)
    }

    @Test
    fun `tan panicle on a grey board of similar brightness is found by its colour`() {
        val coverage = measureContrastCoverage(centredSquare(tanPanicle, on = greyBoard), settings)

        assertEquals(0.25f, coverage.sampleFraction, tolerance)
    }

    @Test
    fun `pale cream panicle on a black board is found by its brightness`() {
        val coverage = measureContrastCoverage(centredSquare(creamPanicle, on = blackBoard), settings)

        assertEquals(0.25f, coverage.sampleFraction, tolerance)
    }

    @Test
    fun `green leaf is found too, because the detector only needs contrast`() {
        val coverage = measureContrastCoverage(centredSquare(leafGreen, on = whiteBoard), settings)

        assertEquals(0.25f, coverage.sampleFraction, tolerance)
    }

    @Test
    fun `lamp shading across a board is not mistaken for a sample`() {
        // The board gets 25% darker from left to right, as under a lamp at one side.
        val image = pixelImage(100, 100) { x, _ -> shadedWhiteBoard(x) }

        val coverage = measureContrastCoverage(image, settings)

        assertEquals(0f, coverage.sampleFraction, tolerance)
    }

    @Test
    fun `panicle on a shaded board is still found`() {
        val image = pixelImage(100, 100) { x, y -> if (isInCentredSquare(x, y)) tanPanicle else shadedWhiteBoard(x) }

        val coverage = measureContrastCoverage(image, settings)

        assertEquals(0.25f, coverage.sampleFraction, tolerance)
    }

    @Test
    fun `panicle crossing the left border shows up in the edge band`() {
        // Tan strip along the whole left side, 10 pixels wide.
        val image = pixelImage(100, 100) { x, _ -> if (x < 10) tanPanicle else greyBoard }

        val coverage = measureContrastCoverage(image, settings)

        // The rest of the board is not counted, so the board estimate was not pulled towards tan.
        assertEquals(0.1f, coverage.sampleFraction, tolerance)
        assertTrue(coverage.edgeSampleFraction > 0.2f)
    }

    @Test
    fun `board colour is the edge median, not pulled towards a sample touching the border`() {
        val image = pixelImage(100, 100) { x, _ -> if (x < 10) tanPanicle else greyBoard }

        assertEquals(BoardColour(150, 150, 150), estimateBoardColour(image, edgeBand = 3))
    }

    @Test
    fun `very dark pixels are compared by brightness only`() {
        // Very different chromaticity, same brightness, but both too dark for colour to mean anything.
        val darkBoard = BoardColour(15, 15, 15)

        assertFalse(isSamplePixel(25, 10, 10, darkBoard, settings))
    }

    @Test
    fun `chroma distance of a warm pixel from a neutral board`() {
        // Chromatic coordinates (0.4, 0.333, 0.267) against (0.333, 0.333, 0.333).
        assertEquals(0.0943f, chromaDistance(120, 100, 80, BoardColour(100, 100, 100)), tolerance)
    }

    @Test
    fun `brightness difference threshold is inclusive`() {
        val board = BoardColour(100, 100, 100)
        // 153 / 765 = 0.2 of the full range.
        val atTwentyPercent = ContrastDetectionSettings(minBrightnessDifference = 0.2f)

        assertFalse(isSamplePixel(150, 150, 151, board, atTwentyPercent), "151 / 765 is just below")
        assertTrue(isSamplePixel(151, 151, 151, board, atTwentyPercent), "153 / 765 is exactly at")
        assertTrue(isSamplePixel(151, 151, 152, board, atTwentyPercent), "154 / 765 is just above")
    }

    @Test
    fun `chroma distance threshold is inclusive`() {
        val board = BoardColour(100, 100, 100)
        // Same brightness as the board, so only colour can make it sample.
        val distance = chromaDistance(110, 100, 90, board)

        assertFalse(isSamplePixel(110, 100, 90, board, ContrastDetectionSettings(minChromaDistance = distance + 0.001f)))
        assertTrue(isSamplePixel(110, 100, 90, board, ContrastDetectionSettings(minChromaDistance = distance)))
        assertTrue(isSamplePixel(110, 100, 90, board, ContrastDetectionSettings(minChromaDistance = distance - 0.001f)))
    }

    @Test
    fun `invalid settings are refused`() {
        assertFailsWith<IllegalArgumentException> { ContrastDetectionSettings(minChromaDistance = 0f) }
        assertFailsWith<IllegalArgumentException> { ContrastDetectionSettings(minBrightnessDifference = 0f) }
        assertFailsWith<IllegalArgumentException> { ContrastDetectionSettings(minBrightnessDifference = 1.1f) }
        assertFailsWith<IllegalArgumentException> { ContrastDetectionSettings(minBrightnessSum = -1) }
        assertFailsWith<IllegalArgumentException> { ContrastDetectionSettings(minBrightnessSum = 766) }
        assertFailsWith<IllegalArgumentException> { ContrastDetectionSettings(edgeBandFraction = 0f) }
        assertFailsWith<IllegalArgumentException> { ContrastDetectionSettings(edgeBandFraction = 0.5f) }
    }

    /** A 100x100 board with a 50x50 sample in the middle: a quarter of the area, away from the edge. */
    private fun centredSquare(sample: Rgb, on: Rgb) =
        pixelImage(100, 100) { x, y -> if (isInCentredSquare(x, y)) sample else on }

    private fun isInCentredSquare(x: Int, y: Int) = x in 25 until 75 && y in 25 until 75

    /** White board darkened linearly from 100% at the left edge to 75% at the right edge. */
    private fun shadedWhiteBoard(x: Int): Rgb {
        val light = 1f - 0.25f * x / 99f
        return Rgb(
            (whiteBoard.red * light).roundToInt(),
            (whiteBoard.green * light).roundToInt(),
            (whiteBoard.blue * light).roundToInt(),
        )
    }
}
