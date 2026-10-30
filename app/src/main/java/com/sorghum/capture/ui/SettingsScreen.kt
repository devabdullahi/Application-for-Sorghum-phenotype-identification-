package com.sorghum.capture.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.sorghum.capture.R

/** The Settings tab. Empty for now; only the title is shown. */
@Composable
fun SettingsScreen() {
    Column(Modifier.fillMaxSize().safeDrawingPadding()) {
        Text(
            text = stringResource(R.string.tab_settings),
            style = MaterialTheme.typography.headlineSmall,
            modifier = Modifier.padding(16.dp),
        )
    }
}
