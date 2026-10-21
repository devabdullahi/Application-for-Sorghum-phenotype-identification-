import Observation

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
    private let statusSettings: SampleStatusSettings

    init(
        targetFrame: TargetFrame = TargetFrame(),
        detectionSettings: GreenDetectionSettings = GreenDetectionSettings(),
        statusSettings: SampleStatusSettings = SampleStatusSettings()
    ) {
        self.targetFrame = targetFrame
        self.statusSettings = statusSettings
        camera = CameraSession(settings: detectionSettings)
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
