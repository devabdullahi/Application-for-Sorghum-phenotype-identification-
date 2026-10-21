import Shared
import UIKit
import XCTest
@testable import SorghumCapture

final class LibraryPhotoConversionTests: XCTestCase {

    /// 2 x 2 photo: top row red, bottom row blue.
    private func redOverBlue(orientation: UIImage.Orientation = .up) -> UIImage {
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        let image = UIGraphicsImageRenderer(size: CGSize(width: 2, height: 2), format: format).image { context in
            UIColor(red: 1, green: 0, blue: 0, alpha: 1).setFill()
            context.fill(CGRect(x: 0, y: 0, width: 2, height: 1))
            UIColor(red: 0, green: 0, blue: 1, alpha: 1).setFill()
            context.fill(CGRect(x: 0, y: 1, width: 2, height: 1))
        }
        return UIImage(cgImage: image.cgImage!, scale: 1, orientation: orientation)
    }

    func testTopRowStaysOnTopWithRgbChannelOrder() throws {
        let image = try XCTUnwrap(pixelImage(ofLibraryPhoto: redOverBlue(), maxLongSide: 640))

        XCTAssertEqual(image.width, 2)
        XCTAssertEqual(image.height, 2)
        XCTAssertEqual(rgb(image, 0), [255, 0, 0])  // top-left red
        XCTAssertEqual(rgb(image, 3), [0, 0, 255])  // bottom-right blue
    }

    func testPhotoOrientationIsApplied() throws {
        // .right means the stored pixels must be turned 90° clockwise to be upright:
        // the stored top row (red) ends up on the right.
        let image = try XCTUnwrap(pixelImage(ofLibraryPhoto: redOverBlue(orientation: .right), maxLongSide: 640))

        XCTAssertEqual(rgb(image, 1), [255, 0, 0])  // top-right red
        XCTAssertEqual(rgb(image, 0), [0, 0, 255])  // top-left blue
    }

    func testLargePhotoIsScaledToTheLongSideLimit() throws {
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        let large = UIGraphicsImageRenderer(size: CGSize(width: 1280, height: 960), format: format).image { context in
            UIColor.green.setFill()
            context.fill(CGRect(x: 0, y: 0, width: 1280, height: 960))
        }

        let image = try XCTUnwrap(pixelImage(ofLibraryPhoto: large, maxLongSide: 640))

        XCTAssertEqual(image.width, 640)
        XCTAssertEqual(image.height, 480)
    }

    private func rgb(_ image: PixelImage, _ pixelIndex: Int32) -> [Int32] {
        [image.redAt(pixelIndex: pixelIndex), image.greenAt(pixelIndex: pixelIndex), image.blueAt(pixelIndex: pixelIndex)]
    }
}
