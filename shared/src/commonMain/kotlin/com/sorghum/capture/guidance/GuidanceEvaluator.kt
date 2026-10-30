package com.sorghum.capture.guidance

import com.sorghum.segmentation.SampleCoverage
import kotlin.math.abs

/**
 * Thresholds for live guidance. The defaults are starting points; tune them on real devices.
 *
 * @param maxTiltDegrees how far from flat the phone may be in either direction. 5° keeps the
 *   scale across the photo consistent while still being easy to hold by hand.
 * @param minSampleFraction fraction of the frame that must be green before we treat a sample
 *   as present. Small, so thin leaves still count.
 * @param maxEdgeGreenFraction fraction of the frame's edge band that may be green. Above this,
 *   the sample crosses the frame edge and is cut off.
 */
data class GuidanceSettings(
    val maxTiltDegrees: Float = 5f,
    val minSampleFraction: Float = 0.02f,
    val maxEdgeGreenFraction: Float = 0.05f,
) {
    init {
        require(maxTiltDegrees > 0f) { "maxTiltDegrees must be positive, was $maxTiltDegrees" }
        require(minSampleFraction in 0f..1f) {
            "minSampleFraction must be within 0..1, was $minSampleFraction"
        }
        require(maxEdgeGreenFraction in 0f..1f) {
            "maxEdgeGreenFraction must be within 0..1, was $maxEdgeGreenFraction"
        }
    }
}

/**
 * Turns the latest tilt and sample measurements into one instruction.
 *
 * Checks run in a fixed priority so the user is never given two instructions at once.
 * Level comes first because framing is meaningless while the phone is tilted: the sample
 * would shift as soon as the user levels the phone.
 *
 * Returns [GuidanceState.HOLD_STEADY] when everything is aligned; [SteadyHoldTimer] decides
 * when that becomes [GuidanceState.READY].
 */
fun evaluateGuidance(
    tilt: DeviceTilt,
    coverage: SampleCoverage,
    settings: GuidanceSettings,
): GuidanceState {
    val levelCorrection = levelCorrectionFor(tilt, settings.maxTiltDegrees)
    if (levelCorrection != null) return levelCorrection

    if (coverage.greenFraction < settings.minSampleFraction) return GuidanceState.NO_SAMPLE

    if (coverage.edgeGreenFraction > settings.maxEdgeGreenFraction) {
        return GuidanceState.SAMPLE_CUT_OFF
    }

    return GuidanceState.HOLD_STEADY
}

/**
 * Returns the instruction that fixes the larger of the two tilts, or null if the phone is level.
 * Fixing the larger tilt first avoids the message flickering between two directions.
 */
private fun levelCorrectionFor(tilt: DeviceTilt, maxTiltDegrees: Float): GuidanceState? {
    val isPitchOff = abs(tilt.pitchDegrees) > maxTiltDegrees
    val isRollOff = abs(tilt.rollDegrees) > maxTiltDegrees
    if (!isPitchOff && !isRollOff) return null

    val isPitchTheLargerTilt = abs(tilt.pitchDegrees) >= abs(tilt.rollDegrees)
    if (isPitchTheLargerTilt) {
        return if (tilt.pitchDegrees > 0) GuidanceState.TILT_TOP_DOWN else GuidanceState.TILT_BOTTOM_DOWN
    }
    return if (tilt.rollDegrees > 0) GuidanceState.TILT_RIGHT_DOWN else GuidanceState.TILT_LEFT_DOWN
}
