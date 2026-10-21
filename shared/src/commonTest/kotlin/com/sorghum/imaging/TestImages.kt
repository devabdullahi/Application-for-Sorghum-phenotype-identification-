package com.sorghum.imaging

/** A pixel colour for building test images; channels 0–255. */
data class Rgb(val red: Int, val green: Int, val blue: Int)

/** Builds a test image by asking [pixelAt] for the colour of every pixel. */
fun pixelImage(width: Int, height: Int, pixelAt: (x: Int, y: Int) -> Rgb): PixelImage {
    val rgb = ByteArray(width * height * PixelImage.BYTES_PER_PIXEL)
    for (y in 0 until height) {
        for (x in 0 until width) {
            val colour = pixelAt(x, y)
            val offset = (y * width + x) * PixelImage.BYTES_PER_PIXEL
            rgb[offset] = colour.red.toByte()
            rgb[offset + 1] = colour.green.toByte()
            rgb[offset + 2] = colour.blue.toByte()
        }
    }
    return PixelImage(width, height, rgb)
}

/** Builds a test image filled with one colour. */
fun uniformImage(width: Int, height: Int, colour: Rgb): PixelImage = pixelImage(width, height) { _, _ -> colour }
