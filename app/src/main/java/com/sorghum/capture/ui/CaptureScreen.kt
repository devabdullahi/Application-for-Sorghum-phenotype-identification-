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
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.WindowInsetsSides
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.only
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.core.view.doOnLayout
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.sorghum.capture.R
import com.sorghum.capture.camera.CameraSession
import com.sorghum.capture.camera.SampleCoverageAnalyzer
import com.sorghum.capture.camera.TiltSensor
import com.sorghum.capture.camera.TiltSensorUnavailableException
import com.sorghum.capture.guidance.GuidanceState
import com.sorghum.capture.quality.RejectionReason
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.launch
import java.text.NumberFormat
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.roundToInt
import kotlin.math.sin

private const val TAG = "CaptureScreen"

/** The user's camera choices, from the flash button and Settings. */
data class CameraOptions(
    val isFlashEnabled: Boolean,
    val isGridShown: Boolean,
    /** False also while a sheet or the photo picker covers the camera, so no photo is taken unseen. */
    val isAutoCaptureEnabled: Boolean,
)

/** Side of the yellow square drawn where the user tapped to focus. */
private val FOCUS_SQUARE_SIZE = 76.dp

/** How far the user drags for one step of exposure compensation. */
private val EXPOSURE_DRAG_PER_STEP = 12.dp

/** How far the sun next to the focus square moves between darkest and brightest. */
private val EXPOSURE_SUN_TRAVEL = 40.dp

/** The focus square fades this long after the last tap or exposure drag, as on the iPhone. */
private const val FOCUS_SQUARE_VISIBLE_MILLIS = 2_000L

/**
 * The full-screen camera: live preview, then either the accepted photo
 * with its species result or the rejection reason. The corner buttons are drawn over it by
 * [HomeScreen].
 */
@Composable
fun CaptureApp(viewModel: CaptureViewModel, options: CameraOptions) {
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

    val state by viewModel.uiState.collectAsStateWithLifecycle()
    val currentState = state
    val isCheckingPhoto = currentState is CaptureUiState.CheckingPhoto
    // One branch for both states so the camera is not restarted while the photo is checked.
    val isLive = currentState is CaptureUiState.Guiding || isCheckingPhoto
    when {
        !isLive -> ResultView(currentState, onRetake = viewModel::retake)
        // Without the camera, a photo uploaded from the gallery can still be checked.
        !hasCameraPermission && isCheckingPhoto -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            CircularProgressIndicator(color = Color.White)
        }
        !hasCameraPermission -> MessageWithButton(
            message = stringResource(R.string.camera_permission_needed),
            buttonLabel = stringResource(R.string.grant_permission),
            onClick = { permissionLauncher.launch(Manifest.permission.CAMERA) },
        )
        else -> CameraPreview(
            viewModel,
            guidance = (currentState as? CaptureUiState.Guiding)?.guidance,
            isCheckingPhoto = isCheckingPhoto,
            options = options,
        )
    }
}

/**
 * Camera preview with one fixed instruction, the zoom label and the shutter. Live guidance
 * (level, hold) drives auto-capture but is not shown. The target frame is not drawn either:
 * photos are still cropped to it, and the instruction asks for the sample in the centre.
 */
