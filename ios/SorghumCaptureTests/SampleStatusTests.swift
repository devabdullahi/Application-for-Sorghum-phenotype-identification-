import XCTest
@testable import SorghumCapture

final class SampleStatusTests: XCTestCase {
    private let settings = SampleStatusSettings()

    func testTooLittleGreenMeansNoSample() {
        let coverage = SampleCoverage(greenFraction: 0.01, edgeGreenFraction: 0, greenConfidence: 1)

        XCTAssertEqual(sampleStatus(for: coverage, settings: settings), .noSample)
    }

    func testGreenInTheEdgeBandMeansCutOff() {
        let coverage = SampleCoverage(greenFraction: 0.3, edgeGreenFraction: 0.2, greenConfidence: 1)

        XCTAssertEqual(sampleStatus(for: coverage, settings: settings), .cutOff)
    }

    func testEnoughGreenAwayFromTheEdgeMeansInFrame() {
        let coverage = SampleCoverage(greenFraction: 0.3, edgeGreenFraction: 0.01, greenConfidence: 1)

        XCTAssertEqual(sampleStatus(for: coverage, settings: settings), .inFrame)
    }

    func testNoSampleTakesPriorityOverCutOff() {
        // A thin sliver of green along one edge is not yet a sample to frame.
        let coverage = SampleCoverage(greenFraction: 0.01, edgeGreenFraction: 0.5, greenConfidence: 1)

        XCTAssertEqual(sampleStatus(for: coverage, settings: settings), .noSample)
    }
}
