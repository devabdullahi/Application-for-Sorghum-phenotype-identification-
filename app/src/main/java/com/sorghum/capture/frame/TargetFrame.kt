package com.sorghum.capture.frame

import kotlin.math.min

/**
 * A rectangle expressed as fractions (0..1) of some area, independent of pixel size.
 *
 * The target frame is stored this way so the same rectangle can be applied to the
 * on-screen preview, the small analysis frames, and the full-resolution photo.
 */
data class NormalizedRect(val left: Float, val top: Float, val right: Float, val bottom: Float) {
    init {
        require(left in 0f..1f && right in 0f..1f && top in 0f..1f && bottom in 0f..1f) {
            "NormalizedRect edges must be within 0..1, was ($left, $top, $right, $bottom)"
        }
        require(left < right && top < bottom) {
            "NormalizedRect must have positive size, was ($left, $top, $right, $bottom)"
        }
    }
}

/** A rectangle in pixels. [right] and [bottom] are exclusive, matching android.graphics.Rect. */
data class PixelRect(val left: Int, val top: Int, val right: Int, val bottom: Int) {
    val width: Int get() = right - left
    val height: Int get() = bottom - top
}

/**
 * Where the user should place the sample: a rectangle centred on the preview.
 *
 * @param widthFraction frame width as a fraction of the preview width.
 * @param aspectRatio frame width divided by frame height. Values below 1 give a tall frame,
 *   which suits long sorghum leaves and whole plants.
 */
data class TargetFrame(val widthFraction: Float = 0.8f, val aspectRatio: Float = 0.5f) {
    init {
        require(widthFraction > 0f && widthFraction <= 1f) {
            "widthFraction must be in (0, 1], was $widthFraction"
        }
        require(aspectRatio > 0f) { "aspectRatio must be positive, was $aspectRatio" }
    }

    /**
     * Returns the frame's position inside an area of the given size (screen pixels, or the
     * upright camera image). If the requested frame would be taller than the area, it is
     * shrunk so it fits while keeping its aspect ratio.
     */
    fun normalizedRectIn(areaWidth: Int, areaHeight: Int): NormalizedRect {
        require(areaWidth > 0 && areaHeight > 0) {
            "Area must have positive size, was ${areaWidth}x$areaHeight"
        }
        val requestedWidth = areaWidth * widthFraction
        val requestedHeight = requestedWidth / aspectRatio
        val shrinkToFit = min(1f, areaHeight / requestedHeight)

        val widthFractionOfArea = requestedWidth * shrinkToFit / areaWidth
        val heightFractionOfArea = requestedHeight * shrinkToFit / areaHeight
        val left = (1f - widthFractionOfArea) / 2f
        val top = (1f - heightFractionOfArea) / 2f
        return NormalizedRect(left, top, left + widthFractionOfArea, top + heightFractionOfArea)
    }
}
