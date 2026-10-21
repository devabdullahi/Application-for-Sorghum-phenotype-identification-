package com.sorghum.capture.sample

import com.sorghum.imaging.PixelImage
import kotlin.math.max
import kotlin.math.min

/**
 * How much of an image region is covered by green plant tissue.
 *
 * @param greenFraction fraction of all pixels in the region that are green.
 * @param edgeGreenFraction fraction of pixels in the region's edge band that are green.
 *   A high value means the sample runs across the region's border, i.e. it is cut off.
 * @param greenConfidence how clearly green the green pixels are, 0..1: the mean of each green
 *   pixel's confidence (see [greenConfidenceOf]). Near 0 means the "green" is barely above the
 *   threshold (dull, yellowing or tinted light); near 1 means clearly green leaf. 0 if no pixel is green.
 */
data class SampleCoverage(
    val greenFraction: Float,
    val edgeGreenFraction: Float,
    val greenConfidence: Float,
)

/**
 * Thresholds for deciding whether a pixel is green plant tissue.
 *
 * @param minExcessGreen minimum excess-green index (see [isPlantPixel]). 0.1 separates leaves
 *   from grey, white, brown or black boards in typical indoor light; tune if the board is tinted.
 * @param minBrightnessSum pixels whose r + g + b is below this are ignored, because in very dark
 *   pixels sensor noise makes the colour ratios meaningless.
 * @param edgeBandFraction width of the edge band, as a fraction of the region's shorter side.
 * @param fullConfidenceExcessGreen excess-green index at and above which a pixel is certainly
 *   green (confidence 1). Healthy leaves score about 0.5–0.7; dull or yellowing tissue sits
 *   near [minExcessGreen]. Initial guess, tune on real photos.
 */
data class GreenDetectionSettings(
    val minExcessGreen: Float = 0.1f,
    val minBrightnessSum: Int = 60,
    val edgeBandFraction: Float = 0.03f,
    val fullConfidenceExcessGreen: Float = 0.3f,
) {
    init {
        require(fullConfidenceExcessGreen > minExcessGreen) {
            "fullConfidenceExcessGreen must be above minExcessGreen ($minExcessGreen), was $fullConfidenceExcessGreen"
        }
        require(minBrightnessSum in 0..765) {
            "minBrightnessSum must be within 0..765, was $minBrightnessSum"
        }
        require(edgeBandFraction > 0f && edgeBandFraction < 0.5f) {
            "edgeBandFraction must be within (0, 0.5), was $edgeBandFraction"
        }
    }
}

/**
 * Live frames are shrunk so their longer side is at most this many pixels before
 * [measureSampleCoverage]. A rough green count needs very few pixels, and a small image keeps
 * analysis well under one frame interval. Thresholds tuned on live frames assume this size.
 */
const val LIVE_ANALYSIS_LONG_SIDE_PIXELS = 160

/**
 * Measures green coverage of an image region.
 *
 * Used both on small live analysis frames and on the captured photo, so the live guidance
 * and the final check agree on what counts as "sample present".
 */
fun measureSampleCoverage(image: PixelImage, settings: GreenDetectionSettings): SampleCoverage {
    val width = image.width
    val height = image.height

    // Always at least one pixel wide, so tiny analysis frames still have an edge band.
    val edgeBand = max(1, (min(width, height) * settings.edgeBandFraction).toInt())

    var greenPixels = 0
    var edgePixels = 0
    var greenEdgePixels = 0
    var confidenceSum = 0f
    for (y in 0 until height) {
        for (x in 0 until width) {
            val pixelIndex = y * width + x
            val excessGreen = excessGreenIndex(
                image.redAt(pixelIndex), image.greenAt(pixelIndex), image.blueAt(pixelIndex), settings,
            )
            val isGreen = excessGreen != null && excessGreen >= settings.minExcessGreen
            val isInEdgeBand = x < edgeBand || x >= width - edgeBand ||
                y < edgeBand || y >= height - edgeBand

            if (isGreen) {
                greenPixels++
                confidenceSum += greenConfidenceOf(excessGreen!!, settings)
            }
            if (isInEdgeBand) {
                edgePixels++
                if (isGreen) greenEdgePixels++
            }
        }
    }

    return SampleCoverage(
        greenFraction = greenPixels.toFloat() / (width * height),
        edgeGreenFraction = greenEdgePixels.toFloat() / edgePixels,
        greenConfidence = if (greenPixels == 0) 0f else confidenceSum / greenPixels,
    )
}

/**
 * Classifies one pixel with the excess-green index, ExG = 2g − r − b, computed on chromatic
 * coordinates (each channel divided by r + g + b). Dividing by brightness makes the index
 * depend on colour rather than lighting, so shaded and sunlit parts of a leaf score alike.
 * It is a standard, cheap vegetation index in plant phenotyping.
 */
internal fun isPlantPixel(red: Int, green: Int, blue: Int, settings: GreenDetectionSettings): Boolean {
    val excessGreen = excessGreenIndex(red, green, blue, settings) ?: return false
    return excessGreen >= settings.minExcessGreen
}

/** The excess-green index of one pixel, or null if it is too dark for colour ratios to mean anything. */
internal fun excessGreenIndex(red: Int, green: Int, blue: Int, settings: GreenDetectionSettings): Float? {
    val brightnessSum = red + green + blue
    if (brightnessSum < settings.minBrightnessSum) return null

    return (2f * green - red - blue) / brightnessSum
}

/**
 * How sure we are that a pixel with this excess-green index is green plant tissue, 0..1.
 * Rises linearly from 0 at the classification threshold to 1 at
 * [GreenDetectionSettings.fullConfidenceExcessGreen], so pixels that only just pass the
 * threshold count as uncertain rather than as fully green.
 */
internal fun greenConfidenceOf(excessGreen: Float, settings: GreenDetectionSettings): Float {
    val range = settings.fullConfidenceExcessGreen - settings.minExcessGreen
    return ((excessGreen - settings.minExcessGreen) / range).coerceIn(0f, 1f)
}
