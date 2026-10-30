package com.sorghum.segmentation

import com.sorghum.imaging.PixelImage
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt

/**
 * How much of an image region is covered by a sample that stands out from a plain board.
 *
 * @param sampleFraction fraction of all pixels in the region that differ from the board.
 * @param edgeSampleFraction fraction of pixels in the region's edge band that differ from the
 *   board. A high value means the sample runs across the region's border, i.e. it is cut off.
 */
data class ContrastCoverage(
    val sampleFraction: Float,
    val edgeSampleFraction: Float,
)

/**
 * Thresholds for deciding whether a pixel belongs to a sample on a plain board. Used for
 * samples that are not reliably green: panicles (tan, red, brown, cream) and grain.
 *
 * @param minChromaDistance distance between a pixel's chromatic coordinates (each channel
 *   divided by r + g + b) and the board's, at and above which the pixel is sample. Shading
 *   changes brightness but barely chromaticity, so a shaded board stays near 0; tan, red and
 *   brown panicles on a white, grey or black board are about 0.1–0.3 away. Pale cream panicles
 *   on a white board are close to this threshold, so use a dark board for them.
 *   Initial guess, tune on real photos.
 * @param minBrightnessDifference difference of r + g + b from the board's, as a fraction of the
 *   full range (765), at and above which the pixel is sample. Catches samples the same hue as
 *   the board but much lighter or darker, such as a cream panicle on a black board. Set above
 *   typical shading across a board under a lamp (about 0.25). Initial guess, tune on real photos.
 * @param minBrightnessSum pixels (and boards) whose r + g + b is below this are compared by
 *   brightness only, because in very dark pixels sensor noise makes the colour ratios meaningless.
 * @param edgeBandFraction width of the edge band, as a fraction of the region's shorter side.
 *   The board colour is estimated from this band, and it also measures whether the sample is cut off.
 */
data class ContrastDetectionSettings(
    val minChromaDistance: Float = 0.05f,
    val minBrightnessDifference: Float = 0.3f,
    val minBrightnessSum: Int = 60,
    val edgeBandFraction: Float = 0.03f,
) {
    init {
        require(minChromaDistance > 0f) { "minChromaDistance must be positive, was $minChromaDistance" }
        require(minBrightnessDifference > 0f && minBrightnessDifference <= 1f) {
            "minBrightnessDifference must be within (0, 1], was $minBrightnessDifference"
        }
        require(minBrightnessSum in 0..MAX_BRIGHTNESS_SUM) {
            "minBrightnessSum must be within 0..$MAX_BRIGHTNESS_SUM, was $minBrightnessSum"
        }
        require(edgeBandFraction > 0f && edgeBandFraction < 0.5f) {
            "edgeBandFraction must be within (0, 0.5), was $edgeBandFraction"
        }
    }
}

/**
 * Measures how much of an image region is covered by a sample on a plain board, whatever the
 * sample's colour.
 *
 * The board colour is the per-channel median of the region's edge band, so the region must
 * show mostly board along its border: the estimate holds while the sample covers less than
 * half of the edge band. That matches the capture instruction to fit the sample inside the frame.
 *
 * Like [com.sorghum.capture.sample.measureSampleCoverage], it is meant to run on both live
 * frames and the captured photo, so both agree on what "sample present" means.
 */
fun measureContrastCoverage(image: PixelImage, settings: ContrastDetectionSettings): ContrastCoverage {
    val width = image.width
    val height = image.height
    // Always at least one pixel wide, so tiny analysis frames still have an edge band.
    val edgeBand = max(1, (min(width, height) * settings.edgeBandFraction).toInt())
    val board = estimateBoardColour(image, edgeBand)

    var samplePixels = 0
    var edgePixels = 0
    var sampleEdgePixels = 0
    for (y in 0 until height) {
        for (x in 0 until width) {
            val pixelIndex = y * width + x
            val isSample = isSamplePixel(
                image.redAt(pixelIndex), image.greenAt(pixelIndex), image.blueAt(pixelIndex), board, settings,
            )
            if (isSample) samplePixels++
            if (isInEdgeBand(x, y, width, height, edgeBand)) {
                edgePixels++
                if (isSample) sampleEdgePixels++
            }
        }
    }

    return ContrastCoverage(
        sampleFraction = samplePixels.toFloat() / (width * height),
        edgeSampleFraction = sampleEdgePixels.toFloat() / edgePixels,
    )
}

