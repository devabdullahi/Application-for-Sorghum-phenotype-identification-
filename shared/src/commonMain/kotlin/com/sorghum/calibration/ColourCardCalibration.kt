package com.sorghum.calibration

import com.sorghum.imaging.NormalizedRect
import com.sorghum.imaging.PixelImage
import com.sorghum.imaging.PixelRect
import kotlin.math.abs
import kotlin.math.ceil
import kotlin.math.floor
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.sqrt

/**
 * One card patch as found in the photo.
 *
 * @param referenceIndex the patch's position in [ColorCheckerClassicMini] order, whatever the
 *   card's rotation in the photo.
 * @param sampleRect the square of pixels averaged, in image pixels.
 * @param meanSrgb mean camera colour over [sampleRect], 8-bit sRGB.
 * @param channelStdDev the largest of the R, G and B standard deviations (0–255) over
 *   [sampleRect]. Per channel rather than luma, because a green leaf over a red patch can have
 *   the same brightness as the patch and would be invisible in luma.
 */
internal data class CardPatch(
    val referenceIndex: Int,
    val sampleRect: PixelRect,
    val meanSrgb: SrgbColour,
    val channelStdDev: Float,
)

/**
 * The card found in a photo.
 *
 * @param patches all 24 patches, in reference order.
 * @param rotationDegrees how the card lies in the photo, clockwise from the reference layout
 *   (landscape, dark skin top-left): 0, 90, 180 or 270.
 * @param patchPitchPx mean of the horizontal and vertical patch pitch, in image pixels.
 * @param pitchMismatch |horizontal - vertical pitch| / mean pitch; 0 for a card seen square-on.
 * @param gridEdgeContrast how clearly the grid stood out (see [ColourCardSettings.minGridEdgeContrast]);
 *   the weaker of the two axes.
 */
internal data class DetectedColourCard(
    val patches: List<CardPatch>,
    val rotationDegrees: Int,
    val patchPitchPx: Float,
    val pitchMismatch: Float,
    val gridEdgeContrast: Float,
)

/** Why no usable colour card was found. Each maps to a user message; all mean "retake". */
internal enum class CardNotFoundReason {
    /** No regular 4 x 6 grid in the card region: card missing, out of the slot, or too small. */
    NO_GRID,

    /** The grid's patches are not square: the card is tilted towards the camera. */
    UNEVEN_GRID,

    /** A patch is not one flat colour: something covers it, or glare or a shadow edge crosses it. */
    PATCH_NOT_UNIFORM,

    /** The patch colours do not match the card's under any colour correction: the card is misread or partly hidden. */
    POOR_COLOUR_FIT,
}

/**
 * The calibration step's result for one photo. The session acts on it: per ARCHITECTURE.md
 * section 4.3, [NotFound] rejects the photo, because colour traits are meaningless without
 * correction.
 */
internal sealed interface ColourCardCalibration {
    /**
     * The card was found and fits.
     *
     * @param pixelsPerMm image pixels per mm, at the card's distance from the camera and in the
     *   image that was passed in. Valid for a sample lying flat on the board next to the card.
     */
    data class Calibrated(
        val card: DetectedColourCard,
        val correction: ColourCorrection,
        val pixelsPerMm: Float,
    ) : ColourCardCalibration

    /** No usable card; the photo must be retaken. */
    data class NotFound(val reason: CardNotFoundReason) : ColourCardCalibration
}

/**
 * Finds the ColorChecker Classic Mini in [cardRegion] of [image], fits a colour correction to
 * its patches, and measures the mm scale from its patch pitch.
 *
 * ASSUMPTION — confirm: the card lies in a known slot on the board, so the capture layout can
 * pass that slot as [cardRegion], and lies roughly square to the photo (any of the four 90°
 * turns). Searching a known slot keeps detection simple and fast and avoids mistaking the
 * sample for the card; finding a card anywhere at any angle would need a general quadrilateral
 * detector, which is not justified until real photos show the slot is impractical.
 *
 * Steps, each with its own failure reason, run for both a landscape (6 x 4) and a portrait
 * (4 x 6) grid: find a regular grid of colour edges → check the patches are square → sample the
 * middle of each patch and check it is uniform → fit the colour correction for each possible
 * card orientation and keep the best → check the fit. The best-fitting result wins.
 *
 * Pure and synchronous; run it on the session's background worker. Cost grows with the square
 * of the region size, and the pixel thresholds in [ColourCardSettings] assume a photo
 * downscaled to [CALIBRATION_LONG_SIDE_PIXELS] on the long side; scale
 * [ColourCardCalibration.Calibrated.pixelsPerMm] to other resolutions.
 *
 * @param image the upright photo.
 * @param cardRegion where the card slot is, in fractions of [image].
 */
