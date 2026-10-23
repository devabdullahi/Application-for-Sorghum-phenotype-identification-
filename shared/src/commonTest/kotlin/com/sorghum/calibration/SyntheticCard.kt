package com.sorghum.calibration

import com.sorghum.imaging.PixelImage
import com.sorghum.imaging.Rgb
import com.sorghum.imaging.pixelImage
import kotlin.math.roundToInt

/**
 * A hand-drawn ColorChecker on a plain board, for detection tests. Geometry is in image pixels;
 * the card is drawn upright and axis-aligned, rotated in 90° steps by [rotationDegrees]
 * (clockwise, relative to the reference landscape layout with dark skin top-left).
 *
 * @param gapPx black gap between neighbouring patches; half of it also borders the outer patches.
 * @param frameMarginPx black card frame outside the patch grid.
 */
internal data class SyntheticCard(
    val pitchXPx: Int = 24,
    val pitchYPx: Int = 24,
    val gapPx: Int = 4,
    val frameMarginPx: Int = 6,
    val leftPx: Int = 30,
    val topPx: Int = 40,
    val rotationDegrees: Int = 0,
) {
    val isPortrait: Boolean get() = rotationDegrees == 90 || rotationDegrees == 270
    val columnsInImage: Int get() = if (isPortrait) 4 else 6
    val rowsInImage: Int get() = if (isPortrait) 6 else 4

    /** Centre of the image cell at ([column], [row]), in image pixels. */
    fun cellCentre(column: Int, row: Int): Pair<Double, Double> = Pair(
        leftPx + frameMarginPx + (column + 0.5) * pitchXPx,
        topPx + frameMarginPx + (row + 0.5) * pitchYPx,
    )
}

/** Board colour: a light, slightly warm plain board. */
internal val BOARD = Rgb(215, 210, 200)

/** Card frame and gap colour. */
internal val CARD_FRAME = Rgb(30, 30, 30)

/** A leaf-green colour for occluders. */
internal val LEAF = Rgb(60, 140, 50)

/**
 * Which reference patch sits in image cell ([column], [row]) for each card rotation. Written
 * out per rotation (not derived from production code) so the test checks the mapping.
 */
internal fun referenceIndexAt(column: Int, row: Int, rotationDegrees: Int): Int {
    val (referenceRow, referenceColumn) = when (rotationDegrees) {
        0 -> Pair(row, column)
        180 -> Pair(3 - row, 5 - column)
        // Clockwise quarter turn: reference bottom-left (white) ends up top-left.
        90 -> Pair(3 - column, row)
        270 -> Pair(column, 5 - row)
        else -> error("Unsupported rotation $rotationDegrees")
    }
    return referenceRow * 6 + referenceColumn
}

/**
 * The camera's colour cast used in tests: channel gains below 1, some cross-talk and a black
 * offset, all in linear light. Gains stay low enough that no reference patch clips at white.
 */
internal fun applyTestCast(colour: LinearRgb): LinearRgb = LinearRgb(
    red = 0.70 * colour.red + 0.05 * colour.green + 0.00 * colour.blue + 0.02,
    green = 0.03 * colour.red + 0.85 * colour.green + 0.02 * colour.blue + 0.02,
    blue = 0.00 * colour.red + 0.05 * colour.green + 0.80 * colour.blue + 0.03,
)

/** Encodes a linear colour to 8-bit sRGB, clipping out-of-gamut values as a camera would. */
internal fun encodeTo8Bit(colour: LinearRgb): Rgb {
    fun channel(value: Double) = (linearToSrgb(value.coerceIn(0.0, 1.0)) * 255).roundToInt()
    return Rgb(channel(colour.red), channel(colour.green), channel(colour.blue))
}

/** 8-bit colour of reference patch [referenceIndex] as the test camera records it. */
internal fun castPatchColour(referenceIndex: Int): Rgb =
    encodeTo8Bit(applyTestCast(ColorCheckerClassicMini.referenceLinearRgb[referenceIndex]))

/**
 * Draws [card] on a [widthPx] x [heightPx] board. Patch pixels get a checkerboard of
 * +-[noiseLevels] on every channel, so each patch's per-channel standard deviation is
 * [noiseLevels] (less where a channel clips at 0 or 255). [occluder] can paint over any pixel last.
 */
internal fun renderCardPhoto(
    widthPx: Int,
    heightPx: Int,
    card: SyntheticCard,
    noiseLevels: Int = 0,
    patchColour: (referenceIndex: Int) -> Rgb = ::castPatchColour,
    occluder: (x: Int, y: Int) -> Rgb? = { _, _ -> null },
): PixelImage = pixelImage(widthPx, heightPx) { x, y ->
    occluder(x, y) ?: cardPixel(x, y, card, noiseLevels, patchColour) ?: BOARD
}

private fun cardPixel(x: Int, y: Int, card: SyntheticCard, noiseLevels: Int, patchColour: (Int) -> Rgb): Rgb? {
    val gridLeft = card.leftPx + card.frameMarginPx
    val gridTop = card.topPx + card.frameMarginPx
    val gridRight = gridLeft + card.columnsInImage * card.pitchXPx
    val gridBottom = gridTop + card.rowsInImage * card.pitchYPx
    val isOnCard = x >= card.leftPx && x < gridRight + card.frameMarginPx &&
        y >= card.topPx && y < gridBottom + card.frameMarginPx
    if (!isOnCard) return null
    if (x < gridLeft || x >= gridRight || y < gridTop || y >= gridBottom) return CARD_FRAME

    val column = (x - gridLeft) / card.pitchXPx
    val row = (y - gridTop) / card.pitchYPx
    val xInCell = (x - gridLeft) % card.pitchXPx
    val yInCell = (y - gridTop) % card.pitchYPx
    val halfGap = card.gapPx / 2
    val isInGap = xInCell < halfGap || xInCell >= card.pitchXPx - (card.gapPx - halfGap) ||
        yInCell < halfGap || yInCell >= card.pitchYPx - (card.gapPx - halfGap)
    if (isInGap) return CARD_FRAME

    val base = patchColour(referenceIndexAt(column, row, card.rotationDegrees))
    val offset = if ((x + y) % 2 == 0) noiseLevels else -noiseLevels
    return Rgb(
        (base.red + offset).coerceIn(0, 255),
        (base.green + offset).coerceIn(0, 255),
        (base.blue + offset).coerceIn(0, 255),
    )
}
