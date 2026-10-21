package com.sorghum.imaging

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertSame

class ImageResizeTest {

    @Test
    fun `centre square of a wide image drops equal margins left and right`() {
        // 4x2 image: columns 0..3 have red 0, 10, 20, 30.
        val wide = pixelImage(4, 2) { x, _ -> Rgb(x * 10, 0, 0) }

        val square = cropCenterSquare(wide)

        assertEquals(2, square.width)
        assertEquals(2, square.height)
        assertEquals(10, square.redAt(0))
        assertEquals(20, square.redAt(1))
    }

    @Test
    fun `centre square of a tall image drops margins top and bottom`() {
        val tall = pixelImage(2, 4) { _, y -> Rgb(0, y * 10, 0) }

        val square = cropCenterSquare(tall)

        assertEquals(10, square.greenAt(0))
        assertEquals(20, square.greenAt(2))
    }

    @Test
    fun `resizing to the same size returns the image unchanged`() {
        val image = uniformImage(3, 3, Rgb(1, 2, 3))

        assertSame(image, resizeBilinear(image, 3, 3))
    }

    @Test
    fun `uniform colour stays uniform after shrinking`() {
        val image = uniformImage(100, 60, Rgb(60, 140, 50))

        val small = resizeBilinear(image, 24, 24)

        for (index in 0 until small.pixelCount) {
            assertEquals(listOf(60, 140, 50), listOf(small.redAt(index), small.greenAt(index), small.blueAt(index)))
        }
    }

    @Test
    fun `halving weights neighbours with the stretched triangle filter like Pillow`() {
        // Row 0, 200, 0, 200 halved: the filter spans 3 source pixels with weights
        // 0.75, 0.75, 0.25 (normalised by 1.75), so 150/1.75 = 86 and 200/1.75 = 114.
        // A plain 2x2 average would give 100 for both; Pillow, used in training, does not.
        val stripes = pixelImage(4, 1) { x, _ -> if (x % 2 == 0) Rgb(0, 0, 0) else Rgb(200, 200, 200) }

        val half = resizeBilinear(stripes, 2, 1)

        assertEquals(86, half.redAt(0))
        assertEquals(114, half.redAt(1))
    }

    @Test
    fun `strong shrink is antialiased instead of skipping pixels`() {
        // A single bright column in 8 dark ones: point sampling could miss it entirely.
        val image = pixelImage(9, 1) { x, _ -> if (x == 4) Rgb(225, 225, 225) else Rgb(0, 0, 0) }

        val onePixel = resizeBilinear(image, 1, 1)

        // The triangle filter spans the whole row, so the bright column contributes.
        assertEquals(true, onePixel.redAt(0) in 1..224)
    }
}
