package com.sorghum.capture.guidance

import kotlin.math.PI
import kotlin.math.atan2

/**
 * How far the phone is from lying flat (screen up, camera pointing straight down).
 *
 * @param pitchDegrees positive when the top edge of the phone is higher than the bottom edge.
 * @param rollDegrees positive when the right edge of the phone is higher than the left edge.
 */
data class DeviceTilt(val pitchDegrees: Float, val rollDegrees: Float) {

    companion object {
        /**
         * Converts a gravity reading (Android's TYPE_GRAVITY or TYPE_ACCELEROMETER, in the
         * device's own axes) into tilt.
         *
         * Android reports the reaction to gravity, so an axis pointing upward reads positive:
         * lying flat screen-up gives (0, 0, +9.8). A positive y therefore means the top edge
         * is raised, and a positive x means the right edge is raised.
         *
         * atan2 against z (rather than against the full horizontal magnitude) is used on
         * purpose: a phone lying face-down reads z < 0 and produces angles near 180°, so it is
         * never mistaken for level.
         */
        fun fromGravity(x: Float, y: Float, z: Float): DeviceTilt {
            val pitch = (atan2(y, z).toDouble() * RADIANS_TO_DEGREES).toFloat()
            val roll = (atan2(x, z).toDouble() * RADIANS_TO_DEGREES).toFloat()
            return DeviceTilt(pitchDegrees = pitch, rollDegrees = roll)
        }

        // Same factor java.lang.Math.toDegrees uses, so results match the JVM version exactly.
        private const val RADIANS_TO_DEGREES = 180.0 / PI
    }
}
