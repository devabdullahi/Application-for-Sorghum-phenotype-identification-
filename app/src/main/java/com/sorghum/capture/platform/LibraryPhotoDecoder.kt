package com.sorghum.capture.platform

import android.content.ContentResolver
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.ImageDecoder
import android.graphics.Matrix
import android.media.ExifInterface
import android.net.Uri
import android.os.Build
import android.util.Log
import androidx.annotation.RequiresApi
import com.sorghum.capture.camera.scaledToLongSide
import java.io.IOException
import kotlin.math.max
import kotlin.math.roundToInt

private const val TAG = "LibraryPhotoDecoder"

/**
 * Reads a photo picked from the photo library into memory, upright and scaled so its longer
 * side is at most [maxLongSidePixels]. Nothing is copied to the app's storage.
 *
 * Returns null if the photo cannot be read as an image. Blocking: call it off the main thread.
 */
fun decodeLibraryPhoto(contentResolver: ContentResolver, photoUri: Uri, maxLongSidePixels: Int): Bitmap? =
    try {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            decodeWithImageDecoder(contentResolver, photoUri, maxLongSidePixels)
        } else {
            decodeWithBitmapFactory(contentResolver, photoUri, maxLongSidePixels)
        }
    } catch (exception: IOException) {
        Log.e(TAG, "Could not read the picked photo", exception)
        null
    } catch (exception: SecurityException) {
        // The picker grants temporary read access; this means that grant was missing or revoked.
        Log.e(TAG, "No permission to read the picked photo", exception)
        null
    }

/** API 28+. ImageDecoder applies the EXIF orientation itself. */
@RequiresApi(Build.VERSION_CODES.P)
private fun decodeWithImageDecoder(contentResolver: ContentResolver, photoUri: Uri, maxLongSidePixels: Int): Bitmap {
    val source = ImageDecoder.createSource(contentResolver, photoUri)
    return ImageDecoder.decodeBitmap(source) { decoder, info, _ ->
        // Software memory, because the photo checks read pixels, which hardware bitmaps do not allow.
        decoder.allocator = ImageDecoder.ALLOCATOR_SOFTWARE
        val longSide = max(info.size.width, info.size.height)
        if (longSide > maxLongSidePixels) {
            val scale = maxLongSidePixels.toFloat() / longSide
            decoder.setTargetSize(
                (info.size.width * scale).roundToInt().coerceAtLeast(1),
                (info.size.height * scale).roundToInt().coerceAtLeast(1),
            )
        }
    }
}

/**
 * API 24-27. Decodes at the largest power-of-two reduction that stays above [maxLongSidePixels],
 * so a large photo never needs its full size in memory, then rotates it upright from its EXIF tag.
 */
private fun decodeWithBitmapFactory(contentResolver: ContentResolver, photoUri: Uri, maxLongSidePixels: Int): Bitmap? {
    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    contentResolver.openInputStream(photoUri)?.use { BitmapFactory.decodeStream(it, null, bounds) } ?: return null
    if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null

    val longSide = max(bounds.outWidth, bounds.outHeight)
    var sampleSize = 1
    while (longSide / (sampleSize * 2) >= maxLongSidePixels) sampleSize *= 2
    val decodeOptions = BitmapFactory.Options().apply { inSampleSize = sampleSize }
    val decoded = contentResolver.openInputStream(photoUri)
        ?.use { BitmapFactory.decodeStream(it, null, decodeOptions) }
        ?: return null

    val rotationDegrees = contentResolver.openInputStream(photoUri)?.use { exifRotationDegrees(ExifInterface(it)) } ?: 0
    val upright = if (rotationDegrees == 0) {
        decoded
    } else {
        val rotation = Matrix().apply { postRotate(rotationDegrees.toFloat()) }
        Bitmap.createBitmap(decoded, 0, 0, decoded.width, decoded.height, rotation, true)
            .also { if (it !== decoded) decoded.recycle() }
    }
    return upright.scaledToLongSide(maxLongSidePixels)
}

/** Clockwise rotation that makes the photo upright. Mirrored orientations are rare and ignored. */
private fun exifRotationDegrees(exif: ExifInterface): Int =
    when (exif.getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL)) {
        ExifInterface.ORIENTATION_ROTATE_90 -> 90
        ExifInterface.ORIENTATION_ROTATE_180 -> 180
        ExifInterface.ORIENTATION_ROTATE_270 -> 270
        else -> 0
    }
