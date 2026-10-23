package com.sorghum.calibration

import com.sorghum.imaging.PixelImage
import kotlin.math.abs

/**
 * An affine colour transform in linear sRGB, fitted to the colour card:
 * corrected = M * measured + offset, with M 3x3 and offset 3x1 (a 3x4 matrix).
 *
 * Affine rather than purely linear (3x3) because the offset absorbs lens flare and the
 * camera's black level, which lift dark patches; PlantCV's `affine_color_correction` uses the
 * same model. Unlike PlantCV we fit in linear light: the camera's errors (white balance,
 * exposure, channel cross-talk) are linear there, so a 3x4 matrix can actually undo them.
 *
 * Not a data class: [coefficients] is an array.
 *
 * @param coefficients 12 values, row-major: row c is (m_cR, m_cG, m_cB, offset_c) for output
 *   channel c in R, G, B order.
 * @param meanDeltaE mean CIE76 ΔE between the corrected card patches and their reference
 *   values: how well the fit explains the card. Higher means a worse fit.
 */
class ColourCorrection internal constructor(
    private val coefficients: DoubleArray,
    val meanDeltaE: Float,
) {
    init {
        require(coefficients.size == AFFINE_COEFFICIENT_COUNT) {
            "Expected $AFFINE_COEFFICIENT_COUNT coefficients, got ${coefficients.size}"
        }
    }

    /** Corrects one linear colour. Not clipped: out-of-range values show the fit's behaviour. */
    fun correct(measured: LinearRgb): LinearRgb = LinearRgb(
        red = channel(0, measured),
        green = channel(1, measured),
        blue = channel(2, measured),
    )

    private fun channel(outputChannel: Int, measured: LinearRgb): Double {
        val row = outputChannel * 4
        return coefficients[row] * measured.red +
            coefficients[row + 1] * measured.green +
            coefficients[row + 2] * measured.blue +
            coefficients[row + 3]
    }
}

/**
 * A colour-corrected photo, as later trait readers consume it.
 *
 * @param correctedLinearRgb row-major, 3 floats per pixel (R, G, B) in linear sRGB, clamped
 *   to 0..1. Same layout as [PixelImage.rgb], so pixel indices carry over.
 */
class CorrectedImage(val width: Int, val height: Int, val correctedLinearRgb: FloatArray) {
    init {
        require(width > 0 && height > 0) { "Image must have positive size, was ${width}x$height" }
        require(correctedLinearRgb.size == width * height * CHANNELS) {
            "Expected ${width * height * CHANNELS} floats for ${width}x$height RGB, got ${correctedLinearRgb.size}"
        }
    }

    private companion object {
        const val CHANNELS = 3
    }
}

/**
 * Applies [correction] to every pixel of [image]: decode sRGB to linear, apply the affine
 * transform, clamp to 0..1. Clamping is deliberate: colours the card cannot vouch for (brighter
 * than its white or darker than its black after correction) are not meaningful to traits.
 */
fun applyColourCorrection(image: PixelImage, correction: ColourCorrection): CorrectedImage {
    val output = FloatArray(image.rgb.size)
    for (pixel in 0 until image.pixelCount) {
        val measured = LinearRgb(
            SRGB_TO_LINEAR_TABLE[image.redAt(pixel)],
            SRGB_TO_LINEAR_TABLE[image.greenAt(pixel)],
            SRGB_TO_LINEAR_TABLE[image.blueAt(pixel)],
        )
        val corrected = correction.correct(measured)
        val offset = pixel * PixelImage.BYTES_PER_PIXEL
        output[offset] = corrected.red.coerceIn(0.0, 1.0).toFloat()
        output[offset + 1] = corrected.green.coerceIn(0.0, 1.0).toFloat()
        output[offset + 2] = corrected.blue.coerceIn(0.0, 1.0).toFloat()
    }
    return CorrectedImage(image.width, image.height, output)
}

/** Linear value of each 8-bit sRGB level; avoids a pow() per channel per pixel. */
private val SRGB_TO_LINEAR_TABLE = DoubleArray(256) { level -> srgbToLinear(level / 255.0) }

private const val AFFINE_COEFFICIENT_COUNT = 12

