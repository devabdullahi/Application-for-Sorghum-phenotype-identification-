import Shared
import UIKit
import XCTest
@testable import SorghumCapture

/// Model parity on iOS (risk R7) for the experimental basic-race output of traits-v3 (#45).
///
/// The fixtures are basic-race test photos at model input size, with the INT8 logits and the
/// answer that `model/` computed (`model/sorghum_model/bundle_export.py`). The path under test
/// is the app's: PNG -> `pixelImage(ofLibraryPhoto:)` -> `SpeciesGate.check` (shared crop,
/// resize and quantization) -> `LiteRTImageModel`. The race logits are output `outputIndex` of
/// that same call. Then shared `readBasicRace` must give the same answer from the iOS logits,
/// from the exported logits, and as `model/`'s Python answer rule.
///
/// The output is experimental and does not meet the race accuracy goal. This test checks only
/// that iOS reproduces it, not that it is good.
final class BasicRaceModelParityTests: XCTestCase {

    /// Allowed difference per logit, in output quantization steps, as in `SpeciesModelParityTests`.
    private let allowedLogitSteps: Float = 2

    func testBundledModelReproducesTheExportedBasicRaceLogitsAndAnswers() throws {
        let fixtures = try loadFixtures()
        let bundle = Bundle.main
        let version = try XCTUnwrap(BundledSpeciesModel.highestModelVersion(in: bundle), "no model is bundled")
        XCTAssertEqual(fixtures.modelVersion, Int(version), "fixtures and the bundled model must be exported together")

        let metadataURL = try XCTUnwrap(bundle.url(forResource: "traits-v\(version)", withExtension: "json"))
        let metadataJson = try String(contentsOf: metadataURL, encoding: .utf8)
        let modelPath = try XCTUnwrap(bundle.path(forResource: "traits-v\(version)", ofType: "tflite"))
        let recorder = RecordingImageModel(wrapping: try LiteRTImageModel(modelPath: modelPath))
        // Loading the gate validates the metadata first, so parsing it below cannot throw into Swift.
        let load = SpeciesGateKt.loadSpeciesGate(metadataJson: metadataJson, model: recorder)
        let gate = try XCTUnwrap((load as? SpeciesGateLoadLoaded)?.gate, "traits-v\(version).json was refused by shared/")
        let head = try XCTUnwrap(ModelMetadataKt.parseModelMetadata(json: metadataJson).basicRace, "no basicRace head")
        XCTAssertEqual(Int(head.outputIndex), fixtures.outputIndex)
        XCTAssertTrue(head.isExperimental, "basic-race-v1 misses its goal and must stay experimental")
        XCTAssertFalse(head.meetsAccuracyGoal)
        XCTAssertFalse(fixtures.entries.isEmpty, "expected.json lists no fixtures")

        var largestLogitDifferenceInSteps: Float = 0
        var matchingAnswerCount = 0
        for fixture in fixtures.entries {
            let photo = try decodeFixture(fixture.image, in: fixtures.directory)
            recorder.reset()
            _ = gate.check(photo: photo)
            let outputs = try XCTUnwrap(recorder.lastOutputs, "\(fixture.image): the model returned no outputs")
            let logits = try XCTUnwrap(outputs.indices.contains(fixtures.outputIndex) ? outputs[fixtures.outputIndex] : nil)
            guard logits.count == fixture.logits.count else {
                XCTFail("\(fixture.image): \(logits.count) logits on iOS, \(fixture.logits.count) in expected.json")
                continue
            }
            for (index, (actual, expected)) in zip(logits, fixture.logits).enumerated() {
                largestLogitDifferenceInSteps = max(largestLogitDifferenceInSteps, abs(actual - expected) / fixtures.logitStep)
                XCTAssertEqual(
                    actual, expected, accuracy: allowedLogitSteps * fixtures.logitStep,
                    "\(fixture.image): logit \(index) is \(actual) on iOS, \(expected) in the export"
                )
            }

            let iosAnswer = answer(of: BasicRaceKt.readBasicRace(outputs: floatArrays(outputs), head: head))
            let exportedAnswer = answer(of: BasicRaceKt.readBasicRace(outputs: exportedOutputs(fixture.logits, at: fixtures.outputIndex), head: head))
            XCTAssertEqual(iosAnswer, exportedAnswer, "\(fixture.image): shared/ answers differently from the iOS and exported logits")
            XCTAssertEqual(exportedAnswer, fixture.answer, "\(fixture.image): shared/ and model/ apply the answer rule differently")
            if iosAnswer == fixture.answer {
                matchingAnswerCount += 1
            }
        }
        print(
            "Basic-race parity traits-v\(version): largest logit difference \(largestLogitDifferenceInSteps) steps "
                + "(allowed \(allowedLogitSteps)), answer matches on \(matchingAnswerCount)/\(fixtures.entries.count) fixtures"
        )
    }

