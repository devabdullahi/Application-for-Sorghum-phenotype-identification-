package com.sorghum.capture.guidance

/**
 * The single instruction shown to the user during live guidance.
 *
 * The TILT_* names say which edge of the phone to lower, because that is the edge
 * that is currently too high.
 */
enum class GuidanceState {
    TILT_TOP_DOWN,
    TILT_BOTTOM_DOWN,
    TILT_LEFT_DOWN,
    TILT_RIGHT_DOWN,
    NO_SAMPLE,
    SAMPLE_CUT_OFF,

    /** Everything is aligned, but not yet for long enough to capture. */
    HOLD_STEADY,

    /** Aligned for the full hold time; the photo should be taken now. */
    READY,
}
