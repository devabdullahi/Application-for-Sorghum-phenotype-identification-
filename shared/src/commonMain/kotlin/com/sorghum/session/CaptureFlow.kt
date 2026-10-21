package com.sorghum.session

import com.sorghum.capture.frame.TargetFrame
import com.sorghum.capture.guidance.DeviceTilt
import com.sorghum.capture.guidance.GuidanceSettings
import com.sorghum.capture.guidance.GuidanceState
import com.sorghum.capture.guidance.SteadyHoldTimer
import com.sorghum.capture.guidance.evaluateGuidance
import com.sorghum.capture.quality.QualitySettings
import com.sorghum.capture.quality.RejectionReason
import com.sorghum.capture.quality.checkPhotoQuality
import com.sorghum.capture.sample.GreenDetectionSettings
import com.sorghum.capture.sample.SampleCoverage
import com.sorghum.capture.sample.measureSampleCoverage
import com.sorghum.imaging.PixelImage

/** Everything the capture screen can show. Exactly one is active at a time. */
sealed interface CaptureState {
    /** Live guidance. [guidance] is null until the first tilt and frame readings arrive. */
    data class Guiding(val guidance: GuidanceState?) : CaptureState

    data object CheckingPhoto : CaptureState

    /** The photo passed the check. The photo itself stays with the platform, which displays it. */
    data object PhotoAccepted : CaptureState

    data class PhotoRejected(val reason: RejectionReason) : CaptureState
    data object CaptureFailed : CaptureState
    data object CameraUnavailable : CaptureState
    data object LevelSensorUnavailable : CaptureState
}

/**
 * All settings of the capture flow, so both apps use the same values.
 *
 * Quality checking reuses [greenDetection], so "the sample is present" means the same thing
 * live and after capture.
 */
data class CaptureSettings(
    val targetFrame: TargetFrame = TargetFrame(),
    val greenDetection: GreenDetectionSettings = GreenDetectionSettings(),
    val guidance: GuidanceSettings = GuidanceSettings(),
    val holdDurationMillis: Long = SteadyHoldTimer.DEFAULT_HOLD_DURATION_MILLIS,
) {
    val quality: QualitySettings = QualitySettings(greenDetection = greenDetection)
}

/**
 * The capture flow's state machine: combines tilt and sample readings into guidance, and
 * turns the post-capture check into an accepted or rejected photo.
 *
 * Threads: the event functions ([onTiltChanged], [onSampleCoverageMeasured], [startCapture],
 * [onPhotoChecked], [retake], ...) and [state] belong to the main thread, so guidance state
 * has a single owner and needs no locking. [measureLiveFrame] and [checkPhoto] are pure and
 * may run on any thread; the apps call them on their camera or worker threads.
 *
 * The platform owns the camera and the photo pixels; this class only sees [PixelImage]s and
 * the measurements made from them.
 */
class CaptureFlow(val settings: CaptureSettings) {

    /** Uses the default settings. Swift cannot use Kotlin default arguments, hence this overload. */
    constructor() : this(CaptureSettings())

    private val holdTimer = SteadyHoldTimer(settings.holdDurationMillis)
    private var latestTilt: DeviceTilt? = null
    private var latestCoverage: SampleCoverage? = null

    var state: CaptureState = CaptureState.Guiding(guidance = null)
        private set

    /** @param timestampMillis from a monotonic clock. */
    fun onTiltChanged(tilt: DeviceTilt, timestampMillis: Long) {
        latestTilt = tilt
        refreshGuidance(timestampMillis)
    }

    /** @param timestampMillis from the same monotonic clock as [onTiltChanged]. */
    fun onSampleCoverageMeasured(coverage: SampleCoverage, timestampMillis: Long) {
        latestCoverage = coverage
        refreshGuidance(timestampMillis)
    }

    /** Measures the sample in a live frame already cropped to the target frame. Any thread. */
    fun measureLiveFrame(image: PixelImage): SampleCoverage =
        measureSampleCoverage(image, settings.greenDetection)

    /**
     * Moves to [CaptureState.CheckingPhoto] and returns true if a photo should be taken now.
     * Returns false unless live guidance is showing, which prevents a second capture while the
     * first is still being checked.
     */
    fun startCapture(): Boolean {
        if (state !is CaptureState.Guiding) return false
        state = CaptureState.CheckingPhoto
        return true
    }

    /**
     * Checks a captured photo, cropped to the target frame and scaled so its longer side is
     * [com.sorghum.capture.quality.QUALITY_CHECK_LONG_SIDE_PIXELS]. Returns the rejection
     * reason, or null if the photo is acceptable. Pure; call it off the main thread.
     */
    fun checkPhoto(image: PixelImage): RejectionReason? = checkPhotoQuality(image, settings.quality)

    /** Records the result of [checkPhoto]. */
    fun onPhotoChecked(rejection: RejectionReason?) {
        state = if (rejection == null) CaptureState.PhotoAccepted else CaptureState.PhotoRejected(rejection)
    }

    fun onCaptureFailed() {
        state = CaptureState.CaptureFailed
    }

    fun onCameraUnavailable() {
        state = CaptureState.CameraUnavailable
    }

    fun onLevelSensorUnavailable() {
        state = CaptureState.LevelSensorUnavailable
    }

    /** Returns to live guidance, starting the steady hold from scratch. */
    fun retake() {
        holdTimer.reset()
        latestCoverage = null
        state = CaptureState.Guiding(guidance = null)
    }

    private fun refreshGuidance(timestampMillis: Long) {
        if (state !is CaptureState.Guiding) return
        val tilt = latestTilt ?: return
        val coverage = latestCoverage ?: return

        val evaluated = evaluateGuidance(tilt, coverage, settings.guidance)
        state = CaptureState.Guiding(holdTimer.update(evaluated, timestampMillis))
    }
}
