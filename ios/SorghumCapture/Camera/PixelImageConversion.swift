import Accelerate
import CoreVideo
import Shared

/// A rectangle of a camera buffer in its own pixels (sensor orientation).
struct BufferRegion: Equatable {
    let left: Int
    let top: Int
    let width: Int
    let height: Int
}

/// Converts the part of a BGRA camera buffer inside `region` (fractions of the buffer size, as
/// returned by `metadataOutputRectConverted`) into the shared core's upright `PixelImage`.
///
/// This is the iOS app's only conversion into the shared image format, used for live frames and
/// photos alike. The region is scaled down with filtering (vImage, like Android's filtered
/// Bitmap scaling) so its longer side is at most `maxLongSide`, then turned upright.
/// Returns nil if the region does not overlap the buffer.
func uprightPixelImage(of pixelBuffer: CVPixelBuffer, in region: CGRect, maxLongSide: Int) -> PixelImage? {
    let bufferWidth = CVPixelBufferGetWidth(pixelBuffer)
    let bufferHeight = CVPixelBufferGetHeight(pixelBuffer)
    guard let pixelRegion = bufferRegion(of: region, bufferWidth: bufferWidth, bufferHeight: bufferHeight) else {
        return nil
    }

    CVPixelBufferLockBaseAddress(pixelBuffer, .readOnly)
    defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, .readOnly) }
    guard let baseAddress = CVPixelBufferGetBaseAddress(pixelBuffer) else { return nil }

    return uprightPixelImage(
        bgra: baseAddress.assumingMemoryBound(to: UInt8.self),
        bytesPerRow: CVPixelBufferGetBytesPerRow(pixelBuffer),
        region: pixelRegion,
        maxLongSide: maxLongSide
    )
}

/// The region in whole buffer pixels, clipped to the buffer, or nil if nothing is left.
func bufferRegion(of region: CGRect, bufferWidth: Int, bufferHeight: Int) -> BufferRegion? {
    let bufferBounds = CGRect(x: 0, y: 0, width: bufferWidth, height: bufferHeight)
    let pixels = CGRect(
        x: region.minX * CGFloat(bufferWidth),
        y: region.minY * CGFloat(bufferHeight),
        width: region.width * CGFloat(bufferWidth),
        height: region.height * CGFloat(bufferHeight)
    ).integral.intersection(bufferBounds)
    guard !pixels.isEmpty else { return nil }
    return BufferRegion(left: Int(pixels.minX), top: Int(pixels.minY), width: Int(pixels.width), height: Int(pixels.height))
}

/// The size the region is scaled to: the longer side becomes at most `maxLongSide`, keeping the
/// aspect ratio. Regions already small enough keep their size.
func scaledSize(of region: BufferRegion, maxLongSide: Int) -> (width: Int, height: Int) {
    let longSide = max(region.width, region.height)
    guard longSide > maxLongSide else { return (region.width, region.height) }
    let scale = Double(maxLongSide) / Double(longSide)
    return (max(1, Int((Double(region.width) * scale).rounded())), max(1, Int((Double(region.height) * scale).rounded())))
}

/// Crops `region` out of a BGRA buffer, scales it to at most `maxLongSide`, and turns it upright.
func uprightPixelImage(bgra: UnsafePointer<UInt8>, bytesPerRow: Int, region: BufferRegion, maxLongSide: Int) -> PixelImage? {
    let (scaledWidth, scaledHeight) = scaledSize(of: region, maxLongSide: maxLongSide)
    let scaledBytesPerRow = scaledWidth * 4
    var scaled = [UInt8](repeating: 0, count: scaledBytesPerRow * scaledHeight)

    // vImage reads the region in place: the source buffer starts at the region's first pixel
    // and keeps the full buffer's row stride. It never writes to the source.
    var source = vImage_Buffer(
        data: UnsafeMutableRawPointer(mutating: bgra + region.top * bytesPerRow + region.left * 4),
        height: vImagePixelCount(region.height),
        width: vImagePixelCount(region.width),
        rowBytes: bytesPerRow
    )
    let error = scaled.withUnsafeMutableBytes { scaledBytes in
        var destination = vImage_Buffer(
            data: scaledBytes.baseAddress,
            height: vImagePixelCount(scaledHeight),
            width: vImagePixelCount(scaledWidth),
            rowBytes: scaledBytesPerRow
        )
        return vImageScale_ARGB8888(&source, &destination, nil, vImage_Flags(kvImageHighQualityResampling))
    }
    guard error == kvImageNoError else { return nil }

    return scaled.withUnsafeBufferPointer { scaledPixels in
        uprightPixelImage(bgra: scaledPixels.baseAddress!, bytesPerRow: scaledBytesPerRow, width: scaledWidth, height: scaledHeight)
    }
}

/// How the BGRA pixels must be turned to be upright.
enum BufferOrientation {
    /// Back-camera buffers: landscape (sensor orientation). In this portrait-only app the upright
    /// image is the buffer turned 90° clockwise.
    case sensorLandscape
    /// Already upright, e.g. a library photo drawn with its orientation applied.
    case upright
}

/// Core of the conversion, split out so channel order, row padding and rotation can be tested
/// with a hand-made buffer.
///
/// For `.sensorLandscape` the upright image is `height` pixels wide, and upright pixel (x, y)
/// comes from buffer column y, row (height - 1 - x).
func uprightPixelImage(
    bgra: UnsafePointer<UInt8>,
    bytesPerRow: Int,
    width: Int,
    height: Int,
    orientation: BufferOrientation = .sensorLandscape
) -> PixelImage? {
    guard width > 0, height > 0 else { return nil }

    let isTurned = orientation == .sensorLandscape
    let uprightWidth = isTurned ? height : width
    let uprightHeight = isTurned ? width : height
    let bytesPerPixel = Int(PixelImage.companion.BYTES_PER_PIXEL)
    let rgb = KotlinByteArray(size: Int32(uprightWidth * uprightHeight * bytesPerPixel))

    for uprightY in 0..<uprightHeight {
        for uprightX in 0..<uprightWidth {
            let source = isTurned
                ? (height - 1 - uprightX) * bytesPerRow + uprightY * 4
                : uprightY * bytesPerRow + uprightX * 4
            let target = Int32((uprightY * uprightWidth + uprightX) * bytesPerPixel)
            // BGRA source, RGB target.
            rgb.set(index: target, value: Int8(bitPattern: bgra[source + 2]))
            rgb.set(index: target + 1, value: Int8(bitPattern: bgra[source + 1]))
            rgb.set(index: target + 2, value: Int8(bitPattern: bgra[source]))
        }
    }
    return PixelImage(width: Int32(uprightWidth), height: Int32(uprightHeight), rgb: rgb)
}
