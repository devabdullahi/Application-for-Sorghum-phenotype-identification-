package com.sorghum.segmentation

import kotlin.math.max
import kotlin.math.min

/**
 * Which pixels of an image belong to the sample, plus the summary numbers guidance and the
 * quality check need. Every detector in this module (green, contrast) returns one, so they all
 * feed the same "sample present" and "sample cut off" decisions.
 *
 * Not a data class: the mask is an array, so generated equals/hashCode would compare identity.
 *
 * @param width image width in pixels.
 * @param height image height in pixels.
 * @param sampleFraction fraction of all pixels that are sample.
 * @param edgeSampleFraction fraction of the pixels in the image's edge band that are sample.
 *   A high value means the sample runs across the border, i.e. it is cut off.
 * @param sampleConfidence how clearly the sample pixels stand out, 0..1: the mean confidence of
 *   the sample pixels. Near 0 means they barely pass the threshold. 0 if there is no sample.
 */
class SampleMask internal constructor(
    val width: Int,
    val height: Int,
    private val isSamplePixel: BooleanArray,
    val sampleFraction: Float,
    val edgeSampleFraction: Float,
    val sampleConfidence: Float,
) {
    /** Whether the pixel at ([x], [y]) is sample. Origin top-left, y down. */
    fun isSampleAt(x: Int, y: Int): Boolean {
        require(x in 0 until width && y in 0 until height) { "($x, $y) is outside the ${width}x$height mask" }
        return isSamplePixel[y * width + x]
    }

    /**
     * The summary in the shape live guidance and the quality check read today. Their fields are
     * still named "green" from when the green detector was the only one; for a contrast mask
     * read them as "sample".
     */
    fun toSampleCoverage(): SampleCoverage = SampleCoverage(
        greenFraction = sampleFraction,
        edgeGreenFraction = edgeSampleFraction,
        greenConfidence = sampleConfidence,
    )
}

/**
 * Builds a [SampleMask] from a per-pixel classifier, so every detector counts coverage and edge
 * touch the same way.
 *
 * @param edgeBandFraction width of the edge band, as a fraction of the image's shorter side.
 * @param sampleConfidenceAt returns the confidence 0..1 that the pixel at the given index
 *   (y * width + x) is sample, or null if it is not sample.
 */
internal inline fun buildSampleMask(
    width: Int,
    height: Int,
    edgeBandFraction: Float,
    sampleConfidenceAt: (pixelIndex: Int) -> Float?,
): SampleMask {
    // Always at least one pixel wide, so tiny analysis frames still have an edge band.
    val edgeBand = max(1, (min(width, height) * edgeBandFraction).toInt())

    val isSamplePixel = BooleanArray(width * height)
    var samplePixels = 0
    var edgePixels = 0
    var sampleEdgePixels = 0
    var confidenceSum = 0f
    for (y in 0 until height) {
        for (x in 0 until width) {
            val pixelIndex = y * width + x
            val confidence = sampleConfidenceAt(pixelIndex)
            val isSample = confidence != null
            val isInEdgeBand = x < edgeBand || x >= width - edgeBand ||
                y < edgeBand || y >= height - edgeBand

            if (confidence != null) {
                isSamplePixel[pixelIndex] = true
                samplePixels++
                confidenceSum += confidence
            }
            if (isInEdgeBand) {
                edgePixels++
                if (isSample) sampleEdgePixels++
            }
        }
    }

    return SampleMask(
        width = width,
        height = height,
        isSamplePixel = isSamplePixel,
        sampleFraction = samplePixels.toFloat() / (width * height),
        edgeSampleFraction = sampleEdgePixels.toFloat() / edgePixels,
        sampleConfidence = if (samplePixels == 0) 0f else confidenceSum / samplePixels,
    )
}
