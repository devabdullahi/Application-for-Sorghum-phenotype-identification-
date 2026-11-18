package com.sorghum.capture.ui

import android.app.Application
import android.graphics.Bitmap
import android.net.Uri
import android.util.Log
import androidx.camera.core.ImageCaptureException
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.sorghum.capture.camera.CameraSession
import com.sorghum.capture.camera.cropToTargetFrame
import com.sorghum.capture.camera.scaledToLongSide
import com.sorghum.capture.camera.toPixelImage
import com.sorghum.capture.guidance.DeviceTilt
import com.sorghum.capture.guidance.GuidanceState
import com.sorghum.capture.platform.BundledSpeciesModel
import com.sorghum.capture.platform.decodeLibraryPhoto
import com.sorghum.capture.quality.PhotoSource
import com.sorghum.capture.quality.QUALITY_CHECK_LONG_SIDE_PIXELS
import com.sorghum.capture.quality.RejectionReason
import com.sorghum.segmentation.SampleCoverage
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
 * One accepted photo from this session, for the recent results list.
 *
 * @param photo a downscaled copy of the framed or picked photo, small enough to keep many in memory.
 * @param capturedAtEpochMillis wall-clock time the photo was taken or picked, for display only.
 */
data class HistoryEntry(val photo: Bitmap, val species: SpeciesCheck, val capturedAtEpochMillis: Long)

/**
 * Android adapter for the shared [CaptureFlow]: forwards camera and sensor events to it and
 * publishes its state for Compose. The capture rules themselves live in `shared/session`.
 *
 * All public functions must be called on the main thread; the camera and sensor callbacks are
 * routed there, so the flow has a single owner and needs no locking.
 *
 * The species model is loaded once, when the ViewModel is created, as on iOS. Without a
 * bundled model the flow reports the species check as unavailable, and each result says so.
 */
class CaptureViewModel(application: Application) : AndroidViewModel(application) {

    private val speciesModel = BundledSpeciesModel.load(application.assets)
    private val flow = CaptureFlow(CaptureSettings(), speciesModel?.gate)

    val targetFrame = flow.settings.targetFrame
    val greenDetectionSettings = flow.settings.greenDetection

    /** False when no species model is installed, which Settings must announce. */
    val isSpeciesCheckAvailable: Boolean get() = flow.isSpeciesCheckAvailable

    /** The accepted photo, kept here because the shared flow never holds platform images. */
    private var acceptedPhoto: Bitmap? = null

    private val mutableUiState = MutableStateFlow<CaptureUiState>(CaptureUiState.Guiding(guidance = null))
    val uiState: StateFlow<CaptureUiState> = mutableUiState.asStateFlow()

    private val mutableHistory = MutableStateFlow<List<HistoryEntry>>(emptyList())

