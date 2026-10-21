package com.sorghum.capture.frame

import kotlin.test.assertEquals
import kotlin.test.Test
import kotlin.test.assertFailsWith

class TargetFrameTest {

    private val tolerance = 0.0001f

    @Test
    fun `frame is centred with the requested width and aspect ratio`() {
        // 80% of a 1000px-wide area is 800px; aspect 0.5 makes it 1600px tall out of 2000px.
        val rect = TargetFrame(widthFraction = 0.8f, aspectRatio = 0.5f).normalizedRectIn(1000, 2000)

        assertEquals(0.1f, rect.left, tolerance)
        assertEquals(0.9f, rect.right, tolerance)
        assertEquals(0.1f, rect.top, tolerance)
        assertEquals(0.9f, rect.bottom, tolerance)
    }

    @Test
    fun `frame that would be too tall is shrunk to fit and keeps its aspect ratio`() {
        // Requested 800x1600px in a 1000x1000 area: scaled by 1000/1600 to 500x1000px.
        val rect = TargetFrame(widthFraction = 0.8f, aspectRatio = 0.5f).normalizedRectIn(1000, 1000)

        assertEquals(0.5f, rect.right - rect.left, tolerance)
        assertEquals(1.0f, rect.bottom - rect.top, tolerance)
        assertEquals(0.25f, rect.left, tolerance)
        assertEquals(0.0f, rect.top, tolerance)
    }

    @Test
    fun `rejects a width fraction above 1`() {
        assertFailsWith<IllegalArgumentException> { TargetFrame(widthFraction = 1.2f) }
    }

    @Test
    fun `rejects an empty area`() {
        assertFailsWith<IllegalArgumentException> { TargetFrame().normalizedRectIn(0, 100) }
    }
}
