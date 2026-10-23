package com.sorghum.segmentation

import com.sorghum.imaging.PixelImage
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt

/**
 * Thresholds for finding a panicle or grain on a plain board by how far its colour is from the
 * board's. Panicles and grain are often brown, red, white or black rather than green, so the
 * excess-green mask misses them; what they reliably have is contrast with the board.
 *
 * Distances are Euclidean distances in 0–255 RGB, so they range from 0 to [MAX_RGB_DISTANCE].
 * They are taken on the camera's colours, before colour-card correction, because live guidance
 * has no card reading yet and must use the same detector as the post-capture check.
 *
 * @param minColourDistance a pixel at least this far from the board colour is sample. Board
 *   noise and uneven light keep board pixels within about 20–30 of the board colour, and light
 *   grain on a dark board or a dark panicle on a light board are 100+ away. Initial guess, tune
 *   on real photos.
 * @param fullConfidenceColourDistance distance at and above which a pixel is certainly sample
 *   (confidence 1); confidence rises linearly from 0 at [minColourDistance]. Initial guess, tune
 *   on real photos.
 * @param boardBandFraction width of the image border band the board colour is estimated from, as
 *   a fraction of the shorter side. The user frames the sample inside the target frame, so the
 *   border is mostly board; 5 % gives enough pixels without reaching in towards the sample.
 * @param edgeBandFraction width of the edge band used for "sample cut off", as a fraction of the
 *   shorter side. Same default as [GreenDetectionSettings.edgeBandFraction], so both detectors
 *   mean the same by edge touch.
 */
data class ContrastMaskSettings(
    val minColourDistance: Float = 60f,
    val fullConfidenceColourDistance: Float = 120f,
    val boardBandFraction: Float = 0.05f,
    val edgeBandFraction: Float = 0.03f,
) {
    init {
        require(minColourDistance > 0f && minColourDistance < MAX_RGB_DISTANCE) {
            "minColourDistance must be within (0, $MAX_RGB_DISTANCE), was $minColourDistance"
        }
        require(fullConfidenceColourDistance > minColourDistance) {
            "fullConfidenceColourDistance must be above minColourDistance ($minColourDistance), " +
                "was $fullConfidenceColourDistance"
        }
        require(boardBandFraction > 0f && boardBandFraction < 0.5f) {
            "boardBandFraction must be within (0, 0.5), was $boardBandFraction"
        }
        require(edgeBandFraction > 0f && edgeBandFraction < 0.5f) {
            "edgeBandFraction must be within (0, 0.5), was $edgeBandFraction"
        }
    }

    companion object {
        /** Distance between black and white in 0–255 RGB: sqrt(3) * 255. */
        const val MAX_RGB_DISTANCE = 441.673f
    }
}

/**
 * Finds the sample on a plain board by colour contrast.
 *
 * The board colour is the per-channel median of the image's border band (see
 * [estimateBoardColour]); every pixel at least [ContrastMaskSettings.minColourDistance] from it
 * is sample. Works for a dark sample on a light board and a light sample on a dark board alike.
 *
 * ASSUMPTION — confirm: the sample covers less than half of the border band. Guidance already
 * asks the user to keep the sample inside the frame (SAMPLE_CUT_OFF), so a photo that breaks this
 * is also one guidance rejects. If the sample fills most of the border the median becomes the
 * sample's colour and the mask inverts.
 *
 * No morphological clean-up: isolated speckle barely moves the coverage fraction, and a kernel of
 * fixed pixel size would behave differently at the live and post-capture sizes, so the two would
 * stop agreeing on "sample present".
 */
fun measureContrastMask(image: PixelImage, settings: ContrastMaskSettings): SampleMask {
    val board = estimateBoardColour(image, settings)
    val confidenceRange = settings.fullConfidenceColourDistance - settings.minColourDistance

    return buildSampleMask(image.width, image.height, settings.edgeBandFraction) { pixelIndex ->
        val redDifference = (image.redAt(pixelIndex) - board.red).toFloat()
        val greenDifference = (image.greenAt(pixelIndex) - board.green).toFloat()
        val blueDifference = (image.blueAt(pixelIndex) - board.blue).toFloat()
        val distance = sqrt(
            redDifference * redDifference + greenDifference * greenDifference + blueDifference * blueDifference,
        )
        if (distance < settings.minColourDistance) {
            null
        } else {
            ((distance - settings.minColourDistance) / confidenceRange).coerceIn(0f, 1f)
        }
    }
}

/** An estimated board colour, channels 0–255 in the camera's colour space. */
internal data class BoardColour(val red: Int, val green: Int, val blue: Int)

/**
 * Estimates the board colour as the per-channel median of the pixels in the border band.
 * The median ignores a sample that pokes into the border, as long as it covers less than half
 * of the band; a mean would be dragged towards it.
 */
internal fun estimateBoardColour(image: PixelImage, settings: ContrastMaskSettings): BoardColour {
    val width = image.width
    val height = image.height
    // At least one pixel, so the smallest live frames still have a border to sample.
    val band = max(1, (min(width, height) * settings.boardBandFraction).toInt())

    val redHistogram = IntArray(CHANNEL_LEVELS)
    val greenHistogram = IntArray(CHANNEL_LEVELS)
    val blueHistogram = IntArray(CHANNEL_LEVELS)
    var bandPixels = 0
    for (y in 0 until height) {
        for (x in 0 until width) {
            val isInBand = x < band || x >= width - band || y < band || y >= height - band
            if (!isInBand) continue

            val pixelIndex = y * width + x
            redHistogram[image.redAt(pixelIndex)]++
            greenHistogram[image.greenAt(pixelIndex)]++
            blueHistogram[image.blueAt(pixelIndex)]++
            bandPixels++
        }
    }

    return BoardColour(
        red = medianOf(redHistogram, bandPixels),
        green = medianOf(greenHistogram, bandPixels),
        blue = medianOf(blueHistogram, bandPixels),
    )
}

/** The lower median of [count] values given as a histogram over 0–255. */
private fun medianOf(histogram: IntArray, count: Int): Int {
    val middle = (count - 1) / 2
    var seen = 0
    for (level in histogram.indices) {
        seen += histogram[level]
        if (seen > middle) return level
    }
    return histogram.lastIndex
}

/** Number of levels in one 8-bit colour channel. */
private const val CHANNEL_LEVELS = 256