    /**
     * Photos accepted this session, newest first, at most [MAX_HISTORY_ENTRIES]. Kept in memory
     * only: photos never leave the device and are not stored (CLAUDE.md, offline and private).
     */
    val history: StateFlow<List<HistoryEntry>> = mutableHistory.asStateFlow()

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
     * Takes a photo and checks it, from auto-capture or the shutter button. Ignored unless live
     * guidance is showing, which prevents a second capture while the first is still being checked.
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
            val capturedAtEpochMillis = System.currentTimeMillis()
            // Cropping and checking a full-resolution photo takes a moment; keep it off the UI thread.
            val check = withContext(Dispatchers.Default) {
                photo.use {
                    val framedPhoto = cropToTargetFrame(it, targetFrame, maxLongSidePixels = Int.MAX_VALUE)
                    checkPhoto(framedPhoto, PhotoSource.CAMERA_TARGET_FRAME)
                }
            }
            recordPhotoCheck(check, capturedAtEpochMillis)
        }
    }

    /**
     * Checks a photo picked from the photo library with the same shared checks as a camera
     * photo. The whole photo is used, since it has no target frame. Works without a camera or
     * level sensor (the shared flow decides); ignored while a photo is already being checked.
     * Same behaviour as `analyzeLibraryPhoto` on iOS.
     */
    fun analyzeLibraryPhoto(photoUri: Uri) {
        if (!flow.startLibraryCheck()) return
        publishState()

        val contentResolver = getApplication<Application>().contentResolver
        viewModelScope.launch {
            val pickedAtEpochMillis = System.currentTimeMillis()
            val photo = withContext(Dispatchers.IO) {
                decodeLibraryPhoto(contentResolver, photoUri, LIBRARY_PHOTO_LONG_SIDE_PIXELS)
            }
            if (photo == null) {
                flow.onCaptureFailed()
                publishState()
                return@launch
            }
            val check = withContext(Dispatchers.Default) { checkPhoto(photo, PhotoSource.PHOTO_LIBRARY) }
            recordPhotoCheck(check, pickedAtEpochMillis)
        }
    }

    /** Empties the recent results list. The photo on screen, if any, is not affected. */
    fun clearHistory() {
        mutableHistory.value = emptyList()
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

    private fun addToHistory(entry: HistoryEntry) {
        mutableHistory.value = (listOf(entry) + mutableHistory.value).take(MAX_HISTORY_ENTRIES)
    }

    override fun onCleared() {
        speciesModel?.close()
    }

    /**
     * Runs the shared checks on an upright photo (cropped to the target frame for a camera
     * photo, whole for a library photo): quality first, then, for an accepted photo, species.
     * Same order and same analysis copy as iOS.
     */
    private fun checkPhoto(photo: Bitmap, source: PhotoSource): PhotoCheck {
        // Quality thresholds are defined for a fixed analysis size (see QualitySettings). The
        // species gate makes its own model input from this same copy.
        val analysisCopy = photo.scaledToLongSide(QUALITY_CHECK_LONG_SIDE_PIXELS)
        val analysisImage = analysisCopy.toPixelImage()
        if (analysisCopy !== photo) analysisCopy.recycle()

        val rejection = flow.checkPhoto(analysisImage, source)
        // A rejected photo is retaken anyway, so the model is not run on it.
        if (rejection != null) return PhotoCheck(photo, rejection, species = null, historyPhoto = null)
        val species = flow.checkSpecies(analysisImage)
        return PhotoCheck(photo, rejection = null, species, photo.scaledToLongSide(HISTORY_PHOTO_LONG_SIDE_PIXELS))
    }

    /** Hands a finished [checkPhoto] to the shared flow and shows the new state. Main thread. */
    private fun recordPhotoCheck(check: PhotoCheck, capturedAtEpochMillis: Long) {
        if (check.rejection == null) {
            acceptedPhoto = check.photo
            addToHistory(HistoryEntry(checkNotNull(check.historyPhoto), checkNotNull(check.species), capturedAtEpochMillis))
            flow.onPhotoChecked(rejection = null, checkNotNull(check.species))
        } else {
            check.photo.recycle()
            flow.onPhotoChecked(check.rejection)
        }
        publishState()
    }

    /** Outcome of [checkPhoto]. [species] and [historyPhoto] are set exactly when [rejection] is null. */
    private class PhotoCheck(
        val photo: Bitmap,
        val rejection: RejectionReason?,
        val species: SpeciesCheck?,
        val historyPhoto: Bitmap?,
    )

    private companion object {
        const val TAG = "CaptureViewModel"

        /**
         * Long side of a library photo in memory: sharp enough for the result screen, and about
         * 16 MB at most, however large the original is.
         */
        const val LIBRARY_PHOTO_LONG_SIDE_PIXELS = 2048

        /** Long side of a History photo: sharp enough for a History row, about 0.5 MB each. */
        const val HISTORY_PHOTO_LONG_SIDE_PIXELS = 512

        /** Oldest photos are dropped beyond this, so History stays under about 25 MB of memory. */
        const val MAX_HISTORY_ENTRIES = 50
    }
}
