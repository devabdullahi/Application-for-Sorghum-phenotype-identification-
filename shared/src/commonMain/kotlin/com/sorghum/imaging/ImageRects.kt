package com.sorghum.imaging

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
