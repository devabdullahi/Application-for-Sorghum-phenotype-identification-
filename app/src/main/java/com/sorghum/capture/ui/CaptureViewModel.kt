package com.sorghum.capture.ui

import android.graphics.Bitmap
import android.util.Log
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.ImageProxy
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.sorghum.capture.camera.CameraSession
import com.sorghum.capture.camera.cropToTargetFrame
import com.sorghum.capture.camera.scaledToLongSide
import com.sorghum.capture.camera.toPixelImage
import com.sorghum.capture.frame.TargetFrame
import com.sorghum.capture.guidance.DeviceTilt
import com.sorghum.capture.guidance.GuidanceSettings
import com.sorghum.capture.guidance.GuidanceState
import com.sorghum.capture.guidance.SteadyHoldTimer
import com.sorghum.capture.guidance.evaluateGuidance
import com.sorghum.capture.quality.QUALITY_CHECK_LONG_SIDE_PIXELS
import com.sorghum.capture.quality.QualitySettings
import com.sorghum.capture.quality.RejectionReason
import com.sorghum.capture.quality.checkPhotoQuality
import com.sorghum.capture.sample.GreenDetectionSettings
import com.sorghum.capture.sample.SampleCoverage
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Everything the capture UI can show. Exactly one is active at a time. */
sealed interface CaptureUiState {
    /** Live guidance. [guidance] is null until the first tilt and frame readings arrive. */
    data class Guiding(val guidance: GuidanceState?) : CaptureUiState

    data object CheckingPhoto : CaptureUiState
    data class PhotoAccepted(val photo: Bitmap) : CaptureUiState
    data class PhotoRejected(val reason: RejectionReason) : CaptureUiState
    data object CaptureFailed : CaptureUiState
    data object CameraUnavailable : CaptureUiState
    data object LevelSensorUnavailable : CaptureUiState
}

/**
 * Holds the capture flow's state: combines tilt and sample readings into guidance, and runs
 * the post-capture check.
 *
 * All public functions must be called on the main thread; the camera and sensor callbacks are
 * routed there, so guidance state has a single owner and needs no locking.
 */
class CaptureViewModel : ViewModel() {

    val targetFrame = TargetFrame()
    val greenDetectionSettings = GreenDetectionSettings()
    private val guidanceSettings = GuidanceSettings()
    private val qualitySettings = QualitySettings(greenDetection = greenDetectionSettings)
    private val holdTimer = SteadyHoldTimer()

    private var latestTilt: DeviceTilt? = null
    private var latestCoverage: SampleCoverage? = null

    private val mutableUiState = MutableStateFlow<CaptureUiState>(CaptureUiState.Guiding(guidance = null))
    val uiState: StateFlow<CaptureUiState> = mutableUiState.asStateFlow()

    /** @param timestampMillis from SystemClock.elapsedRealtime(). */
    fun onTiltChanged(tilt: DeviceTilt, timestampMillis: Long) {
        latestTilt = tilt
        refreshGuidance(timestampMillis)
    }

    /** @param timestampMillis from SystemClock.elapsedRealtime(). */
    fun onSampleCoverageMeasured(coverage: SampleCoverage, timestampMillis: Long) {
        latestCoverage = coverage
        refreshGuidance(timestampMillis)
    }

    fun onCameraUnavailable() {
        mutableUiState.value = CaptureUiState.CameraUnavailable
    }

    fun onLevelSensorUnavailable() {
        mutableUiState.value = CaptureUiState.LevelSensorUnavailable
    }

    /**
     * Takes a photo and checks it. Ignored unless live guidance is showing, which prevents a
     * second capture while the first is still being checked.
     */
    fun captureAndCheckPhoto(camera: CameraSession) {
        if (mutableUiState.value !is CaptureUiState.Guiding) return
        mutableUiState.value = CaptureUiState.CheckingPhoto

        viewModelScope.launch {
            val photo = try {
                camera.takePhoto()
            } catch (exception: ImageCaptureException) {
                Log.e(TAG, "Photo capture failed (error ${exception.imageCaptureError})", exception)
                mutableUiState.value = CaptureUiState.CaptureFailed
                return@launch
            }
            // Cropping and checking a full-resolution photo takes a moment; keep it off the UI thread.
            mutableUiState.value = withContext(Dispatchers.Default) { photo.use { checkPhoto(it) } }
        }
    }

    /** Returns to live guidance, starting the steady hold from scratch. */
    fun retake() {
        holdTimer.reset()
        latestCoverage = null
        mutableUiState.value = CaptureUiState.Guiding(guidance = null)
    }

    private fun refreshGuidance(timestampMillis: Long) {
        if (mutableUiState.value !is CaptureUiState.Guiding) return
        val tilt = latestTilt ?: return
        val coverage = latestCoverage ?: return

        val evaluated = evaluateGuidance(tilt, coverage, guidanceSettings)
        mutableUiState.value = CaptureUiState.Guiding(holdTimer.update(evaluated, timestampMillis))
    }

    private fun checkPhoto(image: ImageProxy): CaptureUiState {
        val framedPhoto = cropToTargetFrame(image, targetFrame, maxLongSidePixels = Int.MAX_VALUE)

        // Quality thresholds are defined for a fixed analysis size (see QualitySettings).
        val analysisCopy = framedPhoto.scaledToLongSide(QUALITY_CHECK_LONG_SIDE_PIXELS)
        val rejection = checkPhotoQuality(analysisCopy.toPixelImage(), qualitySettings)
        if (analysisCopy !== framedPhoto) analysisCopy.recycle()

        if (rejection != null) {
            framedPhoto.recycle()
            return CaptureUiState.PhotoRejected(rejection)
        }
        return CaptureUiState.PhotoAccepted(framedPhoto)
    }

    private companion object {
        const val TAG = "CaptureViewModel"
    }
}
