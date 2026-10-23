package com.sorghum.capture.platform

import com.sorghum.imaging.PixelImage
import org.junit.Assert.assertEquals
import org.junit.Test

class PixelImageConversionTest {

    @Test
    fun `2x2 ARGB image keeps channel order and pixel positions`() {
        // Row 0: red, green. Row 1: blue, a mix with bytes above 127. Alpha varies to show it is dropped.
        val argbPixels = intArrayOf(
            argb(alpha = 0xFF, red = 255, green = 0, blue = 0),
            argb(alpha = 0x80, red = 0, green = 255, blue = 0),
            argb(alpha = 0x00, red = 0, green = 0, blue = 255),
            argb(alpha = 0xFF, red = 200, green = 150, blue = 10),
        )

        val image = argbToPixelImage(argbPixels, width = 2, height = 2)

        assertEquals(2, image.width)
        assertEquals(2, image.height)
        assertEquals(listOf(255, 0, 0), rgbAt(image, 0))
        assertEquals(listOf(0, 255, 0), rgbAt(image, 1))
        assertEquals(listOf(0, 0, 255), rgbAt(image, 2))
        assertEquals(listOf(200, 150, 10), rgbAt(image, 3))
    }

    @Test(expected = IllegalArgumentException::class)
    fun `rejects pixel arrays that do not match the size`() {
        argbToPixelImage(IntArray(3), width = 2, height = 2)
    }

    private fun rgbAt(image: PixelImage, pixelIndex: Int) =
        listOf(image.redAt(pixelIndex), image.greenAt(pixelIndex), image.blueAt(pixelIndex))

    private fun argb(alpha: Int, red: Int, green: Int, blue: Int): Int =
        (alpha shl 24) or (red shl 16) or (green shl 8) or blue
}
