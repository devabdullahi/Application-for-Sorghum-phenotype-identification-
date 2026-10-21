package com.sorghum.imaging

import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/** Returns the largest centred square of [image], as model training crops it (`model/preprocessing.py`). */
fun cropCenterSquare(image: PixelImage): PixelImage {
    val side = min(image.width, image.height)
    val left = (image.width - side) / 2
    val top = (image.height - side) / 2
    val rgb = ByteArray(side * side * PixelImage.BYTES_PER_PIXEL)
    for (y in 0 until side) {
        val sourceStart = ((top + y) * image.width + left) * PixelImage.BYTES_PER_PIXEL
        image.rgb.copyInto(
            rgb,
            destinationOffset = y * side * PixelImage.BYTES_PER_PIXEL,
            startIndex = sourceStart,
            endIndex = sourceStart + side * PixelImage.BYTES_PER_PIXEL,
        )
    }
    return PixelImage(side, side, rgb)
}

/**
 * Resizes [image] with bilinear filtering, widening the filter when shrinking so the result is
 * antialiased. This follows Pillow's `Image.resize(..., BILINEAR)`, which the model was trained
 * with, so the phone sees the same kind of input as training did. Values can differ from
 * Pillow's by one level because Pillow uses fixed-point arithmetic; the parity fixtures check
 * the effect on the model output.
 */
fun resizeBilinear(image: PixelImage, widthPx: Int, heightPx: Int): PixelImage {
    require(widthPx > 0 && heightPx > 0) { "Target size must be positive, was ${widthPx}x$heightPx" }
    if (widthPx == image.width && heightPx == image.height) return image

    // Separable: resize rows first, then columns, each with its own filter weights.
    val horizontal = resampleAxis(image.width, widthPx)
    val vertical = resampleAxis(image.height, heightPx)

    val channels = PixelImage.BYTES_PER_PIXEL
    val rowsResized = FloatArray(widthPx * image.height * channels)
    for (y in 0 until image.height) {
        for (x in 0 until widthPx) {
            val taps = horizontal[x]
            for (channel in 0 until channels) {
                var sum = 0f
                for (tap in taps.weights.indices) {
                    val sourceIndex = (y * image.width + taps.first + tap) * channels + channel
                    sum += taps.weights[tap] * (image.rgb[sourceIndex].toInt() and 0xFF)
                }
                rowsResized[(y * widthPx + x) * channels + channel] = sum
            }
        }
    }

    val rgb = ByteArray(widthPx * heightPx * channels)
    for (y in 0 until heightPx) {
        val taps = vertical[y]
        for (x in 0 until widthPx) {
            for (channel in 0 until channels) {
                var sum = 0f
                for (tap in taps.weights.indices) {
                    sum += taps.weights[tap] * rowsResized[((taps.first + tap) * widthPx + x) * channels + channel]
                }
                rgb[(y * widthPx + x) * channels + channel] = sum.roundToInt().coerceIn(0, 255).toByte()
            }
        }
    }
    return PixelImage(widthPx, heightPx, rgb)
}

/** The source pixels (starting at [first]) and normalised weights that make one output pixel. */
private class FilterTaps(val first: Int, val weights: FloatArray)

/**
 * Triangle-filter taps for every output pixel along one axis, as Pillow computes them: the
 * filter is centred on the output pixel's centre in source coordinates and, when shrinking,
 * stretched by the scale so every source pixel contributes.
 */
private fun resampleAxis(sourceSize: Int, targetSize: Int): List<FilterTaps> {
    val scale = sourceSize.toFloat() / targetSize
    val filterScale = max(scale, 1f)
    val support = filterScale // the triangle filter has support 1 before stretching

    return List(targetSize) { outputIndex ->
        val center = (outputIndex + 0.5f) * scale
        val first = max(0, (center - support + 0.5f).toInt())
        val last = min(sourceSize, (center + support + 0.5f).toInt())
        val weights = FloatArray(last - first) { tap ->
            val distance = (first + tap - center + 0.5f) / filterScale
            max(0f, 1f - abs(distance))
        }
        val total = weights.sum()
        for (tap in weights.indices) weights[tap] /= total
        FilterTaps(first, weights)
    }
}
