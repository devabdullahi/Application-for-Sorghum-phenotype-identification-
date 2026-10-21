import Foundation
import Shared
import os

/// Where the species model comes from: `traits-vN.tflite` and `traits-vN.json` in the app bundle.
/// Put both files from `model/` export into `ios/SorghumCapture/Model/`, then run
/// `xcodegen generate && pod install`; the highest N found is used.
enum BundledSpeciesModel {
    private static let logger = Logger(subsystem: "com.sorghum.capture", category: "SpeciesModel")

    /// The species gate built from the bundled model, or nil when no usable model is bundled.
    /// Nil is not an error for the user: the app runs without the species check and says so
    /// (ARCHITECTURE.md section 4.3). Why it is nil goes to the system log.
    static func loadGate(from bundle: Bundle = .main) -> SpeciesGate? {
        guard let version = highestModelVersion(in: bundle) else {
            logger.info("No species model bundled; species check unavailable")
            return nil
        }
        guard let metadataURL = bundle.url(forResource: "traits-v\(version)", withExtension: "json"),
              let modelPath = bundle.path(forResource: "traits-v\(version)", ofType: "tflite"),
              let metadataJson = try? String(contentsOf: metadataURL, encoding: .utf8)
        else {
            logger.error("traits-v\(version) is incomplete: both .json and .tflite are needed")
            return nil
        }

        let model: LiteRTImageModel
        do {
            model = try LiteRTImageModel(modelPath: modelPath)
        } catch {
            logger.error("traits-v\(version).tflite could not be loaded: \(error.localizedDescription)")
            return nil
        }

        switch SpeciesGateKt.loadSpeciesGate(metadataJson: metadataJson, model: model) {
        case let loaded as SpeciesGateLoadLoaded:
            logger.info("Species model v\(version) loaded")
            return loaded.gate
        case let failed as SpeciesGateLoadFailed:
            logger.error("traits-v\(version).json refused: \(failed.reason)")
            return nil
        default:
            return nil
        }
    }

    /// The largest N with a `traits-vN.json` in the bundle.
    static func highestModelVersion(in bundle: Bundle) -> Int? {
        let names = (bundle.urls(forResourcesWithExtension: "json", subdirectory: nil) ?? []).map(\.lastPathComponent)
        return highestModelVersion(amongFileNames: names)
    }

    static func highestModelVersion(amongFileNames names: [String]) -> Int? {
        names.compactMap { name -> Int? in
            guard name.hasPrefix("traits-v"), name.hasSuffix(".json") else { return nil }
            return Int(name.dropFirst("traits-v".count).dropLast(".json".count))
        }.max()
    }
}
