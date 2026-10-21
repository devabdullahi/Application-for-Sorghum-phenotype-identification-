package com.sorghum.imaging

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class PixelImageTest {

    @Test
    fun `channels are read in RGB order and row by row`() {
        // 2x1 image with a different value in every channel, so any mix-up shows.
        val image = PixelImage(2, 1, byteArrayOf(10, 20, 30, 40, 50, 60))

        assertEquals(10, image.redAt(0))
        assertEquals(20, image.greenAt(0))
        assertEquals(30, image.blueAt(0))
        assertEquals(40, image.redAt(1))
        assertEquals(50, image.greenAt(1))
        assertEquals(60, image.blueAt(1))
    }

    @Test
    fun `channel values above 127 are read as unsigned`() {
        val image = PixelImage(1, 1, byteArrayOf(200.toByte(), 255.toByte(), 128.toByte()))

        assertEquals(200, image.redAt(0))
        assertEquals(255, image.greenAt(0))
        assertEquals(128, image.blueAt(0))
    }

    @Test
    fun `rejects byte arrays that do not match the size`() {
        assertFailsWith<IllegalArgumentException> { PixelImage(2, 2, ByteArray(11)) }
    }

    @Test
    fun `rejects an empty image`() {
        assertFailsWith<IllegalArgumentException> { PixelImage(0, 4, ByteArray(0)) }
    }
}