internal fun calibrateWithColourCard(
    image: PixelImage,
    cardRegion: NormalizedRect,
    settings: ColourCardSettings = ColourCardSettings(),
): ColourCardCalibration {
    val region = cardRegion.toPixelRect(image)
    if (region.width < 2 || region.height < 2) return ColourCardCalibration.NotFound(CardNotFoundReason.NO_GRID)
    val columnProfile = edgeProfile(image, region, ProfileAxis.HORIZONTAL)
    val rowProfile = edgeProfile(image, region, ProfileAxis.VERTICAL)

    // A landscape card also shows a fair 4-column grid over four of its six columns, so the
    // grid contrast alone cannot pick the layout reliably. Try both and let the colour fit
    // decide; if neither works, report the failure of the clearer grid.
    val attempts = CardLayout.entries
        .mapNotNull { layout -> findCardGrid(columnProfile, rowProfile, layout, settings) }
        .sortedByDescending { it.edgeContrast }
        .map { grid -> calibrateOnGrid(image, region, grid, settings) }
    return attempts
        .filterIsInstance<ColourCardCalibration.Calibrated>()
        .minByOrNull { it.correction.meanDeltaE }
        ?: attempts.firstOrNull()
        ?: ColourCardCalibration.NotFound(CardNotFoundReason.NO_GRID)
}

/** Runs the checks and the fit on one candidate grid. */
private fun calibrateOnGrid(image: PixelImage, region: PixelRect, grid: CardGrid, settings: ColourCardSettings): ColourCardCalibration {
    if (grid.edgeContrast < settings.minGridEdgeContrast) return ColourCardCalibration.NotFound(CardNotFoundReason.NO_GRID)

    // The search limits apply to whole-pixel pitches; check them again on the refined grid.
    val meanPitch = (grid.columns.pitchPx + grid.rows.pitchPx) / 2
    val columnSpanFraction = grid.columns.pitchPx * grid.layout.columns / region.width
    val rowSpanFraction = grid.rows.pitchPx * grid.layout.rows / region.height
    val isTooSmall = meanPitch < settings.minPatchPitchPx ||
        min(columnSpanFraction, rowSpanFraction) < settings.minGridFractionOfHint
    if (isTooSmall) return ColourCardCalibration.NotFound(CardNotFoundReason.NO_GRID)
    val pitchMismatch = abs(grid.columns.pitchPx - grid.rows.pitchPx) / meanPitch
    if (pitchMismatch > settings.maxPitchMismatch) return ColourCardCalibration.NotFound(CardNotFoundReason.UNEVEN_GRID)

    val cellSamples = sampleCells(image, region, grid, settings)
    if (cellSamples.any { it.channelStdDev > settings.maxPatchChannelStdDev }) {
        return ColourCardCalibration.NotFound(CardNotFoundReason.PATCH_NOT_UNIFORM)
    }

    val bestFit = grid.layout.rotationsDegrees
        .mapNotNull { rotation -> fitForRotation(cellSamples, grid.layout, rotation) }
        .minByOrNull { it.correction.meanDeltaE }
    if (bestFit == null || !isColourFitAcceptable(bestFit.correction.meanDeltaE, settings)) {
        return ColourCardCalibration.NotFound(CardNotFoundReason.POOR_COLOUR_FIT)
    }

    val card = DetectedColourCard(
        patches = bestFit.patches,
        rotationDegrees = bestFit.rotationDegrees,
        patchPitchPx = meanPitch,
        pitchMismatch = pitchMismatch,
        gridEdgeContrast = grid.edgeContrast,
    )
    return ColourCardCalibration.Calibrated(card, bestFit.correction, meanPitch / ColorCheckerClassicMini.PATCH_PITCH_MM)
}

/**
 * Whether a colour fit with residual [meanDeltaE] is good enough to trust. Written so that it
 * fails closed: a NaN residual (from a numerically broken fit) compares false with everything,
 * so `meanDeltaE > max` would wrongly accept it.
 */
internal fun isColourFitAcceptable(meanDeltaE: Float, settings: ColourCardSettings): Boolean =
    meanDeltaE <= settings.maxMeanDeltaE

/**
 * How the card's grid lies in the photo. A landscape card (rotation 0 or 180) shows 6 columns
 * and 4 rows; a portrait one (90 or 270) shows 4 columns and 6 rows.
 */
private enum class CardLayout(val columns: Int, val rows: Int, val rotationsDegrees: List<Int>) {
    LANDSCAPE(ColorCheckerClassicMini.COLUMNS, ColorCheckerClassicMini.ROWS, listOf(0, 180)),
    PORTRAIT(ColorCheckerClassicMini.ROWS, ColorCheckerClassicMini.COLUMNS, listOf(90, 270)),
}

private class CardGrid(val layout: CardLayout, val columns: GridAxis, val rows: GridAxis) {
    /** Both axes must show a grid, so the weaker one decides. */
    val edgeContrast: Float get() = min(columns.edgeContrast, rows.edgeContrast)
}

/** The best grid for [layout] in the region's edge profiles; null if the grid cannot fit the region. */
private fun findCardGrid(
    columnProfile: FloatArray,
    rowProfile: FloatArray,
    layout: CardLayout,
    settings: ColourCardSettings,
): CardGrid? {
    val columns = findGridAxis(columnProfile, layout.columns, settings) ?: return null
    val rows = findGridAxis(rowProfile, layout.rows, settings) ?: return null
    return CardGrid(layout, columns, rows)
}

