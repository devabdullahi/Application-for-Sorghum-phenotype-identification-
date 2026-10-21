import Observation
import Shared

/// What the capture screen shows.
enum CaptureScreenState: Equatable {
    case starting
    case permissionDenied
    case cameraUnavailable
    case analyzing(SampleStatus, SampleCoverage)
}

/// Owns the camera session and turns its measurements into screen state.
@MainActor
@Observable
final class CaptureModel {
    private(set) var state: CaptureScreenState = .starting

    let camera: CameraSession
    let targetFrame: TargetFrame
    /// The shared capture rules. Its settings are the single source of every threshold.
    private let flow = CaptureFlow()
    private let statusSettings: SampleStatusSettings

    init(statusSettings: SampleStatusSettings = SampleStatusSettings()) {
        self.statusSettings = statusSettings
        targetFrame = flow.settings.targetFrame
        // measureLiveFrame is pure and documented as safe on any thread.
        camera = CameraSession(measureLiveFrame: { [flow] frame in flow.measureLiveFrame(image: frame) })
        camera.onCoverageMeasured = { [weak self] coverage in
            self?.showCoverage(coverage)
        }
    }

    func startCamera() async {
        state = .starting
        do {
            try await camera.start()
        } catch CameraStartError.permissionDenied {
            state = .permissionDenied
        } catch {
            state = .cameraUnavailable
        }
    }

    func stopCamera() {
        camera.stop()
    }

    private func showCoverage(_ coverage: SampleCoverage) {
        state = .analyzing(sampleStatus(for: coverage, settings: statusSettings), coverage)
    }
}
