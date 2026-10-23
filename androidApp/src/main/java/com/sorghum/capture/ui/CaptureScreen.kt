package com.sorghum.capture.ui

import android.Manifest
import android.content.pm.PackageManager
import android.os.SystemClock
import android.util.Log
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.annotation.StringRes
import androidx.camera.view.PreviewView
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathFillType
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.core.view.doOnLayout
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.sorghum.capture.R
import com.sorghum.capture.guidance.GuidanceState
import com.sorghum.capture.platform.CameraSession
import com.sorghum.capture.platform.SampleCoverageAnalyzer
import com.sorghum.capture.platform.TiltSensor
import com.sorghum.capture.platform.TiltSensorUnavailableException
import com.sorghum.capture.quality.RejectionReason
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.launch
import kotlin.math.roundToInt

private const val TAG = "CaptureScreen"

/**
 * The Capture tab. Deliberately minimal for phase 1: live preview with a frame outline and a
 * one-line instruction, then either the accepted photo or the rejection reason.
 */
@Composable
fun CaptureApp(viewModel: CaptureViewModel = viewModel()) {
    val context = LocalContext.current
    var hasCameraPermission by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
        )
    }
    val permissionLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { isGranted ->
        hasCameraPermission = isGranted
    }
    LaunchedEffect(Unit) {
        if (!hasCameraPermission) permissionLauncher.launch(Manifest.permission.CAMERA)
    }

    if (!hasCameraPermission) {
        MessageWithButton(
            message = stringResource(R.string.camera_permission_needed),
            buttonLabel = stringResource(R.string.grant_permission),
            onClick = { permissionLauncher.launch(Manifest.permission.CAMERA) },
        )
        return
    }

    val state by viewModel.uiState.collectAsStateWithLifecycle()
    val currentState = state
    // One branch for both states so the camera is not restarted while the photo is checked.
    if (currentState is CaptureUiState.Guiding || currentState is CaptureUiState.CheckingPhoto) {
        CameraPreview(
            viewModel,
            guidance = (currentState as? CaptureUiState.Guiding)?.guidance,
            isCheckingPhoto = currentState is CaptureUiState.CheckingPhoto,
        )
    } else {
        ResultView(currentState, onRetake = viewModel::retake)
    }
}

/**
 * Camera preview inside the target frame, a fixed instruction, and the capture button. The
 * outline turns green when guidance says the phone is level and the sample is held steady;
 * the photo is only taken when the user taps the button.
 */
