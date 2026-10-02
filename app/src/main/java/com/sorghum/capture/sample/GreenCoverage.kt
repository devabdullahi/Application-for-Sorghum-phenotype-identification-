package com.sorghum.capture.sample

import kotlin.math.max
import kotlin.math.min

/**
 * How much of an image region is covered by green plant tissue.
 *
 * @param greenFraction fraction of all pixels in the region that are green.
 * @param edgeGreenFraction fraction of pixels in the region's edge band that are green.
 *   A high value means the sample runs across the region's border, i.e. it is cut off.
 */
data class SampleCoverage(val greenFraction: Float, val edgeGreenFraction: Float)

/**
 * Thresholds for deciding whether a pixel is green plant tissue.
 *
 * @param minExcessGreen minimum excess-green index (see [isPlantPixel]). 0.1 separates leaves
 *   from grey, white, brown or black boards in typical indoor light; tune if the board is tinted.
 * @param minBrightnessSum pixels whose r + g + b is below this are ignored, because in very dark
 *   pixels sensor noise makes the colour ratios meaningless.
 * @param edgeBandFraction width of the edge band, as a fraction of the region's shorter side.
 */
data class GreenDetectionSettings(
    val minExcessGreen: Float = 0.1f,
    val minBrightnessSum: Int = 60,
    val edgeBandFraction: Float = 0.03f,
) {
    init {
        require(minBrightnessSum in 0..765) {
            "minBrightnessSum must be within 0..765, was $minBrightnessSum"
        }
        require(edgeBandFraction > 0f && edgeBandFraction < 0.5f) {
            "edgeBandFraction must be within (0, 0.5), was $edgeBandFraction"
        }
    }
}

/**
 * Measures green coverage of an image region given as packed ARGB pixels
 * (the format returned by android.graphics.Bitmap.getPixels), row by row.
 *
 * Used both on small live analysis frames and on the captured photo, so the live guidance
 * and the final check agree on what counts as "sample present".
 */
fun measureSampleCoverage(
    argbPixels: IntArray,
    width: Int,
    height: Int,
    settings: GreenDetectionSettings,
): SampleCoverage {
    require(width > 0 && height > 0) { "Region must have positive size, was ${width}x$height" }
    require(argbPixels.size == width * height) {
        "Expected ${width * height} pixels for ${width}x$height, got ${argbPixels.size}"
    }

    // Always at least one pixel wide, so tiny analysis frames still have an edge band.
    val edgeBand = max(1, (min(width, height) * settings.edgeBandFraction).toInt())

    var greenPixels = 0
    var edgePixels = 0
    var greenEdgePixels = 0
    for (y in 0 until height) {
        for (x in 0 until width) {
            val isGreen = isPlantPixel(argbPixels[y * width + x], settings)
            val isInEdgeBand = x < edgeBand || x >= width - edgeBand ||
                y < edgeBand || y >= height - edgeBand

            if (isGreen) greenPixels++
            if (isInEdgeBand) {
                edgePixels++
                if (isGreen) greenEdgePixels++
            }
        }
    }

    return SampleCoverage(
        greenFraction = greenPixels.toFloat() / (width * height),
        edgeGreenFraction = greenEdgePixels.toFloat() / edgePixels,
    )
}

/**
 * Classifies one pixel with the excess-green index, ExG = 2g − r − b, computed on chromatic
 * coordinates (each channel divided by r + g + b). Dividing by brightness makes the index
 * depend on colour rather than lighting, so shaded and sunlit parts of a leaf score alike.
 * It is a standard, cheap vegetation index in plant phenotyping.
 */
internal fun isPlantPixel(argb: Int, settings: GreenDetectionSettings): Boolean {
    val red = (argb shr 16) and 0xFF
    val green = (argb shr 8) and 0xFF
    val blue = argb and 0xFF
    val brightnessSum = red + green + blue
    if (brightnessSum < settings.minBrightnessSum) return false

    val excessGreen = (2f * green - red - blue) / brightnessSum
    return excessGreen >= settings.minExcessGreen
}
