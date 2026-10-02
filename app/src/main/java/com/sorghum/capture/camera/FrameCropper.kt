package com.sorghum.capture.camera

import android.graphics.Bitmap
import android.graphics.Matrix
import android.graphics.Rect
import androidx.camera.core.ImageProxy
import androidx.core.graphics.scale
import com.sorghum.capture.frame.PixelRect
import com.sorghum.capture.frame.TargetFrame
import com.sorghum.capture.frame.mapTargetToImagePixels
import com.sorghum.capture.frame.uprightSize
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/**
 * Cuts the target frame out of a camera image and returns it upright.
 *
 * Used for both the small live analysis frames and the full-resolution photo, so the live
 * guidance and the final check look at exactly the same region.
 *
 * Cropping happens before rotating, so only the frame region is rotated and scaled. That
 * matters for full-resolution photos, which are large.
 *
 * @param maxLongSidePixels the result is scaled down so its longer side is at most this.
 *   Pass [Int.MAX_VALUE] to keep full resolution.
 */
fun cropToTargetFrame(image: ImageProxy, targetFrame: TargetFrame, maxLongSidePixels: Int): Bitmap {
    val rotationDegrees = image.imageInfo.rotationDegrees
    val crop = image.cropRect.toPixelRect()
    val (uprightWidth, uprightHeight) = uprightSize(crop, rotationDegrees)
    val targetInView = targetFrame.normalizedRectIn(uprightWidth, uprightHeight)
    val region = mapTargetToImagePixels(targetInView, crop, rotationDegrees)
        .clampedTo(image.width, image.height)

    val longSide = max(region.width, region.height)
    val scale = min(1f, maxLongSidePixels.toFloat() / longSide)
    val transform = Matrix().apply {
        postScale(scale, scale)
        postRotate(rotationDegrees.toFloat())
    }

    val source = image.toBitmap()
    val cropped = Bitmap.createBitmap(source, region.left, region.top, region.width, region.height, transform, true)
    // Free the full decoded image right away; for photos it can be tens of megabytes.
    if (cropped !== source) source.recycle()
    return cropped
}

/** Returns this bitmap scaled so its longer side is at most [maxLongSidePixels]. */
fun Bitmap.scaledToLongSide(maxLongSidePixels: Int): Bitmap {
    val longSide = max(width, height)
    if (longSide <= maxLongSidePixels) return this
    val scale = maxLongSidePixels.toFloat() / longSide
    return scale((width * scale).roundToInt(), (height * scale).roundToInt())
}

/** All pixels as packed ARGB ints, row by row, the format the analysis functions expect. */
fun Bitmap.argbPixels(): IntArray {
    val pixels = IntArray(width * height)
    getPixels(pixels, 0, width, 0, 0, width, height)
    return pixels
}

private fun Rect.toPixelRect() = PixelRect(left, top, right, bottom)

/**
 * Rounding in the frame mapping can land one pixel outside the image; clamp so
 * Bitmap.createBitmap never throws for a valid frame.
 */
private fun PixelRect.clampedTo(imageWidth: Int, imageHeight: Int): PixelRect {
    val clamped = PixelRect(
        left = left.coerceIn(0, imageWidth - 1),
        top = top.coerceIn(0, imageHeight - 1),
        right = right.coerceIn(1, imageWidth),
        bottom = bottom.coerceIn(1, imageHeight),
    )
    check(clamped.width > 0 && clamped.height > 0) {
        "Target frame $this does not overlap the ${imageWidth}x$imageHeight image"
    }
    return clamped
}
