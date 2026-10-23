package com.sorghum.capture.ui

import android.app.Application
import android.graphics.Bitmap
import android.util.Log
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.ImageProxy
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.sorghum.capture.camera.CameraSession
import com.sorghum.capture.camera.cropToTargetFrame
import com.sorghum.capture.camera.scaledToLongSide
import com.sorghum.capture.camera.toPixelImage
import com.sorghum.capture.guidance.DeviceTilt
import com.sorghum.capture.guidance.GuidanceState
import com.sorghum.capture.platform.BundledSpeciesModel
import com.sorghum.capture.quality.QUALITY_CHECK_LONG_SIDE_PIXELS
import com.sorghum.capture.quality.RejectionReason
import com.sorghum.capture.sample.SampleCoverage
import com.sorghum.session.CaptureFlow
import com.sorghum.session.CaptureSettings
import com.sorghum.session.CaptureState
import com.sorghum.species.SpeciesCheck
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

    /** Passed the quality check; [species] says whether it shows sorghum, or that no model is installed. */
    data class PhotoAccepted(val photo: Bitmap, val species: SpeciesCheck) : CaptureUiState
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
 *
 * The species model is loaded once, when the ViewModel is created, as on iOS. Without a
 * bundled model the flow reports the species check as unavailable and the screen says so.
 */
class CaptureViewModel(application: Application) : AndroidViewModel(application) {

    private val speciesModel = BundledSpeciesModel.load(application.assets)
    private val flow = CaptureFlow(CaptureSettings(), speciesModel?.gate)

    /** False when no usable species model is bundled; the screen must then say photos are not checked for sorghum. */
    val isSpeciesCheckAvailable: Boolean = flow.isSpeciesCheckAvailable

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
            val check = withContext(Dispatchers.Default) { photo.use { checkPhoto(it) } }
            if (check.rejection == null) acceptedPhoto = check.framedPhoto else check.framedPhoto.recycle()
            flow.onPhotoChecked(check.rejection, check.species)
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
            // acceptedPhoto is always set before the flow is told the photo passed.
            is CaptureState.PhotoAccepted -> CaptureUiState.PhotoAccepted(checkNotNull(acceptedPhoto), state.species)
            is CaptureState.PhotoRejected -> CaptureUiState.PhotoRejected(state.reason)
            CaptureState.CaptureFailed -> CaptureUiState.CaptureFailed
            CaptureState.CameraUnavailable -> CaptureUiState.CameraUnavailable
            CaptureState.LevelSensorUnavailable -> CaptureUiState.LevelSensorUnavailable
        }
    }

    override fun onCleared() {
        speciesModel?.close()
    }

    /**
     * Crops the photo to the target frame and runs the shared checks on it: quality first,
     * then, for an accepted photo, species. Same order and same analysis copy as iOS.
     */
    private fun checkPhoto(image: ImageProxy): PhotoCheck {
        val framedPhoto = cropToTargetFrame(image, targetFrame, maxLongSidePixels = Int.MAX_VALUE)

        // Quality thresholds are defined for a fixed analysis size (see QualitySettings). The
        // species gate makes its own model input from this same copy.
        val analysisCopy = framedPhoto.scaledToLongSide(QUALITY_CHECK_LONG_SIDE_PIXELS)
        val analysisImage = analysisCopy.toPixelImage()
        if (analysisCopy !== framedPhoto) analysisCopy.recycle()

        val rejection = flow.checkPhoto(analysisImage)
        // A rejected photo is retaken anyway, so the model is not run on it.
        val species = if (rejection == null) flow.checkSpecies(analysisImage) else SpeciesCheck.Unavailable
        return PhotoCheck(framedPhoto, rejection, species)
    }

    /** Outcome of [checkPhoto]. [species] is only meaningful when [rejection] is null. */
    private class PhotoCheck(val framedPhoto: Bitmap, val rejection: RejectionReason?, val species: SpeciesCheck)

    private companion object {
        const val TAG = "CaptureViewModel"
    }
}
