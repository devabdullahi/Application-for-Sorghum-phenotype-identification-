package com.sorghum.capture.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.sorghum.capture.R

/**
 * Settings, shown in a bottom sheet. The choices last for this session only: nothing is
 * stored on the device. The species check row is information, not a choice: it announces
 * when no model is installed (ARCHITECTURE.md section 4.3).
 */
@Composable
fun SettingsScreen(
    isGridShown: Boolean,
    onGridShownChange: (Boolean) -> Unit,
    isAutoCaptureEnabled: Boolean,
    onAutoCaptureEnabledChange: (Boolean) -> Unit,
    isSpeciesCheckAvailable: Boolean,
    hasRecentResults: Boolean,
    onClearRecentResults: () -> Unit,
) {
    Column(Modifier.fillMaxWidth().padding(bottom = 24.dp)) {
        Text(
            text = stringResource(R.string.settings_title),
            style = MaterialTheme.typography.headlineSmall,
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
        )
        SwitchRow(
            title = stringResource(R.string.setting_grid),
            detail = stringResource(R.string.setting_grid_detail),
            isChecked = isGridShown,
            onCheckedChange = onGridShownChange,
        )
        HorizontalDivider(Modifier.padding(horizontal = 16.dp))
        SwitchRow(
            title = stringResource(R.string.setting_auto_capture),
            detail = stringResource(R.string.setting_auto_capture_detail),
            isChecked = isAutoCaptureEnabled,
            onCheckedChange = onAutoCaptureEnabledChange,
        )
        HorizontalDivider(Modifier.padding(horizontal = 16.dp))
        SettingText(
            title = stringResource(R.string.setting_species_check),
            detail = stringResource(
                if (isSpeciesCheckAvailable) R.string.setting_species_check_installed else R.string.setting_species_check_missing
            ),
            modifier = Modifier.padding(16.dp),
        )
        OutlinedButton(
            onClick = onClearRecentResults,
            enabled = hasRecentResults,
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
        ) {
            Text(stringResource(R.string.clear_recent_results))
        }
    }
}

@Composable
private fun SwitchRow(title: String, detail: String, isChecked: Boolean, onCheckedChange: (Boolean) -> Unit) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(16.dp),
        modifier = Modifier.fillMaxWidth().padding(16.dp),
    ) {
        SettingText(title, detail, Modifier.weight(1f))
        Switch(checked = isChecked, onCheckedChange = onCheckedChange)
    }
}

@Composable
private fun SettingText(title: String, detail: String, modifier: Modifier = Modifier) {
    Column(modifier, verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Text(title, style = MaterialTheme.typography.titleMedium)
        Text(detail, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}
