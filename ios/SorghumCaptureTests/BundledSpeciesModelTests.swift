import XCTest
@testable import SorghumCapture

final class BundledSpeciesModelTests: XCTestCase {

    func testHighestVersionWins() {
        let names = ["traits-v1.json", "traits-v3.json", "traits-v2.json", "other.json"]

        XCTAssertEqual(BundledSpeciesModel.highestModelVersion(amongFileNames: names), 3)
    }

    func testFilesThatAreNotModelMetadataAreIgnored() {
        let names = ["traits-vX.json", "traits-v2.tflite", "cultivars-v1.json"]

        XCTAssertNil(BundledSpeciesModel.highestModelVersion(amongFileNames: names))
    }

    func testAppWithoutABundledModelHasNoGate() {
        // No model is bundled yet, so the app must run without the species check.
        XCTAssertNil(BundledSpeciesModel.loadGate())
    }
}
