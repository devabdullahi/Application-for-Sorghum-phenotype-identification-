import XCTest
@testable import SorghumCapture

final class GreenCoverageTests: XCTestCase {
    private let settings = GreenDetectionSettings()
    private let tolerance = 0.0001

    private let leafGreen = RGBPixel(red: 60, green: 140, blue: 50)
    private let whiteBoard = RGBPixel(red: 230, green: 230, blue: 225)
    private let brownBoard = RGBPixel(red: 120, green: 90, blue: 60)
    private let darkGreenNoise = RGBPixel(red: 5, green: 20, blue: 5)
    // Excess green (2*120 - 100 - 80) / 300 = 0.2: halfway between the 0.1 threshold and 0.3.
    private let dullGreen = RGBPixel(red: 100, green: 120, blue: 80)

    func testLeafGreenIsClassifiedAsPlant() {
        XCTAssertTrue(isPlantPixel(leafGreen, settings: settings))
    }

    func testWhiteAndBrownBoardsAreNotPlant() {
        XCTAssertFalse(isPlantPixel(whiteBoard, settings: settings))
        XCTAssertFalse(isPlantPixel(brownBoard, settings: settings))
    }

    func testVeryDarkPixelsAreIgnoredEvenIfGreenish() {
        XCTAssertFalse(isPlantPixel(darkGreenNoise, settings: settings))
    }

    func testEmptyBoardHasNoCoverage() {
        let pixels = Array(repeating: whiteBoard, count: 100 * 100)

        let coverage = measureSampleCoverage(pixels: pixels, width: 100, height: 100, settings: settings)

        XCTAssertEqual(coverage.greenFraction, 0, accuracy: tolerance)
        XCTAssertEqual(coverage.edgeGreenFraction, 0, accuracy: tolerance)
    }

    func testSampleInTheMiddleIsCoveredButDoesNotTouchTheEdge() {
        // Green square from 25 to 75 on a 100x100 white board: a quarter of the area.
        let pixels = image(width: 100, height: 100) { x, y in
            (25..<75).contains(x) && (25..<75).contains(y) ? leafGreen : whiteBoard
        }

        let coverage = measureSampleCoverage(pixels: pixels, width: 100, height: 100, settings: settings)

        XCTAssertEqual(coverage.greenFraction, 0.25, accuracy: tolerance)
        XCTAssertEqual(coverage.edgeGreenFraction, 0, accuracy: tolerance)
    }

    func testSampleCrossingTheLeftBorderShowsUpInTheEdgeBand() {
        // Green strip along the whole left side, 10 pixels wide.
        let pixels = image(width: 100, height: 100) { x, _ in x < 10 ? leafGreen : whiteBoard }

        let coverage = measureSampleCoverage(pixels: pixels, width: 100, height: 100, settings: settings)

        XCTAssertEqual(coverage.greenFraction, 0.1, accuracy: tolerance)
        XCTAssertGreaterThan(coverage.edgeGreenFraction, 0.2)
    }

    func testTinyRegionsStillGetAOnePixelEdgeBand() {
        let pixels = Array(repeating: leafGreen, count: 4)

        let coverage = measureSampleCoverage(pixels: pixels, width: 2, height: 2, settings: settings)

        XCTAssertEqual(coverage.edgeGreenFraction, 1, accuracy: tolerance)
    }

    func testClearlyGreenLeafHasFullConfidence() {
        let pixels = Array(repeating: leafGreen, count: 100)

        let coverage = measureSampleCoverage(pixels: pixels, width: 10, height: 10, settings: settings)

        XCTAssertEqual(coverage.greenConfidence, 1, accuracy: tolerance)
    }

    func testDullGreenHalfwayPastTheThresholdHasHalfConfidence() {
        let pixels = Array(repeating: dullGreen, count: 100)

        let coverage = measureSampleCoverage(pixels: pixels, width: 10, height: 10, settings: settings)

        XCTAssertEqual(coverage.greenFraction, 1, accuracy: tolerance)
        XCTAssertEqual(coverage.greenConfidence, 0.5, accuracy: tolerance)
    }

    func testConfidenceAveragesOverGreenPixelsOnlyNotTheBoard() {
        // Left half clear leaf, right quarter dull green, rest white board.
        let pixels = image(width: 100, height: 100) { x, _ in
            if x < 50 { return leafGreen }
            if x < 75 { return dullGreen }
            return whiteBoard
        }

        let coverage = measureSampleCoverage(pixels: pixels, width: 100, height: 100, settings: settings)

        // (50 * 1.0 + 25 * 0.5) / 75 green columns.
        XCTAssertEqual(coverage.greenConfidence, 0.8333, accuracy: tolerance)
    }

    func testNoGreenPixelsMeansZeroConfidence() {
        let pixels = Array(repeating: whiteBoard, count: 100)

        let coverage = measureSampleCoverage(pixels: pixels, width: 10, height: 10, settings: settings)

        XCTAssertEqual(coverage.greenConfidence, 0, accuracy: tolerance)
    }

    private func image(width: Int, height: Int, pixelAt: (_ x: Int, _ y: Int) -> RGBPixel) -> [RGBPixel] {
        (0..<(width * height)).map { index in pixelAt(index % width, index / width) }
    }
}
