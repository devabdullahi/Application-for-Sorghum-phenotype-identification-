import Shared
import XCTest
@testable import SorghumCapture

final class PixelImageConversionTests: XCTestCase {

    /// 2 columns x 2 rows of BGRA, with 4 padding bytes per row like a real CVPixelBuffer.
    /// Buffer (sensor orientation):   A B
    ///                                C D
    /// Turned 90° clockwise to upright: C A
    ///                                  D B
    private let bytesPerRow = 12
    private let buffer: [UInt8] = [
        // Row 0: A = rgb(10, 20, 30), B = rgb(40, 50, 60), padding.
        30, 20, 10, 255, 60, 50, 40, 255, 0, 0, 0, 0,
        // Row 1: C = rgb(70, 80, 90), D = rgb(200, 210, 220), padding.
        90, 80, 70, 255, 220, 210, 200, 255, 0, 0, 0, 0,
    ]

    func testTwoByTwoBufferIsTurnedUprightWithRgbChannelOrder() throws {
        let image = try XCTUnwrap(buffer.withUnsafeBufferPointer {
            uprightPixelImage(bgra: $0.baseAddress!, bytesPerRow: bytesPerRow, width: 2, height: 2)
        })

        XCTAssertEqual(image.width, 2)
        XCTAssertEqual(image.height, 2)
        XCTAssertEqual(rgb(image, 0), [70, 80, 90])     // C, top-left
        XCTAssertEqual(rgb(image, 1), [10, 20, 30])     // A, top-right
        XCTAssertEqual(rgb(image, 2), [200, 210, 220])  // D, bottom-left
        XCTAssertEqual(rgb(image, 3), [40, 50, 60])     // B, bottom-right
    }

    func testRegionIsCroppedBeforeTurningUpright() throws {
        // Right column only (B above D), already small enough not to scale: upright D B.
        let region = BufferRegion(left: 1, top: 0, width: 1, height: 2)
        let image = try XCTUnwrap(buffer.withUnsafeBufferPointer {
            uprightPixelImage(bgra: $0.baseAddress!, bytesPerRow: bytesPerRow, region: region, maxLongSide: 160)
        })

        XCTAssertEqual(image.width, 2)
        XCTAssertEqual(image.height, 1)
        XCTAssertEqual(rgb(image, 0), [200, 210, 220])
        XCTAssertEqual(rgb(image, 1), [40, 50, 60])
    }

    func testLargeRegionIsScaledToTheLongSideLimitAndKeepsItsColour() throws {
        // 400 x 200 buffer of one colour: scaling must not shift the channels.
        let width = 400, height = 200
        let pixel: [UInt8] = [30, 140, 60, 255]  // BGRA for rgb(60, 140, 30)
        let uniform = [UInt8]((0..<(width * height)).flatMap { _ in pixel })
        let region = BufferRegion(left: 0, top: 0, width: width, height: height)

        let image = try XCTUnwrap(uniform.withUnsafeBufferPointer {
            uprightPixelImage(bgra: $0.baseAddress!, bytesPerRow: width * 4, region: region, maxLongSide: 160)
        })

        // Upright swaps the sides: 80 wide, 160 tall.
        XCTAssertEqual(image.width, 80)
        XCTAssertEqual(image.height, 160)
        XCTAssertEqual(rgb(image, 0), [60, 140, 30])
        XCTAssertEqual(rgb(image, image.width * image.height - 1), [60, 140, 30])
    }

    func testScaledSizeKeepsSmallRegionsAndLimitsLargeOnes() {
        XCTAssertEqual(scaledSize(of: BufferRegion(left: 0, top: 0, width: 100, height: 50), maxLongSide: 160).width, 100)
        let large = scaledSize(of: BufferRegion(left: 0, top: 0, width: 1920, height: 960), maxLongSide: 640)
        XCTAssertEqual(large.width, 640)
        XCTAssertEqual(large.height, 320)
    }

    func testRegionOutsideTheBufferGivesNil() {
        XCTAssertNil(bufferRegion(of: CGRect(x: 2, y: 2, width: 0.5, height: 0.5), bufferWidth: 100, bufferHeight: 100))
    }

    private func rgb(_ image: PixelImage, _ pixelIndex: Int32) -> [Int32] {
        [image.redAt(pixelIndex: pixelIndex), image.greenAt(pixelIndex: pixelIndex), image.blueAt(pixelIndex: pixelIndex)]
    }
}
