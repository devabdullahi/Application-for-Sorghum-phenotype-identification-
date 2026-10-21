import Shared
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
            case .levelSensorUnavailable:
                messageText("This device has no motion sensor, so the level guide cannot work.")
            case let .guiding(guidance, coverage):
                livePreview(guidance: guidance, coverage: coverage)
            case .checkingPhoto:
                livePreview(guidance: nil, coverage: nil, overrideMessage: "Checking photo…")
            case let .photoAccepted(photo):
                acceptedView(photo)
            case let .photoRejected(reason):
                messageWithButton(rejectionMessage(reason), buttonLabel: "Try again")
            case .captureFailed:
                messageWithButton("The photo could not be taken. Please try again.", buttonLabel: "Try again")
            }
        }
        .task { await model.startCamera() }
        .onDisappear { model.stopCamera() }
    }

    private func livePreview(guidance: GuidanceState?, coverage: SampleCoverage?, overrideMessage: String? = nil) -> some View {
        ZStack {
            CameraPreview(camera: model.camera, targetFrame: model.targetFrame)
                .ignoresSafeArea()

            // Same full-screen area as the preview, so the drawn frame matches the analysed one.
            GeometryReader { geometry in
                let frameRect = model.targetFrame.rect(in: geometry.size)
                RoundedRectangle(cornerRadius: 12)
                    .stroke(frameColor(for: guidance), lineWidth: 4)
                    .frame(width: frameRect.width, height: frameRect.height)
                    .position(x: frameRect.midX, y: frameRect.midY)
            }
            .ignoresSafeArea()

            VStack {
                Spacer()
                statusPanel(message: overrideMessage ?? guidanceMessage(guidance), coverage: coverage)
            }
            .padding()
        }
    }

    private func statusPanel(message: String, coverage: SampleCoverage?) -> some View {
        VStack(spacing: 4) {
            Text(message)
                .font(.headline)
            if let coverage {
                Text("Green: \(coverage.greenFraction, format: wholePercent) · Confidence: \(coverage.greenConfidence, format: wholePercent)")
                    .font(.subheadline)
                    .monospacedDigit()
            }
        }
        .foregroundStyle(.white)
        .padding()
        .frame(maxWidth: .infinity)
        .background(.black.opacity(0.6), in: RoundedRectangle(cornerRadius: 12))
    }

    private func acceptedView(_ photo: UIImage) -> some View {
        VStack(spacing: 16) {
            Text("Photo accepted")
                .font(.headline)
                .foregroundStyle(.white)
            Image(uiImage: photo)
                .resizable()
                .scaledToFit()
                .accessibilityLabel("Photo accepted")
            Button("Retake") { model.retake() }
                .buttonStyle(.borderedProminent)
        }
        .padding()
    }

    private var wholePercent: FloatingPointFormatStyle<Float>.Percent {
        .percent.precision(.fractionLength(0))
    }

    /// Green once the user is aligned, orange when the sample is cut off, white otherwise.
    private func frameColor(for guidance: GuidanceState?) -> Color {
        switch guidance {
        case .holdSteady, .ready: .green
        case .sampleCutOff: .orange
        default: .white
        }
    }

    /// The phone is held flat above the board, so "lower the top edge" is clearer than
    /// "tilt forward", which depends on how the user is standing. Same wording as Android.
    private func guidanceMessage(_ guidance: GuidanceState?) -> String {
        switch guidance {
        case .tiltTopDown: "Lower the top edge of the phone"
        case .tiltBottomDown: "Lower the bottom edge of the phone"
        case .tiltLeftDown: "Lower the left edge of the phone"
        case .tiltRightDown: "Lower the right edge of the phone"
        case .noSample: "Place the sample inside the frame"
        case .sampleCutOff: "Sample is cut off. Move the phone farther away"
        case .holdSteady: "Hold steady…"
        case .ready: "Capturing…"
        default: "Starting camera…"
        }
    }

    private func rejectionMessage(_ reason: RejectionReason) -> String {
        switch reason {
        case .noSample: "No sample found in the photo. Place the sample inside the frame and try again."
        case .tooDark: "Photo is too dark. Add more light and try again."
        case .glare: "Too much glare. Move the light or angle it away from the sample and try again."
        case .blurry: "Photo is blurry. Hold the phone still and try again."
        default: "The photo could not be checked. Please try again."
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

    private func messageWithButton(_ message: String, buttonLabel: String) -> some View {
        VStack(spacing: 16) {
            messageText(message)
            Button(buttonLabel) { model.retake() }
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
