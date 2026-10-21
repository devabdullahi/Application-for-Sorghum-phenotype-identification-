import AVFoundation
import Shared
import SwiftUI

/// Shows the live camera feed full-screen and tells the camera session where the target frame
/// falls inside the video frames.
struct CameraPreview: UIViewRepresentable {
    let camera: CameraSession
    let targetFrame: TargetFrame

    func makeUIView(context: Context) -> PreviewView {
        let view = PreviewView()
        view.previewLayer.session = camera.captureSession
        view.previewLayer.videoGravity = .resizeAspectFill
        view.targetFrame = targetFrame
        view.onAnalysisRegionChanged = { [camera] region in camera.updateAnalysisRegion(region) }
        view.addGestureRecognizer(UIPinchGestureRecognizer(
            target: context.coordinator,
            action: #selector(PinchToZoom.pinchChanged(_:))
        ))
        return view
    }

    func makeCoordinator() -> PinchToZoom {
        PinchToZoom(camera: camera)
    }

    func updateUIView(_ view: PreviewView, context: Context) {
        view.targetFrame = targetFrame
    }
}

/// Pinch to zoom, like the system Camera app: the zoom scales with the pinch, starting from
/// whatever zoom the camera had when the pinch began.
final class PinchToZoom: NSObject {
    private let camera: CameraSession
    private var zoomFactorAtPinchStart: CGFloat = 1

    init(camera: CameraSession) {
        self.camera = camera
    }

    @objc func pinchChanged(_ pinch: UIPinchGestureRecognizer) {
        switch pinch.state {
        case .began:
            zoomFactorAtPinchStart = camera.zoomFactor
        case .changed:
            camera.setZoomFactor(zoomFactorAtPinchStart * pinch.scale)
        default:
            break
        }
    }
}

final class PreviewView: UIView {
    /// Set by `CameraPreview` right after creation; nil only before that.
    var targetFrame: TargetFrame?
    var onAnalysisRegionChanged: ((CGRect) -> Void)?

    override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }

    var previewLayer: AVCaptureVideoPreviewLayer {
        // Safe: layerClass guarantees the layer type.
        layer as! AVCaptureVideoPreviewLayer
    }

    override init(frame: CGRect) {
        super.init(frame: frame)
        // The layer can only convert coordinates once it knows the camera's format, which may be
        // after the first layout, so convert again when the session starts.
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(sessionDidStartRunning),
            name: AVCaptureSession.didStartRunningNotification,
            object: nil
        )
    }

    required init?(coder: NSCoder) {
        fatalError("PreviewView is only created in code")
    }

    override func layoutSubviews() {
        super.layoutSubviews()
        reportAnalysisRegion()
    }

    @objc private func sessionDidStartRunning() {
        DispatchQueue.main.async { self.reportAnalysisRegion() }
    }

    /// Converts the on-screen target frame into the video frames' coordinates. The preview layer
    /// does this conversion itself, accounting for aspect-fill cropping and the sensor's
    /// landscape orientation, so live analysis looks at exactly what the user sees in the frame.
    private func reportAnalysisRegion() {
        guard let targetFrame, bounds.width > 0, bounds.height > 0 else { return }
        let frameOnScreen = targetFrame.rect(in: bounds.size)
        let region = previewLayer.metadataOutputRectConverted(fromLayerRect: frameOnScreen)
        guard !region.isEmpty, !region.isNull else { return }
        onAnalysisRegionChanged?(region)
    }
}
