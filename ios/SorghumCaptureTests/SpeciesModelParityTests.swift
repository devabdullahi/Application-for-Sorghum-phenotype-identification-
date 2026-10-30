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
/// The model is committed in `ios/SorghumCapture/Resources/Models/`, so a missing model fails.
/// The test skips only while no fixtures have been exported yet (the model export's
/// `--fixtures-dir shared/src/commonTest/resources/species`).
final class SpeciesModelParityTests: XCTestCase {

    /// Allowed difference per logit, in output quantization steps (`logitStep` in expected.json).
    /// iOS and TensorFlow run the same INT8 file on the same uint8 input, but their kernels may
    /// round an accumulator differently, which moves a logit by one step; two steps leaves room
    /// for that without hiding a real preprocessing difference, which moves logits much further.
    private let allowedLogitSteps: Float = 2

    /// Allowed difference in the calibrated sorghum probability between the iOS logits and the
    /// exported ones, both put through shared's softmax and temperature.
    private let probabilityTolerance: Float = 1e-3

    func testBundledModelReproducesTheExportedLogits() throws {
        let fixtures = try loadFixtures()
        let installed = try loadInstalledModel()
        guard fixtures.modelVersion == installed.version else {
            return XCTFail(
                "Fixtures are for traits-v\(fixtures.modelVersion) but traits-v\(installed.version) is bundled; export both together"
            )
        }
        guard let logitStep = fixtures.logitStep else {
            return XCTFail("expected.json has no logitStep (the species output's quantization step); re-export the fixtures")
        }
        XCTAssertFalse(fixtures.entries.isEmpty, "expected.json lists no fixtures")
        let logitTolerance = allowedLogitSteps * logitStep

        // Reported at the end, so a passing run still records how close iOS and the export are.
        var largestLogitDifferenceInSteps: Float = 0
        var matchingTopClassCount = 0

        let recorder = RecordingImageModel(wrapping: installed.model)
        guard let gate = loadGate(metadataJson: installed.metadataJson, model: recorder) else {
            return XCTFail("traits-v\(installed.version).json was refused by shared/")
        }

        for fixture in fixtures.entries {
            let photo = try decodeFixture(fixture.image, in: fixtures.directory, expectedSize: installed.inputSize)
            recorder.reset()
            let iosCheck = gate.check(photo: photo)

            // A wrong output count or logit count stops inside SpeciesGate.check before this
            // point; turning that into a load failure is a shared/ follow-up (PR #12 review item 5).
            let outputs = try XCTUnwrap(recorder.lastOutputs, "\(fixture.image): the model returned no outputs")
            let logits = outputs[installed.speciesOutputIndex]
            // The gate does not check the fixture side, and the exported-logits gate below would
            // stop on a count mismatch.
            guard logits.count == fixture.logits.count else {
                XCTFail("\(fixture.image): \(logits.count) logits on iOS, \(fixture.logits.count) in expected.json")
                continue
            }
            for (index, (actual, expected)) in zip(logits, fixture.logits).enumerated() {
                largestLogitDifferenceInSteps = max(largestLogitDifferenceInSteps, abs(actual - expected) / logitStep)
                XCTAssertEqual(
                    actual, expected, accuracy: logitTolerance,
                    "\(fixture.image) (\(fixture.classId)): logit \(index) is \(actual) on iOS, \(expected) in the export"
                )
            }
            if indexOfLargest(logits) == indexOfLargest(fixture.logits) {
                matchingTopClassCount += 1
            }
            XCTAssertEqual(
                indexOfLargest(logits), indexOfLargest(fixture.logits),
                "\(fixture.image) (\(fixture.classId)): iOS and the export predict different classes"
            )

            // shared/ keeps softmax and temperature internal, so the exported logits go through
            // the same gate and the calibrated sorghum probabilities are compared.
            let exportedModel = FixedLogitsImageModel(logits: fixture.logits, outputIndex: installed.speciesOutputIndex)
            let exportedGate = try XCTUnwrap(loadGate(metadataJson: installed.metadataJson, model: exportedModel))
            let exportedCheck = exportedGate.check(photo: photo)
            assertSameSorghumProbability(iosCheck, exportedCheck, fixture: fixture.image)
        }
        print(
            "Species parity traits-v\(installed.version): largest logit difference \(largestLogitDifferenceInSteps) steps "
                + "(allowed \(allowedLogitSteps)), top class matches on \(matchingTopClassCount)/\(fixtures.entries.count) fixtures"
        )
    }

