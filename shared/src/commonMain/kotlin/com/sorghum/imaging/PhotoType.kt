package com.sorghum.imaging

/**
 * Which board photo is being taken or read. Each photo type has its own capture and guidance,
 * its own sample detector (see `segmentation`) and its own traits.
 *
 * Lives in `imaging` because `capture`, `segmentation` and `traits` all need it, and
 * `segmentation` may not depend on `traits` (traits -> segmentation in the module graph).
 */
enum class PhotoType {
    LEAF,
    PANICLE,
    GRAIN,
}
