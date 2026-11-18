package com.sorghum.capture.camera

import android.content.Context
import android.hardware.camera2.CameraAccessException
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.util.Log
import android.util.Size
import androidx.camera.core.Camera
import androidx.camera.core.CameraSelector
import androidx.camera.core.FocusMeteringAction
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.core.UseCaseGroup
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.core.resolutionselector.ResolutionStrategy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.lifecycle.awaitInstance
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleOwner
import kotlinx.coroutines.suspendCancellableCoroutine
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/**
 * True if a back camera has a flash. Asked of Camera2 directly, so it is known before any
 * camera is opened. False if the camera service cannot be reached.
 */
fun hasBackCameraFlash(context: Context): Boolean {
    val cameraManager = context.getSystemService(CameraManager::class.java) ?: return false
    return try {
        cameraManager.cameraIdList.any { cameraId ->
            val characteristics = cameraManager.getCameraCharacteristics(cameraId)
            characteristics.get(CameraCharacteristics.LENS_FACING) == CameraCharacteristics.LENS_FACING_BACK &&
                characteristics.get(CameraCharacteristics.FLASH_INFO_AVAILABLE) == true
        }
    } catch (exception: CameraAccessException) {
        Log.e("CameraSession", "Could not read camera characteristics", exception)
        false
    }
}

/**
 * Owns the back camera: the on-screen preview, low-resolution analysis frames, and
 * full-resolution still capture, plus the user's zoom, focus, exposure and flash controls.
 *
 * All three use cases are bound with the preview's viewport, so CameraX gives every image the
 * same crop as what the user sees. That is what lets the target frame drawn on screen be
 * mapped onto analysis frames and the photo (see FrameMapping.kt).
 */
class CameraSession(context: Context) {

    private val appContext = context.applicationContext

    /** Analysis runs off the main thread so the UI never stutters. */
    private val analysisExecutor: ExecutorService = Executors.newSingleThreadExecutor()

    /** Set once [bind] succeeds, so [close] can release the camera. Main thread only. */
    private var boundCameraProvider: ProcessCameraProvider? = null

    /** The bound camera, for zoom, focus and exposure. Null until [bind] succeeds. Main thread only. */
    private var boundCamera: Camera? = null

    /** The view the camera was bound to; its metering point factory maps screen taps to the sensor. */
    private var boundPreviewView: PreviewView? = null

    /**
     * Last zoom ratio sent to the camera. Kept here rather than read back from the camera's
     * zoom state, which updates asynchronously and would make a fast pinch stutter.
     */
    private var requestedZoomRatio = 1f

    private val preview = Preview.Builder().build()

