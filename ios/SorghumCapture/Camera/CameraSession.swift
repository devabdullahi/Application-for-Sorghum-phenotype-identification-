import AVFoundation
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
/// `@unchecked Sendable`: the session is configured and started only on `sessionQueue`, the
/// analysis region is guarded by a lock, and `onCoverageMeasured` is set once before `start()`.
final class CameraSession: NSObject, @unchecked Sendable {
    let captureSession = AVCaptureSession()

    /// Called on the main thread with the coverage of each analysed frame.
    var onCoverageMeasured: ((SampleCoverage) -> Void)?

    private let settings: GreenDetectionSettings
    private let videoOutput = AVCaptureVideoDataOutput()
    private let sessionQueue = DispatchQueue(label: "com.sorghum.capture.session")
    private let analysisQueue = DispatchQueue(label: "com.sorghum.capture.analysis")
    /// Set on `sessionQueue` during configuration, before `start()` returns.
    private var videoDevice: AVCaptureDevice?

    /// The target frame in the video frames' own coordinates, as fractions of their size
    /// (AVFoundation's "metadata output" coordinates). Written by the preview on the main thread
    /// whenever its layout changes, read on `analysisQueue`. Nil until the preview has laid out.
    private let analysisRegion = OSAllocatedUnfairLock<CGRect?>(initialState: nil)

    init(settings: GreenDetectionSettings) {
        self.settings = settings
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
              let regionPixels = readPixels(of: pixelBuffer, in: region, maxLongSide: Self.liveAnalysisLongSidePixels)
        else { return }

        let coverage = measureSampleCoverage(
            pixels: regionPixels.pixels,
            width: regionPixels.width,
            height: regionPixels.height,
            settings: settings
        )
        DispatchQueue.main.async { self.onCoverageMeasured?(coverage) }
    }

    /// Live frames are sampled down to this size before analysis. A rough green count needs very
    /// few pixels, and a small image keeps analysis well under one frame interval.
    /// Same value as the Android app.
    private static let liveAnalysisLongSidePixels = 160
}

private struct RegionPixels {
    let pixels: [RGBPixel]
    let width: Int
    let height: Int
}

/// Reads the pixels of a BGRA buffer inside `region` (fractions of the buffer size), taking
/// every n-th pixel so the result's longer side is at most `maxLongSide`.
///
/// The region is not rotated to upright. That does not matter here: green coverage and the edge
/// band are the same whichever way the region is turned.
private func readPixels(of pixelBuffer: CVPixelBuffer, in region: CGRect, maxLongSide: Int) -> RegionPixels? {
    let bufferWidth = CVPixelBufferGetWidth(pixelBuffer)
    let bufferHeight = CVPixelBufferGetHeight(pixelBuffer)
    let bufferBounds = CGRect(x: 0, y: 0, width: bufferWidth, height: bufferHeight)
    let pixelRegion = CGRect(
        x: region.minX * CGFloat(bufferWidth),
        y: region.minY * CGFloat(bufferHeight),
        width: region.width * CGFloat(bufferWidth),
        height: region.height * CGFloat(bufferHeight)
    ).integral.intersection(bufferBounds)
    guard !pixelRegion.isEmpty else { return nil }

    let longSide = Int(max(pixelRegion.width, pixelRegion.height))
    let step = max(1, Int((Double(longSide) / Double(maxLongSide)).rounded(.up)))
    let left = Int(pixelRegion.minX)
    let top = Int(pixelRegion.minY)
    let width = Int(pixelRegion.width) / step
    let height = Int(pixelRegion.height) / step
    guard width > 0, height > 0 else { return nil }

    CVPixelBufferLockBaseAddress(pixelBuffer, .readOnly)
    defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, .readOnly) }
    guard let baseAddress = CVPixelBufferGetBaseAddress(pixelBuffer) else { return nil }
    let bytesPerRow = CVPixelBufferGetBytesPerRow(pixelBuffer)
    let bytes = baseAddress.assumingMemoryBound(to: UInt8.self)

    var pixels: [RGBPixel] = []
    pixels.reserveCapacity(width * height)
    for row in 0..<height {
        let rowStart = (top + row * step) * bytesPerRow
        for column in 0..<width {
            // BGRA byte order.
            let offset = rowStart + (left + column * step) * 4
            pixels.append(RGBPixel(red: bytes[offset + 2], green: bytes[offset + 1], blue: bytes[offset]))
        }
    }
    return RegionPixels(pixels: pixels, width: width, height: height)
}