/**
 * Least-squares fit of the affine transform that maps [measured] onto [reference] (both linear
 * sRGB, one entry per card patch, same order). Each output channel is fitted separately on the
 * design matrix [R G B 1], which is what PlantCV's pseudo-inverse solution computes too. The
 * fit's residual is then measured against [referenceLab], the same patches in Lab.
 *
 * Returns null when the patches do not determine a unique transform (for example all patches
 * measured the same colour), which only happens when what was sampled is not a colour card.
 */
internal fun fitAffineColourCorrection(
    measured: List<LinearRgb>,
    reference: List<LinearRgb>,
    referenceLab: List<LabColour>,
): ColourCorrection? {
    require(measured.size == reference.size && measured.size == referenceLab.size) {
        "Got ${measured.size} measured, ${reference.size} reference and ${referenceLab.size} Lab colours"
    }
    require(measured.size >= 4) { "An affine fit needs at least 4 colours, got ${measured.size}" }

    // Normal equations (AᵀA) w = Aᵀ t. AᵀA is the same 4x4 matrix for all three channels.
    val normalMatrix = Array(4) { DoubleArray(4) }
    val rightHandSides = Array(3) { DoubleArray(4) }
    for (index in measured.indices) {
        val row = doubleArrayOf(measured[index].red, measured[index].green, measured[index].blue, 1.0)
        val target = doubleArrayOf(reference[index].red, reference[index].green, reference[index].blue)
        for (i in 0 until 4) {
            for (j in 0 until 4) normalMatrix[i][j] += row[i] * row[j]
            for (channel in 0 until 3) rightHandSides[channel][i] += row[i] * target[channel]
        }
    }

    val coefficients = DoubleArray(AFFINE_COEFFICIENT_COUNT)
    for (channel in 0 until 3) {
        val solution = solveLinearSystem(normalMatrix, rightHandSides[channel]) ?: return null
        solution.copyInto(coefficients, destinationOffset = channel * 4)
    }
    val unscored = ColourCorrection(coefficients, meanDeltaE = 0f)
    return ColourCorrection(coefficients, meanDeltaE(unscored, measured, referenceLab).toFloat())
}

/**
 * Mean CIE76 ΔE between [measured] colours after [correction] and [referenceLab]. ΔE rather
 * than RMS in RGB because it is perceptual: 1 is about a just-noticeable difference, so a
 * threshold reads the same for dark and bright patches.
 */
private fun meanDeltaE(correction: ColourCorrection, measured: List<LinearRgb>, referenceLab: List<LabColour>): Double {
    return measured.indices.sumOf { index ->
        deltaE76(linearRgbToLabD50(correction.correct(measured[index])), referenceLab[index])
    } / measured.size
}

/**
 * Pivot magnitudes below this make the system singular. The normal matrix holds sums of 24
 * products of values in 0..1, so a real card gives pivots many orders of magnitude larger.
 */
private const val SINGULAR_PIVOT = 1e-10

/** Solves the small square system [matrix] x = [rightHandSide] by Gaussian elimination with partial pivoting; null if singular. */
private fun solveLinearSystem(matrix: Array<DoubleArray>, rightHandSide: DoubleArray): DoubleArray? {
    val size = rightHandSide.size
    val a = Array(size) { matrix[it].copyOf() }
    val b = rightHandSide.copyOf()

    for (column in 0 until size) {
        val pivotRow = (column until size).maxBy { abs(a[it][column]) }
        if (abs(a[pivotRow][column]) < SINGULAR_PIVOT) return null
        a[column] = a[pivotRow].also { a[pivotRow] = a[column] }
        b[column] = b[pivotRow].also { b[pivotRow] = b[column] }

        for (row in column + 1 until size) {
            val factor = a[row][column] / a[column][column]
            for (k in column until size) a[row][k] -= factor * a[column][k]
            b[row] -= factor * b[column]
        }
    }

    val solution = DoubleArray(size)
    for (row in size - 1 downTo 0) {
        var sum = b[row]
        for (k in row + 1 until size) sum -= a[row][k] * solution[k]
        solution[row] = sum / a[row][row]
    }
    return solution
}
