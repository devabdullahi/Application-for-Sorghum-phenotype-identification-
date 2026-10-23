package com.sorghum.capture.platform

import android.graphics.Bitmap
import com.sorghum.imaging.PixelImage

/**
 * Copies this bitmap into the shared core's [PixelImage]. This is the Android app's only
 * conversion into the shared image format, so channel order is decided in one place.
 *
 * The bitmap must already be cropped and upright (see [cropToTargetFrame]).
 */
fun Bitmap.toPixelImage(): PixelImage {
    val argbPixels = IntArray(width * height)
    getPixels(argbPixels, 0, width, 0, 0, width, height)
    return argbToPixelImage(argbPixels, width, height)
}

/**
 * Converts packed ARGB ints (the format of [Bitmap.getPixels]), row by row, to a [PixelImage].
 * Alpha is dropped: camera frames are opaque.
 *
 * Split out of [toPixelImage] so the channel order can be tested on the JVM without a Bitmap.
 */
internal fun argbToPixelImage(argbPixels: IntArray, width: Int, height: Int): PixelImage {
    require(argbPixels.size == width * height) {
        "Expected ${width * height} pixels for ${width}x$height, got ${argbPixels.size}"
    }
    val rgb = ByteArray(argbPixels.size * PixelImage.BYTES_PER_PIXEL)
    for (index in argbPixels.indices) {
        val argb = argbPixels[index]
        val offset = index * PixelImage.BYTES_PER_PIXEL
        rgb[offset] = (argb shr 16).toByte()
        rgb[offset + 1] = (argb shr 8).toByte()
        rgb[offset + 2] = argb.toByte()
    }
    return PixelImage(width, height, rgb)
}
