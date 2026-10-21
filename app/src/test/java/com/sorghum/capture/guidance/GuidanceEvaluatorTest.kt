package com.sorghum.capture.guidance

import com.sorghum.capture.sample.SampleCoverage
import org.junit.Assert.assertEquals
import org.junit.Test

class GuidanceEvaluatorTest {

    private val settings = GuidanceSettings(maxTiltDegrees = 5f, minSampleFraction = 0.02f, maxEdgeGreenFraction = 0.05f)
    private val level = DeviceTilt(pitchDegrees = 0f, rollDegrees = 0f)
    private val sampleInsideFrame = SampleCoverage(greenFraction = 0.3f, edgeGreenFraction = 0f, greenConfidence = 1f)

    @Test
    fun `level phone with sample inside frame asks the user to hold steady`() {
        assertEquals(GuidanceState.HOLD_STEADY, evaluateGuidance(level, sampleInsideFrame, settings))
    }

    @Test
    fun `tilt exactly at the limit still counts as level`() {
        val atLimit = DeviceTilt(pitchDegrees = 5f, rollDegrees = -5f)

        assertEquals(GuidanceState.HOLD_STEADY, evaluateGuidance(atLimit, sampleInsideFrame, settings))
    }

    @Test
    fun `each tilt direction asks the user to lower the raised edge`() {
        assertEquals(GuidanceState.TILT_TOP_DOWN, evaluateGuidance(DeviceTilt(10f, 0f), sampleInsideFrame, settings))
        assertEquals(GuidanceState.TILT_BOTTOM_DOWN, evaluateGuidance(DeviceTilt(-10f, 0f), sampleInsideFrame, settings))
        assertEquals(GuidanceState.TILT_RIGHT_DOWN, evaluateGuidance(DeviceTilt(0f, 10f), sampleInsideFrame, settings))
        assertEquals(GuidanceState.TILT_LEFT_DOWN, evaluateGuidance(DeviceTilt(0f, -10f), sampleInsideFrame, settings))
    }

    @Test
    fun `when both tilts are off the larger one is corrected first`() {
        val mostlyRolled = DeviceTilt(pitchDegrees = 7f, rollDegrees = -12f)

        assertEquals(GuidanceState.TILT_LEFT_DOWN, evaluateGuidance(mostlyRolled, sampleInsideFrame, settings))
    }

    @Test
    fun `tilt is reported before framing problems`() {
        val noSample = SampleCoverage(greenFraction = 0f, edgeGreenFraction = 0f, greenConfidence = 1f)

        assertEquals(GuidanceState.TILT_TOP_DOWN, evaluateGuidance(DeviceTilt(20f, 0f), noSample, settings))
    }

    @Test
    fun `too little green means no sample`() {
        val almostNoGreen = SampleCoverage(greenFraction = 0.01f, edgeGreenFraction = 0f, greenConfidence = 1f)

        assertEquals(GuidanceState.NO_SAMPLE, evaluateGuidance(level, almostNoGreen, settings))
    }

    @Test
    fun `green along the frame edge means the sample is cut off`() {
        val crossesEdge = SampleCoverage(greenFraction = 0.4f, edgeGreenFraction = 0.2f, greenConfidence = 1f)

        assertEquals(GuidanceState.SAMPLE_CUT_OFF, evaluateGuidance(level, crossesEdge, settings))
    }
}