    /// The answered races, nil for "unrecognized". Fails the test for an unavailable reading
    /// and for one that is not marked experimental.
    private func answer(of reading: BasicRaceReading) -> [String]? {
        switch reading {
        case let answered as BasicRaceReadingAnswered:
            XCTAssertTrue(answered.isExperimental)
            return answered.races
        case let unrecognized as BasicRaceReadingUnrecognized:
            XCTAssertTrue(unrecognized.isExperimental)
            return nil
        default:
            XCTFail("the basic-race output could not be read: \(reading)")
            return ["unavailable"]
        }
    }

    private func floatArrays(_ outputs: [[Float]]) -> [KotlinFloatArray] {
        outputs.map { values in
            let array = KotlinFloatArray(size: Int32(values.count))
            for (index, value) in values.enumerated() {
                array.set(index: Int32(index), value: value)
            }
            return array
        }
    }

    /// The exported logits at the head's output index; other outputs are empty, as the
    /// basic-race reading does not read them.
    private func exportedOutputs(_ logits: [Float], at outputIndex: Int) -> [KotlinFloatArray] {
        floatArrays((0..<outputIndex).map { _ in [] } + [logits])
    }

    // MARK: - Fixtures

    private struct Fixture: Decodable {
        let image: String
        let race: String
        let logits: [Float]
        let answer: [String]?
    }

    private struct ExpectedDocument: Decodable {
        let modelVersion: Int
        let head: String
        let outputIndex: Int
        let logitStep: Float
        let fixtures: [Fixture]
    }

    private struct FixtureSet {
        let modelVersion: Int
        let outputIndex: Int
        let logitStep: Float
        let entries: [Fixture]
        let directory: URL
    }

    /// project.yml copies shared/src/commonTest/resources/basic-race into the test bundle.
    /// The fixtures are committed with traits-v3, so a missing file fails rather than skips.
    private func loadFixtures() throws -> FixtureSet {
        let url = try XCTUnwrap(
            Bundle(for: Self.self).url(forResource: "expected", withExtension: "json", subdirectory: "basic-race"),
            "No basic-race parity fixtures in the test bundle"
        )
        let document = try JSONDecoder().decode(ExpectedDocument.self, from: Data(contentsOf: url))
        XCTAssertEqual(document.head, "basicRace", "expected.json is for another head")
        return FixtureSet(
            modelVersion: document.modelVersion,
            outputIndex: document.outputIndex,
            logitStep: document.logitStep,
            entries: document.fixtures,
            directory: url.deletingLastPathComponent()
        )
    }

    private func decodeFixture(_ name: String, in directory: URL) throws -> PixelImage {
        let path = directory.appendingPathComponent(name).path
        let image = try XCTUnwrap(UIImage(contentsOfFile: path), "\(name) is missing or not an image")
        let cgImage = try XCTUnwrap(image.cgImage, "\(name) has no bitmap")
        return try XCTUnwrap(pixelImage(ofLibraryPhoto: image, maxLongSide: max(cgImage.width, cgImage.height)))
    }
}
