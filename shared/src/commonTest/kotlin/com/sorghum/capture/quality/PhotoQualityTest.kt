package com.sorghum.capture.quality

import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue
import kotlin.test.Test

/**
 * Synthetic photos: a grey board with a green "leaf" whose edges are sharp or smeared.
 * Real-photo thresholds still need tuning; these tests pin down the decision logic.
 */
class PhotoQualityTest {

    private val settings = QualitySettings()
    private val size = 64

    @Test
    fun `sharp well-lit photo with a sample is accepted`() {
        assertNull(check(sharpLeafPhoto()))
    }

    @Test
    fun `photo without green is rejected as having no sample`() {
        val emptyBoard = IntArray(size * size) { argb(150, 150, 150) }

        assertEquals(RejectionReason.NO_SAMPLE, check(emptyBoard))
    }

    @Test
    fun `dark photo is rejected as too dark`() {
        val darkPhoto = image { x, y -> if (isLeaf(x, y)) argb(20, 60, 20) else argb(35, 35, 35) }

        assertEquals(RejectionReason.TOO_DARK, check(darkPhoto))
    }

    @Test
    fun `photo with a large blown-out patch is rejected for glare`() {
        val withGlare = image { x, y ->
            when {
                x < 16 && y < 16 -> argb(255, 255, 255)
                isLeaf(x, y) -> argb(60, 140, 50)
                else -> argb(150, 150, 150)
            }
        }

        assertEquals(RejectionReason.GLARE, check(withGlare))
    }

    @Test
    fun `photo with soft edges is rejected as blurry`() {
        // Leaf colour fades gradually across the whole width, so there are no sharp edges.
        val blurred = image { x, _ ->
            val mix = x.toFloat() / (size - 1)
            argb((150 - 90 * mix).toInt(), (150 - 10 * mix).toInt(), (150 - 100 * mix).toInt())
        }

        assertEquals(RejectionReason.BLURRY, check(blurred))
    }

    @Test
    fun `laplacian variance is higher for sharp edges than for gradients`() {
        val sharp = toLuma(sharpLeafPhoto())
        val flat = IntArray(size * size) { 128 }

        assertTrue(laplacianVariance(sharp, size, size) > laplacianVariance(flat, size, size))
        assertEquals(0.0, laplacianVariance(flat, size, size), 0.0)
    }

    @Test
    fun `laplacian variance of an image without interior pixels is zero`() {
        assertEquals(0.0, laplacianVariance(IntArray(4), 2, 2), 0.0)
    }

    private fun check(pixels: IntArray) = checkPhotoQuality(pixels, size, size, settings)

    /** Striped leaf in the middle: many hard green/grey transitions, like leaf veins and edges. */
    private fun sharpLeafPhoto() = image { x, y -> if (isLeaf(x, y) && x % 4 < 2) argb(60, 140, 50) else argb(150, 150, 150) }

    private fun isLeaf(x: Int, y: Int) = x in 16 until 48 && y in 8 until 56

    private fun image(pixelAt: (x: Int, y: Int) -> Int): IntArray =
        IntArray(size * size) { index -> pixelAt(index % size, index / size) }

    private fun argb(red: Int, green: Int, blue: Int): Int =
        (0xFF shl 24) or (red shl 16) or (green shl 8) or blue
}