@Composable
private fun CameraPreview(viewModel: CaptureViewModel, guidance: GuidanceState?, isCheckingPhoto: Boolean) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val scope = rememberCoroutineScope()
    val camera = remember { CameraSession(context) }
    DisposableEffect(camera) { onDispose { camera.close() } }

    // Feed level readings into the guidance while this screen is visible.
    LaunchedEffect(Unit) {
        TiltSensor(context).tiltUpdates()
            .catch { error ->
                if (error !is TiltSensorUnavailableException) throw error
                Log.e(TAG, "Level guidance unavailable", error)
                viewModel.onLevelSensorUnavailable()
            }
            .collect { tilt -> viewModel.onTiltChanged(tilt, SystemClock.elapsedRealtime()) }
    }

    Box(Modifier.fillMaxSize()) {
        AndroidView(
            modifier = Modifier.fillMaxSize(),
            factory = { viewContext ->
                PreviewView(viewContext).apply {
                    val analyzer = SampleCoverageAnalyzer(
                        targetFrame = viewModel.targetFrame,
                        settings = viewModel.greenDetectionSettings,
                        callbackExecutor = ContextCompat.getMainExecutor(viewContext),
                    ) { coverage -> viewModel.onSampleCoverageMeasured(coverage, SystemClock.elapsedRealtime()) }

                    // The camera's crop comes from this view's size, so bind only after layout.
                    doOnLayout {
                        scope.launch {
                            try {
                                camera.bind(lifecycleOwner, this@apply, analyzer)
                            } catch (cancellation: CancellationException) {
                                throw cancellation
                            } catch (error: Exception) {
                                // CameraX reports open failures with several exception types; all
                                // mean the same thing to the user.
                                Log.e(TAG, "Could not start the camera", error)
                                viewModel.onCameraUnavailable()
                            }
                        }
                    }
                }
            },
        )

        // Same TargetFrame and same size as the PreviewView, so the outline matches the region
        // that is analysed and cropped. The preview stays full size and is covered outside the
        // frame, because shrinking the PreviewView would change that region.
        val isAligned = guidance == GuidanceState.HOLD_STEADY || guidance == GuidanceState.READY
        Canvas(Modifier.fillMaxSize()) {
            val frame = viewModel.targetFrame.normalizedRectIn(size.width.roundToInt(), size.height.roundToInt())
            val frameRect = Rect(
                left = frame.left * size.width,
                top = frame.top * size.height,
                right = frame.right * size.width,
                bottom = frame.bottom * size.height,
            )
            val outsideFrame = Path().apply {
                fillType = PathFillType.EvenOdd
                addRect(Rect(Offset.Zero, size))
                addRect(frameRect)
            }
            drawPath(outsideFrame, Color.White)
            drawRect(
                color = if (isAligned) Color.Green else Color.White,
                topLeft = frameRect.topLeft,
                size = frameRect.size,
                style = Stroke(width = 4.dp.toPx()),
            )
        }

        // Sits on the white area outside the frame, so it is dark.
        Text(
            text = stringResource(R.string.capture_instruction),
            color = Color.Black,
            modifier = Modifier
                .align(Alignment.TopCenter)
                .safeDrawingPadding()
                .padding(24.dp),
        )

        FilledIconButton(
            onClick = { viewModel.captureAndCheckPhoto(camera) },
            enabled = !isCheckingPhoto,
            shape = CircleShape,
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .safeDrawingPadding()
                .padding(16.dp)
                .size(72.dp),
        ) {
            if (isCheckingPhoto) {
                val checkingPhotoDescription = stringResource(R.string.checking_photo)
                CircularProgressIndicator(
                    modifier = Modifier
                        .size(32.dp)
                        .semantics { contentDescription = checkingPhotoDescription },
                )
            } else {
                Icon(
                    painter = painterResource(R.drawable.ic_tab_capture),
                    contentDescription = stringResource(R.string.capture_photo),
                    modifier = Modifier.size(32.dp),
                )
            }
        }
    }
}

/** Shows the accepted photo, or why capture did not succeed, with a way to try again. */
@Composable
private fun ResultView(state: CaptureUiState, onRetake: () -> Unit) {
    if (state is CaptureUiState.PhotoAccepted) {
        Column(
            modifier = Modifier.fillMaxSize().safeDrawingPadding().padding(16.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text(stringResource(R.string.photo_accepted))
            Image(
                bitmap = state.photo.asImageBitmap(),
                contentDescription = stringResource(R.string.photo_accepted),
                modifier = Modifier.weight(1f).fillMaxWidth(),
            )
            Button(onClick = onRetake) { Text(stringResource(R.string.retake)) }
        }
        return
    }

    val message = when (state) {
        is CaptureUiState.PhotoRejected -> stringResource(rejectionMessage(state.reason))
        CaptureUiState.CaptureFailed -> stringResource(R.string.capture_failed)
        CaptureUiState.CameraUnavailable -> stringResource(R.string.camera_unavailable)
        CaptureUiState.LevelSensorUnavailable -> stringResource(R.string.level_sensor_unavailable)
        else -> error("ResultView cannot show $state")
    }
    MessageWithButton(message, stringResource(R.string.try_again), onRetake)
}

@Composable
private fun MessageWithButton(message: String, buttonLabel: String, onClick: () -> Unit) {
    Column(
        modifier = Modifier.fillMaxSize().safeDrawingPadding().padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(16.dp, Alignment.CenterVertically),
    ) {
        Text(message)
        Button(onClick = onClick) { Text(buttonLabel) }
    }
}

@StringRes
private fun rejectionMessage(reason: RejectionReason): Int = when (reason) {
    RejectionReason.NO_SAMPLE -> R.string.rejected_no_sample
    RejectionReason.TOO_DARK -> R.string.rejected_too_dark
    RejectionReason.GLARE -> R.string.rejected_glare
    RejectionReason.BLURRY -> R.string.rejected_blurry
}
