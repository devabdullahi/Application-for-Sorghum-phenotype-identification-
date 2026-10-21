import CoreGraphics
import Shared
import UIKit

/// Converts a photo picked from the photo library into the shared `PixelImage`, scaled so its
/// longer side is at most `maxLongSide`.
///
/// The photo is drawn upright first (UIKit applies its EXIF orientation), into a BGRA bitmap,
/// then goes through the same `uprightPixelImage` core as camera frames. The whole photo is
/// used: library photos have no target frame. Returns nil if the image has no pixels.
func pixelImage(ofLibraryPhoto photo: UIImage, maxLongSide: Int) -> PixelImage? {
    let pointSize = photo.size
    guard pointSize.width > 0, pointSize.height > 0 else { return nil }
    let pixelWidth = pointSize.width * photo.scale
    let pixelHeight = pointSize.height * photo.scale
    let scale = min(1, CGFloat(maxLongSide) / max(pixelWidth, pixelHeight))
    let width = max(1, Int((pixelWidth * scale).rounded()))
    let height = max(1, Int((pixelHeight * scale).rounded()))

    // Little-endian 32-bit with alpha first puts bytes in memory as B, G, R, A, like the
    // camera's kCVPixelFormatType_32BGRA. Photos are opaque, so premultiplying changes nothing.
    let bytesPerRow = width * 4
    var bgra = [UInt8](repeating: 0, count: bytesPerRow * height)
    let isDrawn = bgra.withUnsafeMutableBytes { buffer -> Bool in
        guard let context = CGContext(
            data: buffer.baseAddress,
            width: width,
            height: height,
            bitsPerComponent: 8,
            bytesPerRow: bytesPerRow,
            space: CGColorSpace(name: CGColorSpace.sRGB)!,
            bitmapInfo: CGImageAlphaInfo.premultipliedFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue
        ) else { return false }
        context.interpolationQuality = .high
        // UIKit drawing applies the photo's orientation; flip so its y-down matches the bitmap's rows.
        UIGraphicsPushContext(context)
        context.translateBy(x: 0, y: CGFloat(height))
        context.scaleBy(x: 1, y: -1)
        photo.draw(in: CGRect(x: 0, y: 0, width: width, height: height))
        UIGraphicsPopContext()
        return true
    }
    guard isDrawn else { return nil }

    return bgra.withUnsafeBufferPointer { pixels in
        uprightPixelImage(bgra: pixels.baseAddress!, bytesPerRow: bytesPerRow, width: width, height: height, orientation: .upright)
    }
}
