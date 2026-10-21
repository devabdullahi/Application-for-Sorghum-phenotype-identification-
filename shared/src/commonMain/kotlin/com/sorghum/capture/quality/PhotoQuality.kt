package com.sorghum.capture.quality

import com.sorghum.capture.sample.GreenDetectionSettings
import com.sorghum.capture.sample.measureSampleCoverage
import com.sorghum.imaging.PixelImage

/** Why a captured photo was rejected. Each reason maps to a specific message for the user. */
enum class RejectionReason {
    NO_SAMPLE,
    TOO_DARK,
    GLARE,
    BLURRY,
}

/**
 * Thresholds for the post-capture check. These are initial guesses and must be tuned on real
 * sample photos taken with the target devices.
 *
 * The blur threshold depends on image size, so the photo must be downscaled to
 * [QUALITY_CHECK_LONG_SIDE_PIXELS] before checking; see [checkPhotoQuality].
 *
 * @param minSampleFraction minimum fraction of the photo that must be green.
 * @param minMeanBrightness minimum average luma (0–255).
 * @param glareBrightness luma at or above which a pixel counts as blown-out glare.
 * @param maxGlareFraction maximum fraction of glare pixels. Leaves are waxy and reflect ring
 *   lights, and glare hides the leaf surface.
 * @param minSharpness minimum variance of the Laplacian. The Laplacian responds to edges;
 *   a blurred image has soft edges, so its Laplacian values vary less.
 */
data class QualitySettings(
    val minSampleFraction: Float = 0.02f,
    val minMeanBrightness: Float = 60f,
    val glareBrightness: Int = 250,
    val maxGlareFraction: Float = 0.02f,
    val minSharpness: Float = 50f,
    val greenDetection: GreenDetectionSettings = GreenDetectionSettings(),
)

/** Where a photo came from, which decides the checks that apply to it. */
enum class PhotoSource {
    /** Taken in the app, cropped to the target frame over the board. All checks apply. */
    CAMERA_TARGET_FRAME,

    /**
     * Picked from the photo library: any framing, background and plant part. Only the
     * darkness and blur checks apply; two board-photo checks are skipped (decision 2026-10-21):
     * - Sample present: green coverage only means "sample present" for a leaf on a plain board.
     *   Foliage in general photos is often olive, shaded or a small part of the frame, and
     *   panicles and grain are not green at all. The species check, whose model has a no-plant
     *   class, decides whether a plant is there.
     * - Glare: blown-out pixels mean light reflected off the leaf only on a board photo. In
     *   general photos they are usually sky or a white background.
     */
    PHOTO_LIBRARY,
}

/** Longest side, in pixels, that photos are scaled to before [checkPhotoQuality]. */
const val QUALITY_CHECK_LONG_SIDE_PIXELS = 640

/**
 * Checks a cropped, upright photo and returns why it should be rejected, or null if it is
 * acceptable.
 *
 * Checks run cheapest and most fundamental first: there is no point reporting blur on a
 * photo that has no sample in it.
 */
fun checkPhotoQuality(
    image: PixelImage,
    settings: QualitySettings,
    source: PhotoSource = PhotoSource.CAMERA_TARGET_FRAME,
): RejectionReason? {
    if (source == PhotoSource.CAMERA_TARGET_FRAME) {
        val coverage = measureSampleCoverage(image, settings.greenDetection)
        if (coverage.greenFraction < settings.minSampleFraction) return RejectionReason.NO_SAMPLE
    }

    val luma = toLuma(image)
    if (luma.average() < settings.minMeanBrightness) return RejectionReason.TOO_DARK

    if (source == PhotoSource.CAMERA_TARGET_FRAME) {
        val glarePixels = luma.count { it >= settings.glareBrightness }
        if (glarePixels.toFloat() / luma.size > settings.maxGlareFraction) return RejectionReason.GLARE
    }

    if (laplacianVariance(luma, image.width, image.height) < settings.minSharpness) return RejectionReason.BLURRY

    return null
}

/** Converts an image to luma (perceived brightness, 0–255) using the BT.601 weights. */
internal fun toLuma(image: PixelImage): IntArray = IntArray(image.pixelCount) { index ->
    (0.299f * image.redAt(index) + 0.587f * image.greenAt(index) + 0.114f * image.blueAt(index)).toInt()
}

/**
 * Sharpness measure: variance of the 4-neighbour Laplacian over the interior pixels.
 * Border pixels are skipped because they lack a full set of neighbours.
 * Returns 0 for images too small to have an interior.
 */
internal fun laplacianVariance(luma: IntArray, width: Int, height: Int): Double {
    if (width < 3 || height < 3) return 0.0

    var sum = 0.0
    var sumOfSquares = 0.0
    var count = 0
    for (y in 1 until height - 1) {
        for (x in 1 until width - 1) {
            val center = luma[y * width + x]
            val laplacian = 4 * center -
                luma[(y - 1) * width + x] - luma[(y + 1) * width + x] -
                luma[y * width + x - 1] - luma[y * width + x + 1]
            sum += laplacian
            sumOfSquares += laplacian.toDouble() * laplacian
            count++
        }
    }
    val mean = sum / count
    return sumOfSquares / count - mean * mean
}
