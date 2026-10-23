import Shared
import UIKit
import XCTest
@testable import SorghumCapture

/// Model parity on iOS (risk R7): the bundled species model, run the way the app runs it, must
/// reproduce the logits that `model/` recorded for the same fixture images with the INT8 model
/// in TensorFlow (`model/sorghum_model/export.py`, `_write_fixtures`).
///
/// The path under test is the app's: PNG -> `pixelImage(ofLibraryPhoto:)` -> `SpeciesGate.check`
/// (shared crop, resize and quantization) -> `LiteRTImageModel`. Fixtures are stored at the model
/// input size, so the shared resize returns the image unchanged and only decoding, quantization
/// and inference are compared.
///
/// Skips when the model or the fixtures are not installed (`ios/scripts/install-species-model.sh`,
/// and the model export's `--fixtures-dir shared/src/commonTest/resources/species`).
final class SpeciesModelParityTests: XCTestCase {

    /// Largest allowed absolute difference per logit. Both sides run the same INT8 file on the
    /// same uint8 input and dequantize the same way, so they should agree to float rounding;
    /// a real kernel or preprocessing difference moves a logit by at least one output step.
    private let logitTolerance: Float = 1e-4

    func testBundledModelReproducesTheExportedLogits() throws {
        let fixtures = try loadFixtures()
        let installed = try loadInstalledModel()
        XCTAssertEqual(
            fixtures.modelVersion, installed.version,
            "Fixtures are for traits-v\(fixtures.modelVersion) but traits-v\(installed.version) is bundled; export both together"
        )
        XCTAssertFalse(fixtures.entries.isEmpty, "expected.json lists no fixtures")

        let recorder = RecordingImageModel(wrapping: installed.model)
        guard let gate = (SpeciesGateKt.loadSpeciesGate(metadataJson: installed.metadataJson, model: recorder)
            as? SpeciesGateLoadLoaded)?.gate
        else {
            return XCTFail("traits-v\(installed.version).json was refused by shared/")
        }

        for fixture in fixtures.entries {
            let photo = try decodeFixture(fixture.image, in: fixtures.directory, expectedSize: installed.inputSize)
            _ = gate.check(photo: photo)

            let outputs = try XCTUnwrap(recorder.lastOutputs, "\(fixture.image): the model returned no outputs")
            XCTAssertGreaterThan(outputs.count, installed.speciesOutputIndex, "\(fixture.image): species output missing")
            guard outputs.count > installed.speciesOutputIndex else { continue }
            let logits = outputs[installed.speciesOutputIndex]
            XCTAssertEqual(logits.count, fixture.logits.count, "\(fixture.image): wrong number of logits")
            for (index, (actual, expected)) in zip(logits, fixture.logits).enumerated() {
                XCTAssertEqual(
                    actual, expected, accuracy: logitTolerance,
                    "\(fixture.image) (\(fixture.classId)): logit \(index) is \(actual) on iOS, \(expected) in the export"
                )
            }
        }
    }

    // MARK: - Fixtures

    /// One entry of `expected.json`.
    private struct Fixture: Decodable {
        let image: String
        let classId: String
        let logits: [Float]
    }

    /// `expected.json` as written by the model export, plus where its images are.
    private struct FixtureSet {
        let modelVersion: Int
        let entries: [Fixture]
        let directory: URL
    }

    private struct ExpectedDocument: Decodable {
        let modelVersion: Int
        let head: String
        let fixtures: [Fixture]
    }

    private func loadFixtures() throws -> FixtureSet {
        // project.yml copies shared/src/commonTest/resources/species into the test bundle.
        guard let url = Bundle(for: Self.self).url(forResource: "expected", withExtension: "json", subdirectory: "species") else {
            throw XCTSkip("No species parity fixtures: export them into shared/src/commonTest/resources/species")
        }
        let document = try JSONDecoder().decode(ExpectedDocument.self, from: Data(contentsOf: url))
        XCTAssertEqual(document.head, "species", "expected.json is for another head")
        return FixtureSet(modelVersion: document.modelVersion, entries: document.fixtures, directory: url.deletingLastPathComponent())
    }

    /// Decodes a fixture PNG with the app's library-photo converter, at its own size.
    private func decodeFixture(_ name: String, in directory: URL, expectedSize: (width: Int, height: Int)) throws -> PixelImage {
        let path = directory.appendingPathComponent(name).path
        let image = try XCTUnwrap(UIImage(contentsOfFile: path), "\(name) is missing or not an image")
        let cgImage = try XCTUnwrap(image.cgImage, "\(name) has no bitmap")
        let photo = try XCTUnwrap(pixelImage(ofLibraryPhoto: image, maxLongSide: max(cgImage.width, cgImage.height)))
        // At input size the shared resize is skipped, so the model sees the stored pixels.
        XCTAssertEqual(Int(photo.width), expectedSize.width, "\(name) is not at model input width")
        XCTAssertEqual(Int(photo.height), expectedSize.height, "\(name) is not at model input height")
        return photo
    }

    // MARK: - Installed model

    /// The bundled model and what the test needs from its metadata.
    private struct InstalledModel {
        let version: Int
        let metadataJson: String
        let model: LiteRTImageModel
        let speciesOutputIndex: Int
        let inputSize: (width: Int, height: Int)
    }

    private struct MetadataDocument: Decodable {
        struct Input: Decodable { let widthPx: Int; let heightPx: Int }
        struct Head: Decodable { let outputIndex: Int }
        let input: Input
        let heads: [String: Head]
    }

    private func loadInstalledModel() throws -> InstalledModel {
        let bundle = Bundle.main
        guard let version = BundledSpeciesModel.highestModelVersion(in: bundle) else {
            throw XCTSkip("No species model bundled: run ios/scripts/install-species-model.sh <export-dir>")
        }
        let metadataURL = try XCTUnwrap(bundle.url(forResource: "traits-v\(version)", withExtension: "json"))
        let modelPath = try XCTUnwrap(
            bundle.path(forResource: "traits-v\(version)", ofType: "tflite"), "traits-v\(version).tflite is not bundled"
        )
        let metadataData = try Data(contentsOf: metadataURL)
        let metadata = try JSONDecoder().decode(MetadataDocument.self, from: metadataData)
        let species = try XCTUnwrap(metadata.heads["species"], "traits-v\(version).json has no species head")
        return InstalledModel(
            version: version,
            metadataJson: String(decoding: metadataData, as: UTF8.self),
            model: try LiteRTImageModel(modelPath: modelPath),
            speciesOutputIndex: species.outputIndex,
            inputSize: (metadata.input.widthPx, metadata.input.heightPx)
        )
    }
}

/// Passes every call to the app's `LiteRTImageModel` and keeps the last outputs, so the test
/// sees the raw logits of the exact call the species gate made.
private final class RecordingImageModel: NSObject, ImageModel {
    private let model: LiteRTImageModel
    /// Outputs of the most recent `run`, as floats; nil before the first call.
    private(set) var lastOutputs: [[Float]]?

    init(wrapping model: LiteRTImageModel) {
        self.model = model
    }

    func run(inputTensor: KotlinByteArray) -> [KotlinFloatArray] {
        let outputs = model.run(inputTensor: inputTensor)
        lastOutputs = outputs.map { tensor in (0..<tensor.size).map { tensor.get(index: $0) } }
        return outputs
    }
}
