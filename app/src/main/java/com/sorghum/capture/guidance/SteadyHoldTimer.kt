package com.sorghum.capture.guidance

/**
 * Upgrades [GuidanceState.HOLD_STEADY] to [GuidanceState.READY] once the user has stayed
 * aligned for [holdDurationMillis] without interruption.
 *
 * Requiring a short hold avoids capturing while the phone is still moving into position.
 * Any other state restarts the hold.
 *
 * Timestamps are passed in rather than read from a clock so the behaviour is deterministic
 * in tests. Not thread-safe: call from a single thread (the UI thread in this app).
 */
class SteadyHoldTimer(private val holdDurationMillis: Long = DEFAULT_HOLD_DURATION_MILLIS) {

    /** When the current uninterrupted alignment started, or null if not aligned. */
    private var alignedSinceMillis: Long? = null

    init {
        require(holdDurationMillis >= 0) {
            "holdDurationMillis must not be negative, was $holdDurationMillis"
        }
    }

    /**
     * Returns the state to show for [evaluatedState], observed at [timestampMillis].
     * Timestamps must come from a monotonic clock (e.g. SystemClock.elapsedRealtime).
     */
    fun update(evaluatedState: GuidanceState, timestampMillis: Long): GuidanceState {
        if (evaluatedState != GuidanceState.HOLD_STEADY) {
            alignedSinceMillis = null
            return evaluatedState
        }

        val alignedSince = alignedSinceMillis ?: timestampMillis.also { alignedSinceMillis = it }
        val heldForMillis = timestampMillis - alignedSince
        return if (heldForMillis >= holdDurationMillis) GuidanceState.READY else GuidanceState.HOLD_STEADY
    }

    /** Forgets any alignment in progress, e.g. after a photo is taken. */
    fun reset() {
        alignedSinceMillis = null
    }

    companion object {
        const val DEFAULT_HOLD_DURATION_MILLIS = 800L
    }
}
