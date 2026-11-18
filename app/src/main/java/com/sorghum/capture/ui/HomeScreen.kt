package com.sorghum.capture.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.sorghum.capture.R
import com.sorghum.capture.camera.hasBackCameraFlash

/** The sheets the corner buttons open over the camera. At most one is open. */
private enum class HomeSheet { RECENT_RESULTS, SETTINGS }

/**
 * The app's top level, laid out like the iPhone camera: a full-screen camera with a round
 * glass button in each corner. Recent results (top left), flash (top right), upload from the
 * gallery (bottom left) and settings (bottom right).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(captureViewModel: CaptureViewModel = viewModel()) {
    var isFlashEnabled by rememberSaveable { mutableStateOf(false) }
    var isGridShown by rememberSaveable { mutableStateOf(false) }
    var isAutoCaptureEnabled by rememberSaveable { mutableStateOf(true) }
    var openSheet by rememberSaveable { mutableStateOf<HomeSheet?>(null) }
    var isPickingPhoto by remember { mutableStateOf(false) }
    val context = LocalContext.current
    val hasFlash = remember { hasBackCameraFlash(context) }
    val history by captureViewModel.history.collectAsStateWithLifecycle()
    val state by captureViewModel.uiState.collectAsStateWithLifecycle()

    // The system photo picker needs no storage permission and grants access to the picked photo only.
    val photoPicker = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { photoUri ->
        isPickingPhoto = false
        if (photoUri != null) captureViewModel.analyzeLibraryPhoto(photoUri)
    }

    Box(Modifier.fillMaxSize().background(Color.Black)) {
        CaptureApp(
            captureViewModel,
            CameraOptions(
                isFlashEnabled = isFlashEnabled && hasFlash,
                isGridShown = isGridShown,
                isAutoCaptureEnabled = isAutoCaptureEnabled && openSheet == null && !isPickingPhoto,
            ),
        )
        // A result screen has its own button to go back to the camera, so the corners stay clear.
        if (isWaitingForPhoto(state)) {
            CornerButtons(
                hasFlash = hasFlash,
                isFlashEnabled = isFlashEnabled && hasFlash,
                isUploadEnabled = state !is CaptureUiState.CheckingPhoto,
                onRecentResultsClick = { openSheet = HomeSheet.RECENT_RESULTS },
                onFlashClick = { isFlashEnabled = !isFlashEnabled },
                onUploadClick = {
                    isPickingPhoto = true
                    photoPicker.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
                },
                onSettingsClick = { openSheet = HomeSheet.SETTINGS },
            )
        }
    }

    when (openSheet) {
        HomeSheet.RECENT_RESULTS -> ModalBottomSheet(
            onDismissRequest = { openSheet = null },
            sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
        ) {
            HistoryScreen(history)
        }
        HomeSheet.SETTINGS -> ModalBottomSheet(onDismissRequest = { openSheet = null }) {
            SettingsScreen(
                isGridShown = isGridShown,
                onGridShownChange = { isGridShown = it },
                isAutoCaptureEnabled = isAutoCaptureEnabled,
                onAutoCaptureEnabledChange = { isAutoCaptureEnabled = it },
                isSpeciesCheckAvailable = captureViewModel.isSpeciesCheckAvailable,
                hasRecentResults = history.isNotEmpty(),
                onClearRecentResults = captureViewModel::clearHistory,
            )
        }
        null -> Unit
    }
}

/**
 * True while the camera, or the message saying why it cannot run, is showing. A gallery photo
 * can still be uploaded from the camera-unavailable messages.
 */
private fun isWaitingForPhoto(state: CaptureUiState): Boolean = when (state) {
    is CaptureUiState.Guiding,
    CaptureUiState.CheckingPhoto,
    CaptureUiState.CameraUnavailable,
    CaptureUiState.LevelSensorUnavailable -> true
    is CaptureUiState.PhotoAccepted,
    is CaptureUiState.PhotoRejected,
    CaptureUiState.CaptureFailed -> false
}

/** The four glass buttons. The bottom two are lifted to line up with the shutter's centre. */
@Composable
private fun CornerButtons(
    hasFlash: Boolean,
    isFlashEnabled: Boolean,
    isUploadEnabled: Boolean,
    onRecentResultsClick: () -> Unit,
    onFlashClick: () -> Unit,
    onUploadClick: () -> Unit,
    onSettingsClick: () -> Unit,
) {
    // No pointer handling of its own, so touches between the buttons reach the camera below.
    Box(Modifier.fillMaxSize().safeDrawingPadding().padding(CAMERA_CONTROLS_EDGE_PADDING)) {
        GlassCircleButton(
            icon = R.drawable.ic_recent_results,
            contentDescription = stringResource(R.string.recent_results_button),
            onClick = onRecentResultsClick,
            modifier = Modifier.align(Alignment.TopStart),
        )
        GlassCircleButton(
            icon = if (isFlashEnabled) R.drawable.ic_flash_on else R.drawable.ic_flash_off,
            contentDescription = stringResource(
                when {
                    !hasFlash -> R.string.flash_unavailable
                    isFlashEnabled -> R.string.flash_turn_off
                    else -> R.string.flash_turn_on
                }
            ),
            onClick = onFlashClick,
            isActive = isFlashEnabled,
            isEnabled = hasFlash,
            modifier = Modifier.align(Alignment.TopEnd),
        )
        GlassCircleButton(
            icon = R.drawable.ic_upload,
            contentDescription = stringResource(R.string.upload_button),
            onClick = onUploadClick,
            isEnabled = isUploadEnabled,
            modifier = Modifier.align(Alignment.BottomStart).padding(bottom = BOTTOM_CORNER_BUTTON_LIFT),
        )
        GlassCircleButton(
            icon = R.drawable.ic_settings,
            contentDescription = stringResource(R.string.settings_button),
            onClick = onSettingsClick,
            modifier = Modifier.align(Alignment.BottomEnd).padding(bottom = BOTTOM_CORNER_BUTTON_LIFT),
        )
    }
}