/** The board's colour, channels 0–255. */
internal data class BoardColour(val red: Int, val green: Int, val blue: Int) {
    val brightnessSum: Int get() = red + green + blue
}

/**
 * The per-channel median of the edge band. A median rather than a mean, so a sample touching
 * part of the border does not pull the estimate towards its own colour.
 */
internal fun estimateBoardColour(image: PixelImage, edgeBand: Int): BoardColour {
    val redHistogram = IntArray(CHANNEL_LEVELS)
    val greenHistogram = IntArray(CHANNEL_LEVELS)
    val blueHistogram = IntArray(CHANNEL_LEVELS)
    var edgePixels = 0
    for (y in 0 until image.height) {
        for (x in 0 until image.width) {
            if (!isInEdgeBand(x, y, image.width, image.height, edgeBand)) continue
            val pixelIndex = y * image.width + x
            redHistogram[image.redAt(pixelIndex)]++
            greenHistogram[image.greenAt(pixelIndex)]++
            blueHistogram[image.blueAt(pixelIndex)]++
            edgePixels++
        }
    }
    return BoardColour(
        red = medianOf(redHistogram, edgePixels),
        green = medianOf(greenHistogram, edgePixels),
        blue = medianOf(blueHistogram, edgePixels),
    )
}

/**
 * Classifies one pixel against the board: sample if its brightness or its colour differs
 * enough. Brightness alone misses a tan panicle on a grey board of the same brightness; colour
 * alone misses a cream panicle on a black board.
 */
internal fun isSamplePixel(red: Int, green: Int, blue: Int, board: BoardColour, settings: ContrastDetectionSettings): Boolean {
    val brightnessSum = red + green + blue
    val brightnessDifference = abs(brightnessSum - board.brightnessSum).toFloat() / MAX_BRIGHTNESS_SUM
    if (brightnessDifference >= settings.minBrightnessDifference) return true

    val isBrightEnoughForColour = brightnessSum >= settings.minBrightnessSum &&
        board.brightnessSum >= settings.minBrightnessSum
    if (!isBrightEnoughForColour) return false
    return chromaDistance(red, green, blue, board) >= settings.minChromaDistance
}

/**
 * Euclidean distance between the chromatic coordinates (r, g, b each divided by r + g + b) of
 * a pixel and the board. Dividing by brightness makes it depend on colour rather than lighting.
 * Both must have a positive brightness sum.
 */
internal fun chromaDistance(red: Int, green: Int, blue: Int, board: BoardColour): Float {
    val brightnessSum = (red + green + blue).toFloat()
    val boardBrightnessSum = board.brightnessSum.toFloat()
    val redDifference = red / brightnessSum - board.red / boardBrightnessSum
    val greenDifference = green / brightnessSum - board.green / boardBrightnessSum
    val blueDifference = blue / brightnessSum - board.blue / boardBrightnessSum
    return sqrt(redDifference * redDifference + greenDifference * greenDifference + blueDifference * blueDifference)
}

private fun isInEdgeBand(x: Int, y: Int, width: Int, height: Int, edgeBand: Int): Boolean =
    x < edgeBand || x >= width - edgeBand || y < edgeBand || y >= height - edgeBand

/** The lower median of [count] values recorded in [histogram]. */
private fun medianOf(histogram: IntArray, count: Int): Int {
    val middleRank = (count - 1) / 2
    var seen = 0
    for (level in histogram.indices) {
        seen += histogram[level]
        if (seen > middleRank) return level
    }
    error("Histogram holds fewer than $count values")
}

private const val CHANNEL_LEVELS = 256
private const val MAX_BRIGHTNESS_SUM = 3 * 255