    /// Asserts both checks carry the same calibrated sorghum probability, within tolerance.
    /// `NoPlant` carries none, so then both must be `NoPlant`.
    private func assertSameSorghumProbability(_ iosCheck: SpeciesCheck, _ exportedCheck: SpeciesCheck, fixture: String) {
        guard let iosProbability = sorghumProbability(of: iosCheck),
              let exportedProbability = sorghumProbability(of: exportedCheck)
        else {
            XCTAssertTrue(
                iosCheck is SpeciesCheckNoPlant && exportedCheck is SpeciesCheckNoPlant,
                "\(fixture): the check is \(iosCheck) on iOS but \(exportedCheck) from the exported logits"
            )
            return
        }
        XCTAssertEqual(
            iosProbability, exportedProbability, accuracy: probabilityTolerance,
            "\(fixture): P(sorghum) is \(iosProbability) on iOS, \(exportedProbability) from the exported logits"
        )
    }

    private func sorghumProbability(of check: SpeciesCheck) -> Float? {
        switch check {
        case let sorghum as SpeciesCheckSorghum: return sorghum.sorghumProbability
        case let notSorghum as SpeciesCheckNotSorghum: return notSorghum.sorghumProbability
        case let unsure as SpeciesCheckUnsure: return unsure.sorghumProbability
        default: return nil
        }
    }

    private func indexOfLargest(_ values: [Float]) -> Int? {
        values.indices.max { values[$0] < values[$1] }
    }

    private func loadGate(metadataJson: String, model: ImageModel) -> SpeciesGate? {
        (SpeciesGateKt.loadSpeciesGate(metadataJson: metadataJson, model: model) as? SpeciesGateLoadLoaded)?.gate
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
        let logitStep: Float?
        let entries: [Fixture]
        let directory: URL
    }

    /// The parts of `expected.json` the test reads. `logitStep` is the species output's
    /// quantization step in logit units; it is optional here so an older export fails with a
    /// clear message instead of a decoding error.
    private struct ExpectedDocument: Decodable {
        let modelVersion: Int
        let head: String
        let logitStep: Float?
        let fixtures: [Fixture]
    }

    /// Reads `expected.json` from the test bundle; skips the test while no fixtures are exported.
    private func loadFixtures() throws -> FixtureSet {
        // project.yml copies shared/src/commonTest/resources/species into the test bundle.
        guard let url = Bundle(for: Self.self).url(forResource: "expected", withExtension: "json", subdirectory: "species") else {
            throw XCTSkip("No species parity fixtures: export them into shared/src/commonTest/resources/species")
        }
        let document = try JSONDecoder().decode(ExpectedDocument.self, from: Data(contentsOf: url))
        XCTAssertEqual(document.head, "species", "expected.json is for another head")
        return FixtureSet(
            modelVersion: document.modelVersion,
            logitStep: document.logitStep,
            entries: document.fixtures,
            directory: url.deletingLastPathComponent()
        )
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

    /// The parts of `traits-vN.json` the test needs to find the species logits and check the
    /// fixture size. shared/ validates the full document when the gate loads.
    private struct MetadataDocument: Decodable {
        struct Input: Decodable { let widthPx: Int; let heightPx: Int }
        struct Head: Decodable { let outputIndex: Int }
        let input: Input
        let heads: [String: Head]
    }

    /// Loads the highest bundled model version, as the app does. Fails when none is bundled,
    /// because the model is committed with its fixtures.
    private func loadInstalledModel() throws -> InstalledModel {
        let bundle = Bundle.main
        let version = try XCTUnwrap(
            BundledSpeciesModel.highestModelVersion(in: bundle),
            "Fixtures are exported but no species model is bundled: run ios/scripts/install-species-model.sh <export-dir> and commit the files"
        )
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

    /// Forgets the last outputs, so a check that never reaches the model cannot be compared
    /// against the previous fixture's logits.
    func reset() {
        lastOutputs = nil
    }

    func run(inputTensor: KotlinByteArray) -> [KotlinFloatArray] {
        let outputs = model.run(inputTensor: inputTensor)
        lastOutputs = outputs.map { tensor in (0..<tensor.size).map { tensor.get(index: $0) } }
        return outputs
    }
}

/// Returns fixed species logits at the species output index, so the exported logits can go
/// through shared's softmax, temperature and decision exactly as the iOS logits do.
private final class FixedLogitsImageModel: NSObject, ImageModel {
    private let outputs: [KotlinFloatArray]

    init(logits: [Float], outputIndex: Int) {
        let species = KotlinFloatArray(size: Int32(logits.count))
        for (index, logit) in logits.enumerated() {
            species.set(index: Int32(index), value: logit)
        }
        // Other heads are not read by the species gate, so empty outputs stand in for them.
        var outputs = (0..<outputIndex).map { _ in KotlinFloatArray(size: 0) }
        outputs.append(species)
        self.outputs = outputs
    }

    func run(inputTensor: KotlinByteArray) -> [KotlinFloatArray] {
        outputs
    }
}
