package com.sorghum.capture.guidance

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.abs

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
        val radians = Math.toRadians(10.0)
        val tilt = DeviceTilt.fromGravity(0f, (gravity * Math.sin(radians)).toFloat(), (gravity * Math.cos(radians)).toFloat())

        assertEquals(10f, tilt.pitchDegrees, tolerance)
        assertEquals(0f, tilt.rollDegrees, tolerance)
    }

    @Test
    fun `raising the right edge gives positive roll`() {
        val radians = Math.toRadians(8.0)
        val tilt = DeviceTilt.fromGravity((gravity * Math.sin(radians)).toFloat(), 0f, (gravity * Math.cos(radians)).toFloat())

        assertEquals(8f, tilt.rollDegrees, tolerance)
    }

    @Test
    fun `phone lying face down is not mistaken for level`() {
        val tilt = DeviceTilt.fromGravity(0f, 0f, -gravity)

        assertTrue(abs(tilt.pitchDegrees) > 90f)
        assertTrue(abs(tilt.rollDegrees) > 90f)
    }
}
