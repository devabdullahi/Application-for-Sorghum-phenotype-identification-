package com.sorghum.calibration

import com.sorghum.imaging.PixelImage
import com.sorghum.imaging.PixelRect
import kotlin.math.abs
import kotlin.math.ceil
import kotlin.math.floor
import kotlin.math.max
import kotlin.math.roundToInt

/**
 * A regular grid found along one image axis, in pixel-boundary coordinates relative to the
 * searched region (coordinate c is the line between pixels c - 1 and c).
 *
 * @param startPx position of the first grid line (outer edge of the first patch cell).
 * @param pitchPx distance between grid lines; sub-pixel, from a line fitted through the
 *   observed patch gaps.
 * @param edgeContrast total colour change across a grid line's band, averaged over the lines,
 *   minus the change across an equally wide band inside the cells; in 0–255 levels. Roughly
 *   the colour step at a patch gap, scaled by the fraction of the region the card spans.
 *   Larger means a clearer grid.
 */
internal class GridAxis(val startPx: Float, val pitchPx: Float, val edgeContrast: Float)

/** Which way an [edgeProfile] runs. */
internal enum class ProfileAxis { HORIZONTAL, VERTICAL }

/**
 * Colour-edge strength across [region] along [axis], summed over the other axis. For
 * [ProfileAxis.HORIZONTAL], entry c is the mean over the region's rows of the colour change
 * between columns c - 1 and c (mean absolute difference of R, G, B, in 0–255 levels); entry 0
 * is 0. The card's black gaps between coloured patches show up as peaks.
 *
 * Summing along whole rows makes the search separable (two 1-D searches instead of one 2-D
 * search) and averages away pixel noise; it assumes the card is roughly square to the image,
 * which the card slot on the board ensures.
 */
internal fun edgeProfile(image: PixelImage, region: PixelRect, axis: ProfileAxis): FloatArray {
    val length = if (axis == ProfileAxis.HORIZONTAL) region.width else region.height
    val across = if (axis == ProfileAxis.HORIZONTAL) region.height else region.width
    val profile = FloatArray(length)
    for (along in 1 until length) {
        var sum = 0L
        for (other in 0 until across) {
            val (x, y) = if (axis == ProfileAxis.HORIZONTAL) {
                Pair(region.left + along, region.top + other)
            } else {
                Pair(region.left + other, region.top + along)
            }
            val here = y * image.width + x
            val before = if (axis == ProfileAxis.HORIZONTAL) here - 1 else here - image.width
            sum += abs(image.redAt(here) - image.redAt(before)) +
                abs(image.greenAt(here) - image.greenAt(before)) +
                abs(image.blueAt(here) - image.blueAt(before))
        }
        profile[along] = sum.toFloat() / (3 * across)
    }
    return profile
}

/**
 * Finds the best grid of [cells] equal cells in an [edgeProfile]: edges strong on the grid
 * lines and weak inside the cells. Tries every whole-pixel pitch and start, then refines the
 * pitch to sub-pixel by fitting a line through the edge centroids of the inner grid lines.
 *
 * Scoring by line edges minus interior edges (rather than interior uniformity alone) matters:
 * a grid at half the true pitch also has uniform interiors, but half its lines fall inside
 * patches where there are no edges, so it scores lower. Line bands are scored by their total
 * edge change, not their mean, so a narrow band (small pitch) gains nothing over a wide one
 * holding the same edges.
 *
 * Returns null when no pitch fits the settings' size limits.
 */
internal fun findGridAxis(profile: FloatArray, cells: Int, settings: ColourCardSettings): GridAxis? {
    val length = profile.size
    // Floor, not ceil, of the pitch limit: refinement may land a fraction below the whole-pixel
    // pitch, and the caller checks the refined pitch against the limit itself.
    val minPitch = max(floor(settings.minPatchPitchPx).toInt(), ceil(settings.minGridFractionOfHint * length / cells).toInt())
    val maxPitch = length / cells
    if (minPitch > maxPitch) return null

    val prefix = DoubleArray(length + 1)
    for (index in 0 until length) prefix[index + 1] = prefix[index] + profile[index]
    fun sumOver(from: Int, toInclusive: Int): Double {
        val first = from.coerceAtLeast(0)
        val last = toInclusive.coerceAtMost(length - 1)
        return if (last < first) 0.0 else prefix[last + 1] - prefix[first]
    }
    fun meanOver(from: Int, toInclusive: Int): Double {
        val count = toInclusive - from + 1
        return if (count <= 0) 0.0 else sumOver(from, toInclusive) / count
    }

    var bestStart = 0
    var bestPitch = 0
    var bestContrast = Double.NEGATIVE_INFINITY
    for (pitch in minPitch..maxPitch) {
        val window = windowHalfWidth(pitch, settings)
        for (start in 0..length - cells * pitch) {
            var lineEdgeSum = 0.0
            for (line in 0..cells) lineEdgeSum += sumOver(start + line * pitch - window, start + line * pitch + window)
            var interiorMeanSum = 0.0
            for (cell in 0 until cells) {
                interiorMeanSum += meanOver(start + cell * pitch + window + 1, start + (cell + 1) * pitch - window - 1)
            }
            // Edge change across a line band, minus what a band of the same width inside a patch carries.
            val contrast = lineEdgeSum / (cells + 1) - interiorMeanSum / cells * (2 * window + 1)
            if (contrast > bestContrast) {
                bestContrast = contrast
                bestStart = start
                bestPitch = pitch
            }
        }
    }
    return refineGrid(profile, cells, bestStart, bestPitch, windowHalfWidth(bestPitch, settings), bestContrast.toFloat())
}

private fun windowHalfWidth(pitch: Int, settings: ColourCardSettings): Int =
    max(1, (pitch * settings.gridBoundaryWindowFraction).roundToInt())

/**
 * Sub-pixel start and pitch from a least-squares line through the edge centroid of each inner
 * grid line (line k at start + k * pitch). The centroid of a gap's two edges is the gap's
 * centre. Outer lines are skipped: the card frame on one side makes their centroids lopsided.
 * Falls back to the whole-pixel grid when fewer than two inner lines have any edge.
 */
private fun refineGrid(profile: FloatArray, cells: Int, start: Int, pitch: Int, window: Int, contrast: Float): GridAxis {
    val lineIndices = mutableListOf<Double>()
    val centroids = mutableListOf<Double>()
    for (line in 1 until cells) {
        val centre = start + line * pitch
        var weight = 0.0
        var weightedPosition = 0.0
        for (position in (centre - window).coerceAtLeast(0)..(centre + window).coerceAtMost(profile.size - 1)) {
            weight += profile[position]
            weightedPosition += profile[position].toDouble() * position
        }
        if (weight > 0.0) {
            lineIndices += line.toDouble()
            centroids += weightedPosition / weight
        }
    }
    if (lineIndices.size < 2) return GridAxis(start.toFloat(), pitch.toFloat(), contrast)

    val meanLine = lineIndices.average()
    val meanCentroid = centroids.average()
    var covariance = 0.0
    var variance = 0.0
    for (index in lineIndices.indices) {
        covariance += (lineIndices[index] - meanLine) * (centroids[index] - meanCentroid)
        variance += (lineIndices[index] - meanLine) * (lineIndices[index] - meanLine)
    }
    val refinedPitch = covariance / variance
    val refinedStart = meanCentroid - refinedPitch * meanLine
    return GridAxis(refinedStart.toFloat(), refinedPitch.toFloat(), contrast)
}
