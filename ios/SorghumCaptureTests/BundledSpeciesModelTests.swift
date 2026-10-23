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

    /// Whatever is installed in Resources/Models must behave: no model means no gate (the app
    /// runs without the species check), and an installed model must load, so a broken export
    /// fails here rather than silently turning the species check off.
    func testBundledModelLoadsOrIsAbsent() {
        let gate = BundledSpeciesModel.loadGate()

        if let version = BundledSpeciesModel.highestModelVersion(in: .main) {
            XCTAssertNotNil(gate, "traits-v\(version) is bundled but was refused; see the SpeciesModel log")
        } else {
            XCTAssertNil(gate)
        }
    }
}
