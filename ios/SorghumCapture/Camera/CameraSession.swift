import AVFoundation
import Shared
import os

enum CameraStartError: Error {
    case permissionDenied
    case cameraUnavailable
}

/// Runs the back camera and measures how much green sample is inside the target frame of each
/// live video frame.
///
/// Frames are analysed on `analysisQueue`; results are delivered to `onCoverageMeasured` on the
/// main thread so all UI state is only touched from one thread.
///
/// The measurement itself is the shared core's (`measureLiveFrame`); this class only turns
/// camera buffers into `PixelImage`s.
///
/// `@unchecked Sendable`: the session is configured and started only on `sessionQueue`, the
/// analysis region is guarded by a lock, and `onCoverageMeasured` is set once before `start()`.
final class CameraSession: NSObject, @unchecked Sendable {
    let captureSession = AVCaptureSession()

    /// Called on the main thread with the coverage of each analysed frame.
    var onCoverageMeasured: ((SampleCoverage) -> Void)?

    /// Pure shared function, safe to call on `analysisQueue`.
    private let measureLiveFrame: @Sendable (PixelImage) -> SampleCoverage
    private let videoOutput = AVCaptureVideoDataOutput()
    private let sessionQueue = DispatchQueue(label: "com.sorghum.capture.session")
    private let analysisQueue = DispatchQueue(label: "com.sorghum.capture.analysis")
    /// Set on `sessionQueue` during configuration, before `start()` returns.
    private var videoDevice: AVCaptureDevice?

    /// The target frame in the video frames' own coordinates, as fractions of their size
    /// (AVFoundation's "metadata output" coordinates). Written by the preview on the main thread
    /// whenever its layout changes, read on `analysisQueue`. Nil until the preview has laid out.
    private let analysisRegion = OSAllocatedUnfairLock<CGRect?>(initialState: nil)

    init(measureLiveFrame: @escaping @Sendable (PixelImage) -> SampleCoverage) {
        self.measureLiveFrame = measureLiveFrame
        super.init()
    }

    func updateAnalysisRegion(_ region: CGRect) {
        analysisRegion.withLock { $0 = region }
    }

    /// Asks for camera permission if needed, then configures and starts the session.
    func start() async throws {
        guard await AVCaptureDevice.requestAccess(for: .video) else {
            throw CameraStartError.permissionDenied
        }
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            sessionQueue.async {
                do {
                    try self.configureSession()
                    // startRunning blocks until the camera is up, so it stays off the main thread.
                    self.captureSession.startRunning()
                    continuation.resume()
                } catch {
                    continuation.resume(throwing: error)
                }
            }
        }
    }

    /// The camera's current zoom, 1 meaning no zoom.
    var zoomFactor: CGFloat {
        videoDevice?.videoZoomFactor ?? 1
    }

    /// Zooms the camera, clamped to what the camera supports and to `maxZoomFactor`.
    /// The preview and the analysed frames both show the zoomed image, so the green check
    /// keeps matching what the user sees inside the frame.
    func setZoomFactor(_ requestedFactor: CGFloat) {
        sessionQueue.async {
            guard let device = self.videoDevice else { return }
            let maxFactor = min(device.maxAvailableVideoZoomFactor, Self.maxZoomFactor)
            let factor = min(max(requestedFactor, device.minAvailableVideoZoomFactor), maxFactor)
            do {
                try device.lockForConfiguration()
                device.videoZoomFactor = factor
                device.unlockForConfiguration()
            } catch {
                // Another app holds the camera configuration; skipping one zoom step is harmless
                // because the next pinch update tries again.
            }
        }
    }

    /// Beyond this the zoom is purely digital on most iPhones and the image gets too soft for
    /// a reliable photo.
    private static let maxZoomFactor: CGFloat = 5

    func stop() {
        sessionQueue.async { self.captureSession.stopRunning() }
    }

    private func configureSession() throws {
        guard captureSession.inputs.isEmpty else { return }

        guard let camera = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back),
              let input = try? AVCaptureDeviceInput(device: camera),
              captureSession.canAddInput(input),
              captureSession.canAddOutput(videoOutput)
        else {
            throw CameraStartError.cameraUnavailable
        }

        captureSession.beginConfiguration()
        captureSession.sessionPreset = .high
        captureSession.addInput(input)
        videoDevice = camera

        // BGRA lets the analyser read colour channels directly, with no YUV conversion.
        videoOutput.videoSettings = [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA]
        // Drop frames when analysis falls behind, so guidance reflects the latest frame.
        videoOutput.alwaysDiscardsLateVideoFrames = true
        videoOutput.setSampleBufferDelegate(self, queue: analysisQueue)
        captureSession.addOutput(videoOutput)
        captureSession.commitConfiguration()
    }
}

extension CameraSession: AVCaptureVideoDataOutputSampleBufferDelegate {
    func captureOutput(_ output: AVCaptureOutput,
                       didOutput sampleBuffer: CMSampleBuffer,
                       from connection: AVCaptureConnection) {
        guard let region = analysisRegion.withLock({ $0 }),
              let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer),
              let frame = uprightPixelImage(
                  of: pixelBuffer,
                  in: region,
                  maxLongSide: Int(GreenCoverageKt.LIVE_ANALYSIS_LONG_SIDE_PIXELS)
              )
        else { return }

        let coverage = measureLiveFrame(frame)
        DispatchQueue.main.async { self.onCoverageMeasured?(coverage) }
    }
}
