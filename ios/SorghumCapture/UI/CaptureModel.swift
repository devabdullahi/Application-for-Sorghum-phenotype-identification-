import CoreImage
import Observation
import Shared
import UIKit

/// What the capture screen shows.
enum CaptureScreenState {
    case permissionDenied
    case cameraUnavailable
    case levelSensorUnavailable
    /// Live guidance. `guidance` is nil until the first tilt and frame readings arrive;
    /// `coverage` is the latest live measurement, shown as a readout.
    case guiding(guidance: GuidanceState?, coverage: SampleCoverage?)
    case checkingPhoto
    /// Passed the quality check; `species` says whether it shows sorghum, or that no model is installed.
    case photoAccepted(UIImage, species: SpeciesCheck)
    case photoRejected(RejectionReason)
    case captureFailed
}

/// iOS adapter for the shared `CaptureFlow`: forwards camera and motion events to it, takes the
/// photo when it says READY, and maps its state to screen state. The capture rules (guidance
/// order, steady hold, quality thresholds) all live in `shared/session`.
@MainActor
@Observable
final class CaptureModel {
    private(set) var state: CaptureScreenState = .guiding(guidance: nil, coverage: nil)

    let camera: CameraSession
    let targetFrame: TargetFrame
    /// The shared capture rules. Its settings are the single source of every threshold.
    /// No species model is bundled yet, so the flow reports the species check as unavailable
    /// and the screen says so; the LiteRT runner arrives with the first trained model.
    private let flow = CaptureFlow()
    private let tiltSensor = TiltSensor()
    private var latestCoverage: SampleCoverage?
    /// Kept here because the shared flow never holds platform images.
    private var acceptedPhoto: UIImage?
    private var isPermissionDenied = false

    init() {
        targetFrame = flow.settings.targetFrame
        // measureLiveFrame is pure and documented as safe on any thread.
        camera = CameraSession(measureLiveFrame: { [flow] frame in flow.measureLiveFrame(image: frame) })
        camera.onCoverageMeasured = { [weak self] coverage in
            self?.onCoverageMeasured(coverage)
        }
    }

    func startCamera() async {
        guard tiltSensor.isAvailable else {
            flow.onLevelSensorUnavailable()
            publishState()
            return
        }
        do {
            try await camera.start()
        } catch CameraStartError.permissionDenied {
            isPermissionDenied = true
            publishState()
            return
        } catch {
            flow.onCameraUnavailable()
            publishState()
            return
        }
        tiltSensor.start { [weak self] tilt, timestampMillis in
            self?.onTiltChanged(tilt, timestampMillis: timestampMillis)
        }
    }

    func stopCamera() {
        tiltSensor.stop()
        camera.stop()
    }

    /// Returns to live guidance, starting the steady hold from scratch.
    func retake() {
        acceptedPhoto = nil
        latestCoverage = nil
        flow.retake()
        publishState()
    }

    private func onTiltChanged(_ tilt: DeviceTilt, timestampMillis: Int64) {
        flow.onTiltChanged(tilt: tilt, timestampMillis: timestampMillis)
        publishState()
        captureIfReady()
    }

    private func onCoverageMeasured(_ coverage: SampleCoverage) {
        latestCoverage = coverage
        flow.onSampleCoverageMeasured(coverage: coverage, timestampMillis: monotonicMillis())
        publishState()
        captureIfReady()
    }

    private func captureIfReady() {
        guard let guiding = flow.state as? CaptureStateGuiding, guiding.guidance == .ready else { return }
        guard flow.startCapture() else { return }
        publishState()
        Task { await captureAndCheckPhoto() }
    }

    private func captureAndCheckPhoto() async {
        let photo: CVPixelBuffer
        do {
            photo = try await camera.takePhoto()
        } catch {
            flow.onCaptureFailed()
            publishState()
            return
        }
        guard let region = camera.currentAnalysisRegion else {
            flow.onCaptureFailed()
            publishState()
            return
        }

        // Scaling and checking a full-resolution photo takes a moment; keep it off the main thread.
        let flow = self.flow
        let outcome = await Task.detached(priority: .userInitiated) { () -> PhotoCheckOutcome in
            let maxLongSide = Int(PhotoQualityKt.QUALITY_CHECK_LONG_SIDE_PIXELS)
            guard let analysisCopy = uprightPixelImage(of: photo, in: region, maxLongSide: maxLongSide) else {
                return .unreadable
            }
            if let rejection = flow.checkPhoto(image: analysisCopy) {
                return .rejected(rejection)
            }
            let species = flow.checkSpecies(image: analysisCopy)
            guard let displayImage = uprightImage(of: photo, in: region) else { return .unreadable }
            return .accepted(displayImage, species)
        }.value

        switch outcome {
        case .unreadable:
            flow.onCaptureFailed()
        case let .rejected(reason):
            flow.onPhotoChecked(rejection: reason, species: SpeciesCheckUnavailable.shared)
        case let .accepted(displayImage, species):
            acceptedPhoto = displayImage
            flow.onPhotoChecked(rejection: nil, species: species)
        }
        publishState()
    }

    private func publishState() {
        if isPermissionDenied {
            state = .permissionDenied
            return
        }
        switch flow.state {
        case let guiding as CaptureStateGuiding:
            state = .guiding(guidance: guiding.guidance, coverage: latestCoverage)
        case is CaptureStateCheckingPhoto:
            state = .checkingPhoto
        case let accepted as CaptureStatePhotoAccepted:
            // acceptedPhoto is always set before the flow is told the photo passed.
            state = acceptedPhoto.map { .photoAccepted($0, species: accepted.species) } ?? .captureFailed
        case let rejected as CaptureStatePhotoRejected:
            state = .photoRejected(rejected.reason)
        case is CaptureStateCameraUnavailable:
            state = .cameraUnavailable
        case is CaptureStateLevelSensorUnavailable:
            state = .levelSensorUnavailable
        default:
            state = .captureFailed
        }
    }
}

/// Result of the background photo check. The verdict is the shared check's; `unreadable` means
/// the photo's pixels could not be read at all, which is a capture failure, not a verdict.
private enum PhotoCheckOutcome: @unchecked Sendable {
    case unreadable
    case rejected(RejectionReason)
    case accepted(UIImage, SpeciesCheck)
}

/// The photo cropped to the target frame and turned upright, for showing to the user.
/// Display only: the quality check uses the `PixelImage` from `uprightPixelImage`.
private func uprightImage(of pixelBuffer: CVPixelBuffer, in region: CGRect) -> UIImage? {
    let photo = CIImage(cvPixelBuffer: pixelBuffer)
    let extent = photo.extent
    // Core Image's origin is bottom-left; the region's is top-left.
    let crop = CGRect(
        x: region.minX * extent.width,
        y: (1 - region.maxY) * extent.height,
        width: region.width * extent.width,
        height: region.height * extent.height
    )
    let upright = photo.cropped(to: crop).oriented(.right)
    guard let cgImage = CIContext().createCGImage(upright, from: upright.extent) else { return nil }
    return UIImage(cgImage: cgImage)
}
