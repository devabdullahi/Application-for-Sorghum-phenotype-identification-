package com.sorghum.capture.platform

import android.content.Context
import android.util.Size
import androidx.camera.core.CameraSelector
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
 * Owns the back camera: the on-screen preview, low-resolution analysis frames, and
 * full-resolution still capture.
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
        cameraProvider.bindToLifecycle(lifecycleOwner, CameraSelector.DEFAULT_BACK_CAMERA, useCases)
    }

    /**
     * Stops the camera and the analysis thread. The session cannot be reused afterwards.
     * Not suspending, so it can be called from Compose's onDispose.
     */
    fun close() {
        boundCameraProvider?.unbindAll()
        boundCameraProvider = null
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
