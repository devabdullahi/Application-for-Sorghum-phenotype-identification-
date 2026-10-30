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
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
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
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.core.view.doOnLayout
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.sorghum.capture.R
import com.sorghum.capture.camera.CameraSession
import com.sorghum.capture.camera.SampleCoverageAnalyzer
import com.sorghum.capture.camera.TiltSensor
import com.sorghum.capture.camera.TiltSensorUnavailableException
import com.sorghum.capture.guidance.GuidanceState
import com.sorghum.capture.quality.RejectionReason
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.launch
import kotlin.math.roundToInt

private const val TAG = "CaptureScreen"

/**
 * The Capture tab: live preview with a frame outline and a fixed instruction, then either the
 * accepted photo with its species result or the rejection reason.
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
 * Camera preview, target frame outline and one fixed instruction. Live guidance (level, hold)
 * still drives auto-capture, but is shown only through the outline turning green.
 */
@Composable
private fun CameraPreview(viewModel: CaptureViewModel, guidance: GuidanceState?, isCheckingPhoto: Boolean) {
    val context = LocalContext.current
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

    // Auto-capture as soon as the user has held steady long enough.
    LaunchedEffect(guidance) {
        if (guidance == GuidanceState.READY) viewModel.captureAndCheckPhoto(camera)
    }

    Column(Modifier.fillMaxSize()) {
        // Above the preview, not over it, so it never hides the top of the target frame.
        Text(
            text = stringResource(R.string.capture_instruction),
            color = Color.White,
            style = MaterialTheme.typography.titleMedium,
            textAlign = TextAlign.Center,
            modifier = Modifier
                .fillMaxWidth()
                .background(Color.Black)
                .safeDrawingPadding()
                .padding(horizontal = 24.dp, vertical = 12.dp),
        )
        CameraViewfinder(viewModel, camera, guidance, isCheckingPhoto, Modifier.weight(1f))
    }
}

/**
 * Preview with the target frame outline. The [PreviewView] and the outline share this box, so
 * the outline matches the region that is analysed and cropped.
 */
@Composable
private fun CameraViewfinder(
    viewModel: CaptureViewModel,
    camera: CameraSession,
    guidance: GuidanceState?,
    isCheckingPhoto: Boolean,
    modifier: Modifier,
) {
    val lifecycleOwner = LocalLifecycleOwner.current
    val scope = rememberCoroutineScope()
    Box(modifier.fillMaxWidth()) {
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
        // that is analysed and cropped.
        val isAligned = guidance == GuidanceState.HOLD_STEADY || guidance == GuidanceState.READY
        Canvas(Modifier.fillMaxSize()) {
            val frame = viewModel.targetFrame.normalizedRectIn(size.width.roundToInt(), size.height.roundToInt())
            drawRect(
                color = if (isAligned) Color.Green else Color.White,
                topLeft = Offset(frame.left * size.width, frame.top * size.height),
                size = Size((frame.right - frame.left) * size.width, (frame.bottom - frame.top) * size.height),
                style = Stroke(width = 4.dp.toPx()),
            )
        }

        if (isCheckingPhoto) {
            CircularProgressIndicator(color = Color.White, modifier = Modifier.align(Alignment.Center))
        }
    }
}

/** Shows the accepted photo, or why capture did not succeed, with a way to try again. */
@Composable
private fun ResultView(state: CaptureUiState, onRetake: () -> Unit) {
    if (state is CaptureUiState.PhotoAccepted) {
        val verdict = speciesVerdict(state.species)
        Column(
            modifier = Modifier.fillMaxSize().safeDrawingPadding().padding(16.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text(verdict.title, color = verdict.color, style = MaterialTheme.typography.titleMedium)
            Text(verdict.detail)
            Image(
                bitmap = state.photo.asImageBitmap(),
                contentDescription = verdict.title,
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
