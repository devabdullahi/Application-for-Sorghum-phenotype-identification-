package com.sorghum.capture.quality

import com.sorghum.imaging.PixelImage
import com.sorghum.imaging.Rgb
import com.sorghum.imaging.pixelImage
import com.sorghum.imaging.uniformImage
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
        val emptyBoard = uniformImage(size, size, Rgb(150, 150, 150))

        assertEquals(RejectionReason.NO_SAMPLE, check(emptyBoard))
    }

    @Test
    fun `dark photo is rejected as too dark`() {
        val darkPhoto = image { x, y -> if (isLeaf(x, y)) Rgb(20, 60, 20) else Rgb(35, 35, 35) }

        assertEquals(RejectionReason.TOO_DARK, check(darkPhoto))
    }

    @Test
    fun `photo with a large blown-out patch is rejected for glare`() {
        val withGlare = image { x, y ->
            when {
                x < 16 && y < 16 -> Rgb(255, 255, 255)
                isLeaf(x, y) -> Rgb(60, 140, 50)
                else -> Rgb(150, 150, 150)
            }
        }

        assertEquals(RejectionReason.GLARE, check(withGlare))
    }

    @Test
    fun `photo with soft edges is rejected as blurry`() {
        // Leaf colour fades gradually across the whole width, so there are no sharp edges.
        val blurred = image { x, _ ->
            val mix = x.toFloat() / (size - 1)
            Rgb((150 - 90 * mix).toInt(), (150 - 10 * mix).toInt(), (150 - 100 * mix).toInt())
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

    private fun check(image: PixelImage) = checkPhotoQuality(image, settings)

    /** Striped leaf in the middle: many hard green/grey transitions, like leaf veins and edges. */
    private fun sharpLeafPhoto() = image { x, y -> if (isLeaf(x, y) && x % 4 < 2) Rgb(60, 140, 50) else Rgb(150, 150, 150) }

    private fun isLeaf(x: Int, y: Int) = x in 16 until 48 && y in 8 until 56

    private fun image(pixelAt: (x: Int, y: Int) -> Rgb): PixelImage = pixelImage(size, size, pixelAt)

    @Test
    fun `library photo without green is not rejected for missing sample`() {
        // Sharp grey stripes, no green at all: no sample for a board photo, fine for a library photo.
        val stripesWithoutGreen = image { x, _ -> if (x % 4 < 2) Rgb(90, 90, 90) else Rgb(170, 170, 170) }

        assertEquals(RejectionReason.NO_SAMPLE, checkPhotoQuality(stripesWithoutGreen, settings, PhotoSource.CAMERA_TARGET_FRAME))
        assertNull(checkPhotoQuality(stripesWithoutGreen, settings, PhotoSource.PHOTO_LIBRARY))
    }

    @Test
    fun `library photo with a white background is not rejected for glare`() {
        // Leaf stripes on a pure-white background: glare for a board photo, normal for a library photo.
        val onWhite = image { x, y -> if (isLeaf(x, y) && x % 4 < 2) Rgb(60, 140, 50) else Rgb(255, 255, 255) }

        assertEquals(RejectionReason.GLARE, checkPhotoQuality(onWhite, settings, PhotoSource.CAMERA_TARGET_FRAME))
        assertNull(checkPhotoQuality(onWhite, settings, PhotoSource.PHOTO_LIBRARY))
    }

    @Test
    fun `library photo is still checked for darkness and blur`() {
        val darkPhoto = image { x, _ -> if (x % 4 < 2) Rgb(10, 10, 10) else Rgb(40, 40, 40) }
        val flatPhoto = uniformImage(size, size, Rgb(150, 150, 150))

        assertEquals(RejectionReason.TOO_DARK, checkPhotoQuality(darkPhoto, settings, PhotoSource.PHOTO_LIBRARY))
        assertEquals(RejectionReason.BLURRY, checkPhotoQuality(flatPhoto, settings, PhotoSource.PHOTO_LIBRARY))
    }
}
