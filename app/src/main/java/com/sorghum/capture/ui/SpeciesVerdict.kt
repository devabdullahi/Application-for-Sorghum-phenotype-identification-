package com.sorghum.capture.ui

import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import com.sorghum.capture.R
import com.sorghum.species.SpeciesCheck
import java.text.NumberFormat

/** How a species result reads on screen. */
internal class SpeciesVerdict(val title: String, val detail: String, val color: Color)

/**
 * Wording and colour for a species result, shared by the result screen and History. Only
 * presentation: the decision itself was made in the shared core. Mirrors `speciesVerdict` in
 * `ios/SorghumCapture/UI/CaptureScreen.swift`.
 */
@Composable
internal fun speciesVerdict(species: SpeciesCheck): SpeciesVerdict = when (species) {
    is SpeciesCheck.Sorghum -> SpeciesVerdict(
        title = stringResource(R.string.species_sorghum_title),
        detail = stringResource(R.string.species_sorghum_detail, wholePercent(species.sorghumProbability)),
        color = VERDICT_GOOD_COLOR,
    )
    is SpeciesCheck.NotSorghum -> SpeciesVerdict(
        title = stringResource(R.string.species_not_sorghum_title),
        detail = species.lookAlikeClassId
            ?.let { stringResource(R.string.species_look_alike_detail, lookAlikeName(it)) }
            ?: stringResource(R.string.species_not_sorghum_detail),
        color = VERDICT_STOP_COLOR,
    )
    SpeciesCheck.NoPlant -> SpeciesVerdict(
        title = stringResource(R.string.species_no_plant_title),
        detail = stringResource(R.string.species_no_plant_detail),
        color = VERDICT_STOP_COLOR,
    )
    is SpeciesCheck.Unsure -> SpeciesVerdict(
        title = stringResource(R.string.species_unsure_title),
        detail = stringResource(R.string.species_unsure_detail),
        color = VERDICT_UNSURE_COLOR,
    )
    SpeciesCheck.Unavailable -> SpeciesVerdict(
        title = stringResource(R.string.photo_accepted),
        detail = stringResource(R.string.species_unavailable_detail),
        color = Color.Unspecified,
    )
}

// Light tints, because the app uses a dark colour scheme (see MainActivity).
private val VERDICT_GOOD_COLOR = Color(0xFF81C784)
private val VERDICT_STOP_COLOR = Color(0xFFFFB74D)
private val VERDICT_UNSURE_COLOR = Color(0xFFFFD54F)

/** A probability as a whole percentage in the user's locale, e.g. "93%". */
private fun wholePercent(probability: Float): String = NumberFormat.getPercentInstance().format(probability)

/**
 * Display name for one of the model's look-alike class ids
 * (`model/sorghum_model/species_classes.py`). An id the app does not know yet is shown with
 * spaces instead of underscores, as on iOS, rather than hidden.
 */
@Composable
private fun lookAlikeName(classId: String): String = when (classId) {
    "johnson_grass" -> stringResource(R.string.look_alike_johnson_grass)
    "maize" -> stringResource(R.string.look_alike_maize)
    "sugarcane" -> stringResource(R.string.look_alike_sugarcane)
    "pearl_millet" -> stringResource(R.string.look_alike_pearl_millet)
    "finger_millet" -> stringResource(R.string.look_alike_finger_millet)
    else -> classId.replace('_', ' ')
}
