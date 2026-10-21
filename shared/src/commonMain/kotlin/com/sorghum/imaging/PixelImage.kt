package com.sorghum.imaging

/**
 * An upright RGB image, the only image type that crosses into the shared core (ADR-0003).
 *
 * Pixels are stored row by row, top row first, 3 bytes per pixel in R, G, B order, with no
 * alpha and no row padding. Each platform converts its camera frame into this format once,
 * in its adapter, after cropping and rotating it upright.
 *
 * Not a data class: [rgb] is an array, so generated equals/hashCode would compare identity.
 *
 * @param rgb channel values 0–255, stored as (signed) bytes; read them with [redAt],
 *   [greenAt] and [blueAt], which undo the sign.
 */
class PixelImage(val width: Int, val height: Int, val rgb: ByteArray) {
    init {
        require(width > 0 && height > 0) { "Image must have positive size, was ${width}x$height" }
        require(rgb.size == width * height * BYTES_PER_PIXEL) {
            "Expected ${width * height * BYTES_PER_PIXEL} bytes for ${width}x$height RGB, got ${rgb.size}"
        }
    }

    val pixelCount: Int get() = width * height

    /** Red channel 0–255 of the pixel at [pixelIndex] (= y * width + x). */
    fun redAt(pixelIndex: Int): Int = rgb[pixelIndex * BYTES_PER_PIXEL].toInt() and 0xFF

    /** Green channel 0–255 of the pixel at [pixelIndex] (= y * width + x). */
    fun greenAt(pixelIndex: Int): Int = rgb[pixelIndex * BYTES_PER_PIXEL + 1].toInt() and 0xFF

    /** Blue channel 0–255 of the pixel at [pixelIndex] (= y * width + x). */
    fun blueAt(pixelIndex: Int): Int = rgb[pixelIndex * BYTES_PER_PIXEL + 2].toInt() and 0xFF

    companion object {
        const val BYTES_PER_PIXEL = 3
    }
}
