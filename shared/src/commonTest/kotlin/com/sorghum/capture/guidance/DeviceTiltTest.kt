package com.sorghum.capture.guidance

import kotlin.test.assertEquals
import kotlin.test.assertTrue
import kotlin.test.Test
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.sin

class DeviceTiltTest {

    private val gravity = 9.81f
    private val tolerance = 0.01f

    @Test
    fun `phone lying flat screen up is level`() {
        val tilt = DeviceTilt.fromGravity(0f, 0f, gravity)

        assertEquals(0f, tilt.pitchDegrees, tolerance)
        assertEquals(0f, tilt.rollDegrees, tolerance)
    }

    @Test
    fun `raising the top edge gives positive pitch`() {
        // Top edge raised 10°: part of gravity now reads along +y.
        val radians = 10.0 * PI / 180
        val tilt = DeviceTilt.fromGravity(0f, (gravity * sin(radians)).toFloat(), (gravity * cos(radians)).toFloat())

        assertEquals(10f, tilt.pitchDegrees, tolerance)
        assertEquals(0f, tilt.rollDegrees, tolerance)
    }

    @Test
    fun `raising the right edge gives positive roll`() {
        val radians = 8.0 * PI / 180
        val tilt = DeviceTilt.fromGravity((gravity * sin(radians)).toFloat(), 0f, (gravity * cos(radians)).toFloat())

        assertEquals(8f, tilt.rollDegrees, tolerance)
    }

    @Test
    fun `phone lying face down is not mistaken for level`() {
        val tilt = DeviceTilt.fromGravity(0f, 0f, -gravity)

        assertTrue(abs(tilt.pitchDegrees) > 90f)
        assertTrue(abs(tilt.rollDegrees) > 90f)
    }
}
