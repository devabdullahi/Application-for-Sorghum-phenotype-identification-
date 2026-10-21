import SwiftUI

struct CaptureScreen: View {
    @State private var model = CaptureModel()
    @Environment(\.openURL) private var openURL

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()

            switch model.state {
            case .permissionDenied:
                permissionMessage
            case .cameraUnavailable:
                messageText("The camera could not be started. Close other camera apps and try again.")
            case .starting, .analyzing:
                livePreview
            }
        }
        .task { await model.startCamera() }
        .onDisappear { model.stopCamera() }
    }

    private var livePreview: some View {
        ZStack {
            CameraPreview(camera: model.camera, targetFrame: model.targetFrame)
                .ignoresSafeArea()

            // Same full-screen area as the preview, so the drawn frame matches the analysed one.
            GeometryReader { geometry in
                let frameRect = model.targetFrame.rect(in: geometry.size)
                RoundedRectangle(cornerRadius: 12)
                    .stroke(frameColor, lineWidth: 4)
                    .frame(width: frameRect.width, height: frameRect.height)
                    .position(x: frameRect.midX, y: frameRect.midY)
            }
            .ignoresSafeArea()

            VStack {
                Spacer()
                statusPanel
            }
            .padding()
        }
    }

    private var statusPanel: some View {
        VStack(spacing: 4) {
            switch model.state {
            case let .analyzing(status, coverage):
                Text(status.message)
                    .font(.headline)
                Text("Green: \(coverage.greenFraction, format: wholePercent) · Confidence: \(coverage.greenConfidence, format: wholePercent)")
                    .font(.subheadline)
                    .monospacedDigit()
            default:
                Text("Starting camera…")
                    .font(.headline)
            }
        }
        .foregroundStyle(.white)
        .padding()
        .frame(maxWidth: .infinity)
        .background(.black.opacity(0.6), in: RoundedRectangle(cornerRadius: 12))
    }

    private var wholePercent: FloatingPointFormatStyle<Float>.Percent {
        .percent.precision(.fractionLength(0))
    }

    private var frameColor: Color {
        guard case let .analyzing(status, _) = model.state else { return .white }
        switch status {
        case .noSample: return .white
        case .cutOff: return .orange
        case .inFrame: return .green
        }
    }

    private var permissionMessage: some View {
        VStack(spacing: 16) {
            messageText("Camera permission is needed to photograph samples.")
            Button("Open Settings") {
                if let settingsURL = URL(string: UIApplication.openSettingsURLString) {
                    openURL(settingsURL)
                }
            }
            .buttonStyle(.borderedProminent)
        }
    }

    private func messageText(_ message: String) -> some View {
        Text(message)
            .foregroundStyle(.white)
            .multilineTextAlignment(.center)
            .padding()
    }
}
