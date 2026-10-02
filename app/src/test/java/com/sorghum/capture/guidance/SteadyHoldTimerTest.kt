package com.sorghum.capture.guidance

import org.junit.Assert.assertEquals
import org.junit.Test

class SteadyHoldTimerTest {

    private val timer = SteadyHoldTimer(holdDurationMillis = 800)

    @Test
    fun `aligned state stays HOLD_STEADY until the hold time has passed`() {
        assertEquals(GuidanceState.HOLD_STEADY, timer.update(GuidanceState.HOLD_STEADY, 1_000))
        assertEquals(GuidanceState.HOLD_STEADY, timer.update(GuidanceState.HOLD_STEADY, 1_799))
        assertEquals(GuidanceState.READY, timer.update(GuidanceState.HOLD_STEADY, 1_800))
    }

    @Test
    fun `any misalignment restarts the hold`() {
        timer.update(GuidanceState.HOLD_STEADY, 1_000)
        assertEquals(GuidanceState.TILT_TOP_DOWN, timer.update(GuidanceState.TILT_TOP_DOWN, 1_500))

        // Aligned again at 1_600: must hold until 2_400, not 1_800.
        assertEquals(GuidanceState.HOLD_STEADY, timer.update(GuidanceState.HOLD_STEADY, 1_600))
        assertEquals(GuidanceState.HOLD_STEADY, timer.update(GuidanceState.HOLD_STEADY, 2_000))
        assertEquals(GuidanceState.READY, timer.update(GuidanceState.HOLD_STEADY, 2_400))
    }

    @Test
    fun `reset forgets alignment in progress`() {
        timer.update(GuidanceState.HOLD_STEADY, 1_000)
        timer.reset()

        assertEquals(GuidanceState.HOLD_STEADY, timer.update(GuidanceState.HOLD_STEADY, 1_900))
    }

    @Test
    fun `zero hold time is ready immediately`() {
        val instantTimer = SteadyHoldTimer(holdDurationMillis = 0)

        assertEquals(GuidanceState.READY, instantTimer.update(GuidanceState.HOLD_STEADY, 5))
    }
}
