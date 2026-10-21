import Shared

/// What the green check says about the sample inside the target frame.
enum SampleStatus: Equatable {
    case noSample
    case cutOff
    case inFrame

    var message: String {
        switch self {
        case .noSample: "Place the sample inside the frame"
        case .cutOff: "Sample is cut off. Move the phone farther away"
        case .inFrame: "Sample is inside the frame"
        }
    }
}

/// Thresholds for turning coverage into a status. Defaults match the Android app's
/// `GuidanceSettings`; tune them on real devices.
struct SampleStatusSettings {
    /// Fraction of the frame that must be green before a sample counts as present.
    /// Small, so thin leaves still count.
    let minSampleFraction: Float
    /// Fraction of the frame's edge band that may be green. Above this, the sample crosses
    /// the frame edge and is cut off.
    let maxEdgeGreenFraction: Float

    init(minSampleFraction: Float = 0.02, maxEdgeGreenFraction: Float = 0.05) {
        precondition((0...1).contains(minSampleFraction),
                     "minSampleFraction must be within 0...1, was \(minSampleFraction)")
        precondition((0...1).contains(maxEdgeGreenFraction),
                     "maxEdgeGreenFraction must be within 0...1, was \(maxEdgeGreenFraction)")
        self.minSampleFraction = minSampleFraction
        self.maxEdgeGreenFraction = maxEdgeGreenFraction
    }
}

func sampleStatus(for coverage: SampleCoverage, settings: SampleStatusSettings) -> SampleStatus {
    if coverage.greenFraction < settings.minSampleFraction { return .noSample }
    if coverage.edgeGreenFraction > settings.maxEdgeGreenFraction { return .cutOff }
    return .inFrame
}
