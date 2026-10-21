import CoreVideo
import Shared

/// A rectangle of a camera buffer in its own pixels (sensor orientation). Right and bottom are
/// exclusive, like the shared `PixelRect`.
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
/// photos alike. The result's longer side is at most `maxLongSide`. Returns nil if the region
/// does not overlap the buffer.
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
        step: samplingStep(for: pixelRegion, maxLongSide: maxLongSide)
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

/// Takes every `step`-th pixel so the longer side ends up at most `maxLongSide`.
func samplingStep(for region: BufferRegion, maxLongSide: Int) -> Int {
    let longSide = max(region.width, region.height)
    return max(1, Int((Double(longSide) / Double(maxLongSide)).rounded(.up)))
}

/// Core of the conversion, split out so channel order, row padding and rotation can be tested
/// with a hand-made buffer.
///
/// The back camera's buffers are landscape (sensor orientation); in this portrait-only app the
/// upright image is the buffer turned 90° clockwise. So the upright image is `region.height`
/// samples wide, and upright pixel (x, y) comes from buffer column y, row (rows - 1 - x).
func uprightPixelImage(bgra: UnsafePointer<UInt8>, bytesPerRow: Int, region: BufferRegion, step: Int) -> PixelImage? {
    let sampledColumns = region.width / step
    let sampledRows = region.height / step
    guard sampledColumns > 0, sampledRows > 0 else { return nil }

    let uprightWidth = sampledRows
    let uprightHeight = sampledColumns
    let bytesPerPixel = Int(PixelImage.companion.BYTES_PER_PIXEL)
    let rgb = KotlinByteArray(size: Int32(uprightWidth * uprightHeight * bytesPerPixel))

    for uprightY in 0..<uprightHeight {
        let column = region.left + uprightY * step
        for uprightX in 0..<uprightWidth {
            let row = region.top + (sampledRows - 1 - uprightX) * step
            let source = row * bytesPerRow + column * 4
            let target = Int32((uprightY * uprightWidth + uprightX) * bytesPerPixel)
            // BGRA source, RGB target.
            rgb.set(index: target, value: Int8(bitPattern: bgra[source + 2]))
            rgb.set(index: target + 1, value: Int8(bitPattern: bgra[source + 1]))
            rgb.set(index: target + 2, value: Int8(bitPattern: bgra[source]))
        }
    }
    return PixelImage(width: Int32(uprightWidth), height: Int32(uprightHeight), rgb: rgb)
}
