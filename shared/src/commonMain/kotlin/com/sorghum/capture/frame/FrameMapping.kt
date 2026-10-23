package com.sorghum.capture.frame

import com.sorghum.imaging.NormalizedRect
import com.sorghum.imaging.PixelRect
import kotlin.math.roundToInt

/**
 * The single place that converts between "what the user sees" and camera image pixels.
 *
 * Camera images arrive in the sensor's orientation (usually landscape) with a crop rectangle
 * that CameraX sets so every use case shows the same region as the on-screen preview.
 * The user sees that crop rotated upright. A target frame is defined in the upright view,
 * so to find its pixels we undo the rotation and offset by the crop.
 *
 * @param targetInUprightView target frame as fractions of the upright, cropped view.
 * @param cropRect the image's crop rectangle, in sensor-oriented image pixels.
 * @param rotationDegrees clockwise rotation needed to make the image upright (0, 90, 180, 270),
 *   as reported by CameraX's ImageInfo.rotationDegrees.
 * @return the target frame in sensor-oriented image pixels.
 */
fun mapTargetToImagePixels(
    targetInUprightView: NormalizedRect,
    cropRect: PixelRect,
    rotationDegrees: Int,
): PixelRect {
    // Map the rectangle to fractions of the un-rotated crop. For each rotation, an upright
    // point (u, v) comes from a specific point of the sensor image; see the derivation in
    // FrameMappingTest for worked examples.
    val t = targetInUprightView
    val sensorFractions = when (rotationDegrees) {
        0 -> NormalizedRect(t.left, t.top, t.right, t.bottom)
        // Rotating 90° clockwise sends sensor (x, y) to upright (H - y, x), so x = v and y = 1 - u.
        90 -> NormalizedRect(t.top, 1f - t.right, t.bottom, 1f - t.left)
        180 -> NormalizedRect(1f - t.right, 1f - t.bottom, 1f - t.left, 1f - t.top)
        // Rotating 270° clockwise sends sensor (x, y) to upright (y, W - x), so x = 1 - v and y = u.
        270 -> NormalizedRect(1f - t.bottom, t.left, 1f - t.top, t.right)
        else -> throw IllegalArgumentException(
            "rotationDegrees must be 0, 90, 180 or 270, was $rotationDegrees"
        )
    }

    return PixelRect(
        left = cropRect.left + (sensorFractions.left * cropRect.width).roundToInt(),
        top = cropRect.top + (sensorFractions.top * cropRect.height).roundToInt(),
        right = cropRect.left + (sensorFractions.right * cropRect.width).roundToInt(),
        bottom = cropRect.top + (sensorFractions.bottom * cropRect.height).roundToInt(),
    )
}

/**
 * Size of the crop as the user sees it (after rotation). Needed to place the target frame
 * with the same proportions as on screen.
 */
fun uprightSize(cropRect: PixelRect, rotationDegrees: Int): Pair<Int, Int> {
    val isSideways = rotationDegrees == 90 || rotationDegrees == 270
    return if (isSideways) cropRect.height to cropRect.width else cropRect.width to cropRect.height
}
