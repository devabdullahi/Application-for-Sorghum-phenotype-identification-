package com.sorghum.segmentation

import com.sorghum.imaging.Rgb
import com.sorghum.imaging.pixelImage
import com.sorghum.imaging.uniformImage
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class ContrastMaskTest {

    private val settings = ContrastMaskSettings()
    private val tolerance = 0.0001f

    private val lightBoard = Rgb(220, 215, 205)
    private val darkBoard = Rgb(40, 40, 45)
    private val greyBoard = Rgb(100, 100, 100)
    private val darkPanicle = Rgb(70, 45, 30)
    private val lightGrain = Rgb(230, 200, 150)

    @Test
    fun `board only has no sample`() {
        val mask = measureContrastMask(uniformImage(100, 100, lightBoard), settings)

        assertEquals(0f, mask.sampleFraction, tolerance)
        assertEquals(0f, mask.edgeSampleFraction, tolerance)
        assertEquals(0f, mask.sampleConfidence, tolerance)
    }

    @Test
    fun `slightly noisy board has no sample`() {
        // Sensor noise of +-10 per channel is far below the colour-distance threshold.
        val image = pixelImage(100, 100) { x, y ->
            val noise = if ((x + y) % 2 == 0) 10 else -10
            Rgb(lightBoard.red + noise, lightBoard.green + noise, lightBoard.blue + noise)
        }

        val mask = measureContrastMask(image, settings)

        assertEquals(0f, mask.sampleFraction, tolerance)
    }

    @Test
    fun `dark panicle on a light board is found`() {
        // 40x40 panicle in the middle of a 100x100 board: 16% of the area, clear of the edges.
        val image = pixelImage(100, 100) { x, y -> if (x in 30 until 70 && y in 30 until 70) darkPanicle else lightBoard }

        val mask = measureContrastMask(image, settings)

        assertEquals(0.16f, mask.sampleFraction, tolerance)
        assertEquals(0f, mask.edgeSampleFraction, tolerance)
        assertEquals(1f, mask.sampleConfidence, tolerance)
        assertTrue(mask.isSampleAt(50, 50))
        assertFalse(mask.isSampleAt(10, 10))
    }

    @Test
    fun `light grain on a dark board is found`() {
        // Three 10x10 kernels on a 100x100 dark board: 3% of the area.
        val kernelCorners = listOf(20 to 20, 50 to 40, 70 to 70)
        val image = pixelImage(100, 100) { x, y ->
            val isKernel = kernelCorners.any { (left, top) -> x in left until left + 10 && y in top until top + 10 }
            if (isKernel) lightGrain else darkBoard
        }

        val mask = measureContrastMask(image, settings)

        assertEquals(0.03f, mask.sampleFraction, tolerance)
        assertEquals(0f, mask.edgeSampleFraction, tolerance)
        assertTrue(mask.isSampleAt(55, 45))
        assertFalse(mask.isSampleAt(40, 40))
    }

    @Test
    fun `sample touching the edge shows up in the edge band`() {
        // Panicle runs off the left side: columns 0-19, rows 30-69. It covers less than half of
        // the border, so the board colour is still estimated from the board.
        val image = pixelImage(100, 100) { x, y -> if (x < 20 && y in 30 until 70) darkPanicle else lightBoard }

        val mask = measureContrastMask(image, settings)

        assertEquals(0.08f, mask.sampleFraction, tolerance)
        assertTrue(mask.edgeSampleFraction > 0f)
        assertTrue(mask.isSampleAt(0, 50))
    }

    @Test
    fun `board colour is the per-channel median of the border band`() {
        val image = pixelImage(100, 100) { x, y -> if (x < 20 && y in 30 until 70) darkPanicle else lightBoard }

        assertEquals(BoardColour(lightBoard.red, lightBoard.green, lightBoard.blue), estimateBoardColour(image, settings))
    }

    @Test
    fun `colour distance just above the threshold is sample`() {
        assertTrue(isSampleAtDistance(settings.minColourDistance.toInt() + 1))
    }

    @Test
    fun `colour distance exactly at the threshold is sample`() {
        assertTrue(isSampleAtDistance(settings.minColourDistance.toInt()))
    }

    @Test
    fun `colour distance just below the threshold is board`() {
        assertFalse(isSampleAtDistance(settings.minColourDistance.toInt() - 1))
    }

    @Test
    fun `confidence rises from zero at the threshold to one at full distance`() {
        val atThreshold = confidenceAtDistance(settings.minColourDistance.toInt())
        val halfway = confidenceAtDistance(((settings.minColourDistance + settings.fullConfidenceColourDistance) / 2).toInt())
        val atFull = confidenceAtDistance(settings.fullConfidenceColourDistance.toInt())

        assertEquals(0f, atThreshold, tolerance)
        assertEquals(0.5f, halfway, tolerance)
        assertEquals(1f, atFull, tolerance)
    }

    @Test
    fun `full confidence distance must be above the threshold`() {
        assertFailsWith<IllegalArgumentException> {
            ContrastMaskSettings(minColourDistance = 80f, fullConfidenceColourDistance = 80f)
        }
    }

    @Test
    fun `threshold must be a positive distance within the RGB cube`() {
        assertFailsWith<IllegalArgumentException> { ContrastMaskSettings(minColourDistance = 0f) }
        assertFailsWith<IllegalArgumentException> {
            ContrastMaskSettings(minColourDistance = 500f, fullConfidenceColourDistance = 600f)
        }
    }

    @Test
    fun `band fractions must be within zero and one half`() {
        assertFailsWith<IllegalArgumentException> { ContrastMaskSettings(boardBandFraction = 0f) }
        assertFailsWith<IllegalArgumentException> { ContrastMaskSettings(boardBandFraction = 0.5f) }
        assertFailsWith<IllegalArgumentException> { ContrastMaskSettings(edgeBandFraction = 0f) }
        assertFailsWith<IllegalArgumentException> { ContrastMaskSettings(edgeBandFraction = 0.5f) }
    }

    /**
     * A grey board with a 20x20 block in the middle whose red channel is [distance] higher,
     * so the block's colour distance from the board is exactly [distance].
     */
    private fun boardWithBlockAtDistance(distance: Int) = pixelImage(100, 100) { x, y ->
        if (x in 40 until 60 && y in 40 until 60) Rgb(greyBoard.red + distance, greyBoard.green, greyBoard.blue) else greyBoard
    }

    private fun isSampleAtDistance(distance: Int): Boolean =
        measureContrastMask(boardWithBlockAtDistance(distance), settings).isSampleAt(50, 50)

    private fun confidenceAtDistance(distance: Int): Float =
        measureContrastMask(boardWithBlockAtDistance(distance), settings).sampleConfidence
}
