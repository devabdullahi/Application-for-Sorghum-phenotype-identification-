package com.sorghum.capture.ui

import androidx.annotation.DrawableRes
import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.consumeWindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.sorghum.capture.R

/** Bottom bar tabs, in the order they are shown. */
private enum class HomeTab(@param:StringRes val label: Int, @param:DrawableRes val icon: Int) {
    HISTORY(R.string.tab_history, R.drawable.ic_tab_history),
    CAPTURE(R.string.tab_capture, R.drawable.ic_tab_capture),
    SETTINGS(R.string.tab_settings, R.drawable.ic_tab_settings),
}

/**
 * The app's top level: a bottom bar with History, Capture and Settings. Capture is selected on
 * launch because photographing a sample is the main task.
 */
@Composable
fun HomeScreen(captureViewModel: CaptureViewModel = viewModel()) {
    var selectedTab by rememberSaveable { mutableStateOf(HomeTab.CAPTURE) }
    val history by captureViewModel.history.collectAsStateWithLifecycle()

    Scaffold(
        // Each tab pads for the status bar itself, so the camera preview can reach the top edge.
        contentWindowInsets = WindowInsets(0),
        bottomBar = {
            NavigationBar {
                HomeTab.entries.forEach { tab ->
                    NavigationBarItem(
                        selected = tab == selectedTab,
                        onClick = { selectedTab = tab },
                        icon = { Icon(painterResource(tab.icon), contentDescription = null) },
                        label = { Text(stringResource(tab.label)) },
                    )
                }
            }
        },
    ) { innerPadding ->
        // Consumed so the tabs' own safeDrawingPadding does not add the bar height again.
        Box(Modifier.fillMaxSize().padding(innerPadding).consumeWindowInsets(innerPadding)) {
            // Leaving the Capture tab removes CaptureApp from composition, which closes the camera.
            when (selectedTab) {
                HomeTab.HISTORY -> HistoryScreen(history)
                HomeTab.CAPTURE -> CaptureApp(captureViewModel)
                HomeTab.SETTINGS -> SettingsScreen()
            }
        }
    }
}