    private val imageAnalysis = ImageAnalysis.Builder()
        // Drop frames that arrive while the previous one is still being analysed, so guidance
        // always reflects the latest frame instead of lagging behind a queue.
        .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
        // RGBA avoids a YUV-to-RGB conversion step in our code; the green check needs RGB.
        .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_RGBA_8888)
        .setResolutionSelector(
            ResolutionSelector.Builder()
                .setResolutionStrategy(
                    ResolutionStrategy(
                        ANALYSIS_RESOLUTION,
                        ResolutionStrategy.FALLBACK_RULE_CLOSEST_LOWER_THEN_HIGHER,
                    )
                )
                .build()
        )
        .build()

    private val imageCapture = ImageCapture.Builder()
        // Photos are used for measurements, so favour quality over shutter speed.
        .setCaptureMode(ImageCapture.CAPTURE_MODE_MAXIMIZE_QUALITY)
        .build()

    /**
     * Starts the camera and binds it to [lifecycleOwner], so it stops automatically when the
     * app goes to the background. Call after [previewView] has been laid out, because the
     * viewport comes from its size.
     *
     * Throws if the camera cannot be opened (e.g. another app is using it).
     */
    suspend fun bind(lifecycleOwner: LifecycleOwner, previewView: PreviewView, analyzer: ImageAnalysis.Analyzer) {
        val viewPort = checkNotNull(previewView.viewPort) {
            "PreviewView has no viewport yet; bind() must be called after it is laid out"
        }
        val cameraProvider = ProcessCameraProvider.awaitInstance(appContext)
        boundCameraProvider = cameraProvider

        preview.surfaceProvider = previewView.surfaceProvider
        imageAnalysis.setAnalyzer(analysisExecutor, analyzer)

        val useCases = UseCaseGroup.Builder()
            .setViewPort(viewPort)
            .addUseCase(preview)
            .addUseCase(imageAnalysis)
            .addUseCase(imageCapture)
            .build()

        cameraProvider.unbindAll()
        boundCamera = cameraProvider.bindToLifecycle(lifecycleOwner, CameraSelector.DEFAULT_BACK_CAMERA, useCases)
        boundPreviewView = previewView
    }

    /** Whether the next photo fires the flash. Can be changed at any time, before or after [bind]. */
    var isFlashEnabled: Boolean
        get() = imageCapture.flashMode == ImageCapture.FLASH_MODE_ON
        set(isEnabled) {
            imageCapture.flashMode = if (isEnabled) ImageCapture.FLASH_MODE_ON else ImageCapture.FLASH_MODE_OFF
        }

    /**
     * Multiplies the zoom by [scaleFactor] (a pinch's scale change), within the camera's range.
     * Returns the zoom ratio now requested, for the on-screen label. Does nothing before [bind].
     */
    fun zoomBy(scaleFactor: Float): Float {
        val camera = boundCamera ?: return requestedZoomRatio
        val zoomState = camera.cameraInfo.zoomState.value ?: return requestedZoomRatio
        requestedZoomRatio = (requestedZoomRatio * scaleFactor).coerceIn(zoomState.minZoomRatio, zoomState.maxZoomRatio)
        camera.cameraControl.setZoomRatio(requestedZoomRatio)
        return requestedZoomRatio
    }

    /**
     * Focuses and meters exposure at a point of the preview, in the preview view's pixels, and
     * resets exposure compensation, as a tap does in the iPhone camera. The point stays in use
     * until the next tap rather than timing out, so the brightness the user chose does not jump
     * back. Does nothing before [bind].
     */
    fun focusAndMeterAt(previewX: Float, previewY: Float) {
        val camera = boundCamera ?: return
        val previewView = boundPreviewView ?: return
        val point = previewView.meteringPointFactory.createPoint(previewX, previewY)
        val action = FocusMeteringAction.Builder(point, FocusMeteringAction.FLAG_AF or FocusMeteringAction.FLAG_AE)
            .disableAutoCancel()
            .build()
        camera.cameraControl.startFocusAndMetering(action)
        setExposureCompensation(0)
    }

    /**
     * The exposure compensation range in camera steps (negative is darker), or null if this
     * camera cannot adjust exposure or is not bound yet.
     */
    val exposureCompensationRange: IntRange?
        get() {
            val exposureState = boundCamera?.cameraInfo?.exposureState ?: return null
            if (!exposureState.isExposureCompensationSupported) return null
            val range = exposureState.exposureCompensationRange
            return range.lower..range.upper
        }

    /**
     * Sets exposure compensation to [steps], clamped to [exposureCompensationRange], and returns
     * the steps actually applied (0 when exposure cannot be adjusted).
     */
    fun setExposureCompensation(steps: Int): Int {
        val camera = boundCamera ?: return 0
        val range = exposureCompensationRange ?: return 0
        val appliedSteps = steps.coerceIn(range)
        camera.cameraControl.setExposureCompensationIndex(appliedSteps)
        return appliedSteps
    }

    /**
     * Stops the camera and the analysis thread. The session cannot be reused afterwards.
     * Not suspending, so it can be called from Compose's onDispose.
     */
    fun close() {
        boundCameraProvider?.unbindAll()
        boundCameraProvider = null
        boundCamera = null
        boundPreviewView = null
        imageAnalysis.clearAnalyzer()
        analysisExecutor.shutdown()
    }

    /**
     * Takes a full-resolution photo and returns it in memory. Nothing is written to storage.
     * The caller must close the returned image.
     *
     * @throws ImageCaptureException if the camera fails to take the photo.
     */
    suspend fun takePhoto(): ImageProxy = suspendCancellableCoroutine { continuation ->
        imageCapture.takePicture(
            ContextCompat.getMainExecutor(appContext),
            object : ImageCapture.OnImageCapturedCallback() {
                override fun onCaptureSuccess(image: ImageProxy) {
                    // If the caller was cancelled meanwhile, nobody will close the image, so
                    // close it here to release the camera buffer.
                    continuation.resume(image) { _, capturedImage, _ -> capturedImage.close() }
                }

                override fun onError(exception: ImageCaptureException) {
                    continuation.resumeWithException(exception)
                }
            },
        )
    }

    private companion object {
        /** Small frames are enough for counting green pixels and keep analysis fast. */
        val ANALYSIS_RESOLUTION = Size(640, 480)
    }
}
