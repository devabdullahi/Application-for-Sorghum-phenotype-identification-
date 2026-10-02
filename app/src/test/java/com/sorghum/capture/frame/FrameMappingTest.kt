package com.sorghum.capture.frame

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Worked examples use a 400x300 sensor image (landscape) with no extra crop, and a target
 * covering the top-left quarter of what the user sees. Rotation tells us which sensor corner
 * the user sees as "top-left".
 */
class FrameMappingTest {

    private val fullCrop = PixelRect(0, 0, 400, 300)
    private val topLeftQuarter = NormalizedRect(0f, 0f, 0.5f, 0.5f)

    @Test
    fun `no rotation maps directly onto the crop`() {
        val result = mapTargetToImagePixels(topLeftQuarter, fullCrop, rotationDegrees = 0)

        assertEquals(PixelRect(0, 0, 200, 150), result)
    }

    @Test
    fun `90 degrees - upright top-left comes from the sensor's bottom-left`() {
        // Rotating the sensor image 90° clockwise moves its bottom-left corner to the top-left.
        val result = mapTargetToImagePixels(topLeftQuarter, fullCrop, rotationDegrees = 90)

        assertEquals(PixelRect(0, 150, 200, 300), result)
    }

    @Test
    fun `180 degrees - upright top-left comes from the sensor's bottom-right`() {
        val result = mapTargetToImagePixels(topLeftQuarter, fullCrop, rotationDegrees = 180)

        assertEquals(PixelRect(200, 150, 400, 300), result)
    }

    @Test
    fun `270 degrees - upright top-left comes from the sensor's top-right`() {
        val result = mapTargetToImagePixels(topLeftQuarter, fullCrop, rotationDegrees = 270)

        assertEquals(PixelRect(200, 0, 400, 150), result)
    }

    @Test
    fun `crop offset is added to the mapped rectangle`() {
        val crop = PixelRect(left = 50, top = 20, right = 250, bottom = 120)
        val centreHalf = NormalizedRect(0.25f, 0.25f, 0.75f, 0.75f)

        val result = mapTargetToImagePixels(centreHalf, crop, rotationDegrees = 0)

        assertEquals(PixelRect(100, 45, 200, 95), result)
    }

    @Test(expected = IllegalArgumentException::class)
    fun `rejects rotations that are not a multiple of 90`() {
        mapTargetToImagePixels(topLeftQuarter, fullCrop, rotationDegrees = 45)
    }

    @Test
    fun `upright size swaps width and height for sideways rotations`() {
        assertEquals(300 to 400, uprightSize(fullCrop, 90))
        assertEquals(400 to 300, uprightSize(fullCrop, 180))
    }
}
