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
import com.sorghum.capture.guidance.DeviceTilt
import com.sorghum.capture.guidance.GuidanceState
import com.sorghum.capture.quality.QUALITY_CHECK_LONG_SIDE_PIXELS
import com.sorghum.capture.quality.RejectionReason
import com.sorghum.capture.sample.SampleCoverage
import com.sorghum.session.CaptureFlow
import com.sorghum.session.CaptureState
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
 * Android adapter for the shared [CaptureFlow]: forwards camera and sensor events to it and
 * publishes its state for Compose. The capture rules themselves live in `shared/session`.
 *
 * All public functions must be called on the main thread; the camera and sensor callbacks are
 * routed there, so the flow has a single owner and needs no locking.
 */
class CaptureViewModel : ViewModel() {

    private val flow = CaptureFlow()

    val targetFrame = flow.settings.targetFrame
    val greenDetectionSettings = flow.settings.greenDetection

    /** The accepted photo, kept here because the shared flow never holds platform images. */
    private var acceptedPhoto: Bitmap? = null

    private val mutableUiState = MutableStateFlow<CaptureUiState>(CaptureUiState.Guiding(guidance = null))
    val uiState: StateFlow<CaptureUiState> = mutableUiState.asStateFlow()

    /** @param timestampMillis from SystemClock.elapsedRealtime(). */
    fun onTiltChanged(tilt: DeviceTilt, timestampMillis: Long) {
        flow.onTiltChanged(tilt, timestampMillis)
        publishState()
    }

    /** @param timestampMillis from SystemClock.elapsedRealtime(). */
    fun onSampleCoverageMeasured(coverage: SampleCoverage, timestampMillis: Long) {
        flow.onSampleCoverageMeasured(coverage, timestampMillis)
        publishState()
    }

    fun onCameraUnavailable() {
        flow.onCameraUnavailable()
        publishState()
    }

    fun onLevelSensorUnavailable() {
        flow.onLevelSensorUnavailable()
        publishState()
    }

    /**
     * Takes a photo and checks it. Ignored unless live guidance is showing, which prevents a
     * second capture while the first is still being checked.
     */
    fun captureAndCheckPhoto(camera: CameraSession) {
        if (!flow.startCapture()) return
        publishState()

        viewModelScope.launch {
            val photo = try {
                camera.takePhoto()
            } catch (exception: ImageCaptureException) {
                Log.e(TAG, "Photo capture failed (error ${exception.imageCaptureError})", exception)
                flow.onCaptureFailed()
                publishState()
                return@launch
            }
            // Cropping and checking a full-resolution photo takes a moment; keep it off the UI thread.
            val (framedPhoto, rejection) = withContext(Dispatchers.Default) { photo.use { checkPhoto(it) } }
            if (rejection == null) acceptedPhoto = framedPhoto else framedPhoto.recycle()
            flow.onPhotoChecked(rejection)
            publishState()
        }
    }

    /** Returns to live guidance, starting the steady hold from scratch. */
    fun retake() {
        acceptedPhoto = null
        flow.retake()
        publishState()
    }

    private fun publishState() {
        mutableUiState.value = when (val state = flow.state) {
            is CaptureState.Guiding -> CaptureUiState.Guiding(state.guidance)
            CaptureState.CheckingPhoto -> CaptureUiState.CheckingPhoto
            // Android has no species model yet (step 4 lands on iOS first), so species is always Unavailable.
            is CaptureState.PhotoAccepted -> CaptureUiState.PhotoAccepted(checkNotNull(acceptedPhoto))
            is CaptureState.PhotoRejected -> CaptureUiState.PhotoRejected(state.reason)
            CaptureState.CaptureFailed -> CaptureUiState.CaptureFailed
            CaptureState.CameraUnavailable -> CaptureUiState.CameraUnavailable
            CaptureState.LevelSensorUnavailable -> CaptureUiState.LevelSensorUnavailable
        }
    }

    /** Returns the photo cropped to the target frame, and why it was rejected (null if accepted). */
    private fun checkPhoto(image: ImageProxy): Pair<Bitmap, RejectionReason?> {
        val framedPhoto = cropToTargetFrame(image, targetFrame, maxLongSidePixels = Int.MAX_VALUE)

        // Quality thresholds are defined for a fixed analysis size (see QualitySettings).
        val analysisCopy = framedPhoto.scaledToLongSide(QUALITY_CHECK_LONG_SIDE_PIXELS)
        val rejection = flow.checkPhoto(analysisCopy.toPixelImage())
        if (analysisCopy !== framedPhoto) analysisCopy.recycle()
        return framedPhoto to rejection
    }

    private companion object {
        const val TAG = "CaptureViewModel"
    }
}