@Composable
private fun CameraPreview(
    viewModel: CaptureViewModel,
    guidance: GuidanceState?,
    isCheckingPhoto: Boolean,
    options: CameraOptions,
) {
    val context = LocalContext.current
    val camera = remember { CameraSession(context) }
    DisposableEffect(camera) { onDispose { camera.close() } }
    LaunchedEffect(camera, options.isFlashEnabled) { camera.isFlashEnabled = options.isFlashEnabled }
    var zoomRatio by remember { mutableFloatStateOf(1f) }

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
    LaunchedEffect(guidance, options.isAutoCaptureEnabled) {
        if (options.isAutoCaptureEnabled && guidance == GuidanceState.READY) viewModel.captureAndCheckPhoto(camera)
    }

    // As in the iPhone camera: a top bar, the viewfinder, and a bottom bar with the shutter.
    // The viewfinder sits between the bars, so the target frame drawn in it is never covered by
    // the corner buttons ([HomeScreen]), whatever the screen's shape. The bars' sizes match the
    // corner buttons' positions.
    Column(Modifier.fillMaxSize()) {
        // Between the two top corner buttons, so it never covers them.
        val instructionSideInset = CAMERA_CONTROLS_EDGE_PADDING + GLASS_BUTTON_SIZE + 12.dp
        Box(
            contentAlignment = Alignment.Center,
            modifier = Modifier
                .fillMaxWidth()
                .windowInsetsPadding(WindowInsets.safeDrawing.only(WindowInsetsSides.Top + WindowInsetsSides.Horizontal))
                .padding(
                    top = CAMERA_CONTROLS_EDGE_PADDING,
                    bottom = CAMERA_BAR_GAP,
                    start = instructionSideInset,
                    end = instructionSideInset,
                )
                .heightIn(min = GLASS_BUTTON_SIZE),
        ) {
            Text(
                text = stringResource(R.string.capture_instruction),
                color = Color.White,
                style = MaterialTheme.typography.bodyMedium,
                textAlign = TextAlign.Center,
                modifier = Modifier
                    .liquidGlass(RoundedCornerShape(percent = 50))
                    .padding(horizontal = 16.dp, vertical = 6.dp),
            )
        }

        Box(Modifier.weight(1f).fillMaxWidth()) {
            CameraViewfinder(
                viewModel,
                camera,
                isCheckingPhoto,
                isGridShown = options.isGridShown,
                onZoomRatioChanged = { zoomRatio = it },
                modifier = Modifier.fillMaxSize(),
            )
            ZoomLabel(zoomRatio, Modifier.align(Alignment.BottomCenter).padding(bottom = CAMERA_BAR_GAP))
        }

        Box(
            contentAlignment = Alignment.Center,
            modifier = Modifier
                .fillMaxWidth()
                .windowInsetsPadding(WindowInsets.safeDrawing.only(WindowInsetsSides.Bottom + WindowInsetsSides.Horizontal))
                .padding(top = CAMERA_CONTROLS_EDGE_PADDING, bottom = CAMERA_CONTROLS_EDGE_PADDING),
        ) {
            ShutterButton(
                onClick = { viewModel.captureAndCheckPhoto(camera) },
                contentDescription = stringResource(R.string.shutter_button),
                isEnabled = !isCheckingPhoto,
            )
        }
    }
}

/**
 * Preview with the touch controls: tap to focus and meter, then drag up or down to brighten
 * or darken; pinch to zoom. The [PreviewView] and the overlays share this box, so tap
 * positions are in the preview's own pixels.
 */
