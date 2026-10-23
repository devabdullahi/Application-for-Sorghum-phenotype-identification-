package com.sorghum.segmentation

import com.sorghum.imaging.PhotoType
import com.sorghum.imaging.PixelImage

/**
 * Settings for every sample detector, so a caller holds one value whatever the photo type.
 *
 * @param green the excess-green detector, used for leaves.
 * @param contrast the board-contrast detector, used for panicles and grain.
 */
data class SampleDetectionSettings(
    val green: GreenDetectionSettings = GreenDetectionSettings(),
    val contrast: ContrastMaskSettings = ContrastMaskSettings(),
)

/**
 * Finds the sample in a board photo with the detector that suits its [photoType]:
 * - [PhotoType.LEAF]: excess-green ([measureGreenMask]); leaves are green and boards are not.
 * - [PhotoType.PANICLE] and [PhotoType.GRAIN]: contrast with the board ([measureContrastMask]);
 *   they are often brown, red, white or black, which the green mask misses.
 *
 * This is the one detector for live guidance (frames at [LIVE_ANALYSIS_LONG_SIDE_PIXELS]) and
 * the post-capture check (photos at the quality-check size), so both agree on what "sample
 * present" means. Do not add a faster variant for live frames.
 */
fun detectSampleMask(image: PixelImage, photoType: PhotoType, settings: SampleDetectionSettings): SampleMask =
    when (photoType) {
        PhotoType.LEAF -> measureGreenMask(image, settings.green)
        PhotoType.PANICLE, PhotoType.GRAIN -> measureContrastMask(image, settings.contrast)
    }