/** A sampled grid cell, before the card's orientation (and so each patch's identity) is known. */
private class CellSample(val column: Int, val row: Int, val rect: PixelRect, val meanSrgb: SrgbColour, val channelStdDev: Float)

/** Samples the middle of every grid cell, row by row. */
private fun sampleCells(image: PixelImage, region: PixelRect, grid: CardGrid, settings: ColourCardSettings): List<CellSample> {
    val pitch = min(grid.columns.pitchPx, grid.rows.pitchPx)
    val side = (pitch * settings.sampleFractionOfPitch).roundToInt().coerceAtLeast(1)
    val samples = ArrayList<CellSample>(ColorCheckerClassicMini.PATCH_COUNT)
    for (row in 0 until grid.layout.rows) {
        for (column in 0 until grid.layout.columns) {
            val centreX = region.left + grid.columns.startPx + (column + 0.5f) * grid.columns.pitchPx
            val centreY = region.top + grid.rows.startPx + (row + 0.5f) * grid.rows.pitchPx
            val left = (centreX - side / 2f).roundToInt().coerceIn(0, image.width - 1)
            val top = (centreY - side / 2f).roundToInt().coerceIn(0, image.height - 1)
            val rect = PixelRect(left, top, min(left + side, image.width), min(top + side, image.height))
            samples += sampleRect(image, rect, column, row)
        }
    }
    return samples
}

private fun sampleRect(image: PixelImage, rect: PixelRect, column: Int, row: Int): CellSample {
    val sums = DoubleArray(3)
    val squaredSums = DoubleArray(3)
    for (y in rect.top until rect.bottom) {
        for (x in rect.left until rect.right) {
            val pixel = y * image.width + x
            // Locals rather than an array: this loop runs for every sampled pixel.
            val red = image.redAt(pixel).toDouble()
            val green = image.greenAt(pixel).toDouble()
            val blue = image.blueAt(pixel).toDouble()
            sums[0] += red
            sums[1] += green
            sums[2] += blue
            squaredSums[0] += red * red
            squaredSums[1] += green * green
            squaredSums[2] += blue * blue
        }
    }
    val count = rect.width * rect.height
    val means = DoubleArray(3) { sums[it] / count }
    val largestVariance = (0 until 3).maxOf { (squaredSums[it] / count - means[it] * means[it]).coerceAtLeast(0.0) }
    return CellSample(
        column = column,
        row = row,
        rect = rect,
        meanSrgb = SrgbColour(means[0].toFloat(), means[1].toFloat(), means[2].toFloat()),
        channelStdDev = sqrt(largestVariance).toFloat(),
    )
}

private class OrientedFit(val rotationDegrees: Int, val patches: List<CardPatch>, val correction: ColourCorrection)

/**
 * Assigns cells to reference patches as if the card were turned by [rotationDegrees] and fits
 * the correction. Only the right orientation lets one affine map explain all 24 patches, so the
 * caller keeps the lowest residual; this avoids needing an orientation mark on the board.
 */
private fun fitForRotation(cells: List<CellSample>, layout: CardLayout, rotationDegrees: Int): OrientedFit? {
    val patches = List(ColorCheckerClassicMini.PATCH_COUNT) { referenceIndex ->
        val (column, row) = imageCellOf(referenceIndex, rotationDegrees)
        val cell = cells[row * layout.columns + column]
        CardPatch(referenceIndex, cell.rect, cell.meanSrgb, cell.channelStdDev)
    }
    val correction = fitAffineColourCorrection(
        measured = patches.map { it.meanSrgb.toLinear() },
        reference = ColorCheckerClassicMini.referenceLinearRgb,
        referenceLab = ColorCheckerClassicMini.referenceLabD50,
    ) ?: return null
    return OrientedFit(rotationDegrees, patches, correction)
}

/**
 * Image grid cell (column, row) of a reference patch when the card is turned clockwise by
 * [rotationDegrees]. Reference layout: 6 columns x 4 rows, index = row * 6 + column.
 */
private fun imageCellOf(referenceIndex: Int, rotationDegrees: Int): Pair<Int, Int> {
    val lastRow = ColorCheckerClassicMini.ROWS - 1
    val lastColumn = ColorCheckerClassicMini.COLUMNS - 1
    val row = referenceIndex / ColorCheckerClassicMini.COLUMNS
    val column = referenceIndex % ColorCheckerClassicMini.COLUMNS
    return when (rotationDegrees) {
        0 -> Pair(column, row)
        90 -> Pair(lastRow - row, column)
        180 -> Pair(lastColumn - column, lastRow - row)
        270 -> Pair(row, lastColumn - column)
        else -> error("Card rotation must be a multiple of 90°, was $rotationDegrees")
    }
}

/** Pixel bounds of a normalized rect in [image], rounded outwards so no part of the region is lost. */
private fun NormalizedRect.toPixelRect(image: PixelImage) = PixelRect(
    left = floor(left * image.width).toInt(),
    top = floor(top * image.height).toInt(),
    right = ceil(right * image.width).toInt().coerceAtMost(image.width),
    bottom = ceil(bottom * image.height).toInt().coerceAtMost(image.height),
)