@Composable
private fun CameraViewfinder(
    viewModel: CaptureViewModel,
    camera: CameraSession,
    isCheckingPhoto: Boolean,
    isGridShown: Boolean,
    onZoomRatioChanged: (Float) -> Unit,
    modifier: Modifier,
) {
    val lifecycleOwner = LocalLifecycleOwner.current
    val scope = rememberCoroutineScope()
    val exposureDragPerStepPx = with(LocalDensity.current) { EXPOSURE_DRAG_PER_STEP.toPx() }

    var focusPoint by remember { mutableStateOf<Offset?>(null) }
    var exposureSteps by remember { mutableIntStateOf(0) }
    var exposureDragPx by remember { mutableFloatStateOf(0f) }

    LaunchedEffect(focusPoint, exposureSteps) {
        if (focusPoint == null) return@LaunchedEffect
        delay(FOCUS_SQUARE_VISIBLE_MILLIS)
        focusPoint = null
    }

    Box(modifier) {
        AndroidView(
            modifier = Modifier.fillMaxSize(),
            factory = { viewContext ->
                PreviewView(viewContext).apply {
                    // A TextureView, not the default SurfaceView: PreviewView scales the preview
                    // up to fill this box, and a SurfaceView's surface is not clipped by its
                    // parent, so it spilled over the top and bottom bars and hid the controls.
                    implementationMode = PreviewView.ImplementationMode.COMPATIBLE
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

        if (isGridShown) Canvas(Modifier.fillMaxSize()) { drawThirdsGrid() }

        // Above the PreviewView, so touches reach these detectors and not the platform view.
        Box(
            Modifier
                .fillMaxSize()
                .pointerInput(camera) {
                    detectTapGestures { tapPoint ->
                        camera.focusAndMeterAt(tapPoint.x, tapPoint.y)
                        focusPoint = tapPoint
                        exposureSteps = 0
                        exposureDragPx = 0f
                    }
                }
                .pointerInput(camera) {
                    detectTransformGestures { _, pan, zoom, _ ->
                        if (zoom != 1f) {
                            onZoomRatioChanged(camera.zoomBy(zoom))
                        } else if (focusPoint != null) {
                            // Dragging up (negative y) brightens, as on the iPhone.
                            exposureDragPx -= pan.y
                            val requestedSteps = (exposureDragPx / exposureDragPerStepPx).roundToInt()
                            exposureSteps = camera.setExposureCompensation(requestedSteps)
                            // Past the end of the range, stop counting, so dragging back responds at once.
                            if (exposureSteps != requestedSteps) exposureDragPx = exposureSteps * exposureDragPerStepPx
                        }
                    }
                },
        )

        focusPoint?.let { point ->
            FocusSquare(point, exposurePosition(exposureSteps, camera.exposureCompensationRange))
        }

        if (isCheckingPhoto) {
            CircularProgressIndicator(color = Color.White, modifier = Modifier.align(Alignment.Center))
        }
    }
}

/** Where the exposure sits in its range, from -1 (darkest) to 1 (brightest); 0 without a range. */
private fun exposurePosition(steps: Int, range: IntRange?): Float {
    if (range == null) return 0f
    val largestStep = max(abs(range.first), abs(range.last))
    return if (largestStep == 0) 0f else steps.toFloat() / largestStep
}

/** Two vertical and two horizontal lines that split the view into thirds. */
private fun DrawScope.drawThirdsGrid() {
    val lineColor = Color.White.copy(alpha = 0.35f)
    val lineWidth = 1.dp.toPx()
    for (third in 1..2) {
        val x = size.width * third / 3f
        val y = size.height * third / 3f
        drawLine(lineColor, Offset(x, 0f), Offset(x, size.height), lineWidth)
        drawLine(lineColor, Offset(0f, y), Offset(size.width, y), lineWidth)
    }
}

/**
 * The yellow square centred on [center], with a sun beside it that rises as the photo gets
 * brighter. [exposurePosition] runs from -1 (darkest) to 1 (brightest).
 */
@Composable
private fun FocusSquare(center: Offset, exposurePosition: Float) {
    val density = LocalDensity.current
    val halfSquarePx = with(density) { (FOCUS_SQUARE_SIZE / 2).toPx() }
    Row(
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier.offset { IntOffset((center.x - halfSquarePx).roundToInt(), (center.y - halfSquarePx).roundToInt()) },
    ) {
        Box(Modifier.size(FOCUS_SQUARE_SIZE).border(1.5.dp, CAMERA_ACCENT_COLOR))
        val sunOffsetPx = with(density) { (-exposurePosition * EXPOSURE_SUN_TRAVEL.toPx() / 2).roundToInt() }
        Canvas(Modifier.size(20.dp).offset { IntOffset(0, sunOffsetPx) }) { drawSun(CAMERA_ACCENT_COLOR) }
    }
}

/** A small sun: a disc with eight rays, the iPhone's exposure symbol. */
private fun DrawScope.drawSun(color: Color) {
    val discRadius = size.minDimension * 0.22f
    val rayStart = size.minDimension * 0.32f
    val rayEnd = size.minDimension * 0.48f
    drawCircle(color, radius = discRadius)
    for (ray in 0 until 8) {
        val angle = ray * Math.PI / 4
        val direction = Offset(cos(angle).toFloat(), sin(angle).toFloat())
        drawLine(color, center + direction * rayStart, center + direction * rayEnd, strokeWidth = 1.5.dp.toPx())
    }
}

/** The current zoom in a small glass circle above the shutter, e.g. "1×" or "2.5×". */
@Composable
private fun ZoomLabel(zoomRatio: Float, modifier: Modifier = Modifier) {
    val formattedRatio = remember(zoomRatio) {
        NumberFormat.getNumberInstance().apply { maximumFractionDigits = 1 }.format(zoomRatio)
    }
    Box(contentAlignment = Alignment.Center, modifier = modifier.size(40.dp).liquidGlass(CircleShape)) {
        Text(
            text = stringResource(R.string.zoom_ratio, formattedRatio),
            color = CAMERA_ACCENT_COLOR,
            style = MaterialTheme.typography.labelMedium,
        )
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
        Text(message, textAlign = TextAlign.Center)
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
