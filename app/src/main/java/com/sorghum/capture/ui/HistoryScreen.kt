package com.sorghum.capture.ui

import android.text.format.DateFormat
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.sorghum.capture.R
import com.sorghum.species.SpeciesCheck
import java.util.Date

/** The History tab: a summary of this session's results, then each accepted photo, newest first. */
@Composable
fun HistoryScreen(entries: List<HistoryEntry>) {
    Column(Modifier.fillMaxSize().safeDrawingPadding()) {
        Text(
            text = stringResource(R.string.tab_history),
            style = MaterialTheme.typography.headlineSmall,
            modifier = Modifier.padding(16.dp),
        )
        if (entries.isEmpty()) {
            Box(Modifier.fillMaxSize().padding(24.dp), contentAlignment = Alignment.Center) {
                Text(stringResource(R.string.history_empty), textAlign = TextAlign.Center)
            }
            return@Column
        }

        Text(
            text = historySummary(entries),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 16.dp),
        )
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            items(entries) { entry -> HistoryRow(entry) }
        }
    }
}

/** One photo with its species result and the time it was taken. */
@Composable
private fun HistoryRow(entry: HistoryEntry) {
    val verdict = speciesVerdict(entry.species)
    val image = remember(entry.photo) { entry.photo.asImageBitmap() }
    Card(Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier.padding(12.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Image(
                bitmap = image,
                contentDescription = verdict.title,
                contentScale = ContentScale.Crop,
                modifier = Modifier.size(72.dp).clip(RoundedCornerShape(8.dp)),
            )
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(verdict.title, color = verdict.color, style = MaterialTheme.typography.titleMedium)
                Text(verdict.detail, style = MaterialTheme.typography.bodyMedium)
                Text(
                    text = captureTime(entry.capturedAtEpochMillis),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

/** E.g. "4 photos · 2 sorghum · 1 not sorghum · 1 to retake". Outcomes with no photos are left out. */
@Composable
private fun historySummary(entries: List<HistoryEntry>): String {
    val sorghumCount = entries.count { it.species is SpeciesCheck.Sorghum }
    val notSorghumCount = entries.count { it.species is SpeciesCheck.NotSorghum }
    val retakeCount = entries.count { it.species is SpeciesCheck.Unsure || it.species == SpeciesCheck.NoPlant }
    val notCheckedCount = entries.count { it.species == SpeciesCheck.Unavailable }

    val parts = buildList {
        add(pluralStringResource(R.plurals.history_photo_count, entries.size, entries.size))
        if (sorghumCount > 0) add(stringResource(R.string.history_sorghum_count, sorghumCount))
        if (notSorghumCount > 0) add(stringResource(R.string.history_not_sorghum_count, notSorghumCount))
        if (retakeCount > 0) add(stringResource(R.string.history_retake_count, retakeCount))
        if (notCheckedCount > 0) add(stringResource(R.string.history_not_checked_count, notCheckedCount))
    }
    return parts.joinToString(" · ")
}

/** Time of day in the user's 12- or 24-hour format. History only covers this session, so no date. */
@Composable
private fun captureTime(epochMillis: Long): String =
    DateFormat.getTimeFormat(LocalContext.current).format(Date(epochMillis))
