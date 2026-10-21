import XCTest
@testable import SorghumCapture

final class TargetFrameTests: XCTestCase {
    func testFrameIsCentredWithRequestedWidthAndAspectRatio() {
        let rect = TargetFrame(widthFraction: 0.8, aspectRatio: 0.5).rect(in: CGSize(width: 1000, height: 2000))

        XCTAssertEqual(rect, CGRect(x: 100, y: 200, width: 800, height: 1600))
    }

    func testFrameTallerThanTheAreaIsShrunkToFitKeepingAspectRatio() {
        // Requested 800x1600 does not fit in a 1000x800 area; shrunk to 400x800.
        let rect = TargetFrame(widthFraction: 0.8, aspectRatio: 0.5).rect(in: CGSize(width: 1000, height: 800))

        XCTAssertEqual(rect, CGRect(x: 300, y: 0, width: 400, height: 800))
    }
}
