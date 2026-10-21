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
            case let .photoAccepted(photo, species):
                acceptedView(photo, species: species)
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

            VStack(spacing: 16) {
                Spacer()
                statusPanel(message: overrideMessage ?? guidanceMessage(guidance), coverage: coverage)
                shutterButton(isEnabled: overrideMessage == nil)
            }
            .padding()
        }
    }

    /// Takes the photo by hand. Guidance still captures on its own when everything is aligned.
    private func shutterButton(isEnabled: Bool) -> some View {
        Button {
            model.captureNow()
        } label: {
            Circle()
                .strokeBorder(.white, lineWidth: 4)
                .background(Circle().fill(.white.opacity(isEnabled ? 0.9 : 0.3)).padding(6))
                .frame(width: 72, height: 72)
        }
        .disabled(!isEnabled)
        .accessibilityLabel("Take photo")
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

    private func acceptedView(_ photo: UIImage, species: SpeciesCheck) -> some View {
        let verdict = speciesVerdict(species)
        return VStack(spacing: 16) {
            Text(verdict.title)
                .font(.headline)
                .foregroundStyle(verdict.color)
            Text(verdict.detail)
                .font(.subheadline)
                .foregroundStyle(.white)
                .multilineTextAlignment(.center)
            Image(uiImage: photo)
                .resizable()
                .scaledToFit()
                .accessibilityLabel(verdict.title)
            Button("Retake") { model.retake() }
                .buttonStyle(.borderedProminent)
        }
        .padding()
    }

    /// How the species result reads on screen. Only wording: the decision itself was made in
    /// the shared core.
    private func speciesVerdict(_ species: SpeciesCheck) -> (title: String, detail: String, color: Color) {
        switch species {
        case let sorghum as SpeciesCheckSorghum:
            return ("Sorghum", "Photo accepted. Sorghum, \(percent(sorghum.sorghumProbability)) sure.", .green)
        case let notSorghum as SpeciesCheckNotSorghum:
            let detail = notSorghum.lookAlikeClassId.map { "This looks like \(lookAlikeName($0)), not sorghum." }
                ?? "This does not look like sorghum."
            return ("Not sorghum", detail, .orange)
        case is SpeciesCheckNoPlant:
            return ("No plant found", "Place the sample on the board inside the frame and retake.", .orange)
        case is SpeciesCheckUnsure:
            return ("Not sure it is sorghum", "Retake closer, in good light, or photograph another part of the plant.", .yellow)
        default:
            return ("Photo accepted", "Species check not installed yet: this photo was only checked for quality.", .white)
        }
    }

    private func percent(_ probability: Float) -> String {
        probability.formatted(.percent.precision(.fractionLength(0)))
    }

    /// Display names for the model's look-alike class ids (`model/sorghum_model/species_classes.py`).
    private func lookAlikeName(_ classId: String) -> String {
        switch classId {
        case "johnson_grass": "Johnson grass"
        case "maize": "maize"
        case "sugarcane": "sugarcane"
        case "pearl_millet": "pearl millet"
        case "finger_millet": "finger millet"
        default: classId.replacingOccurrences(of: "_", with: " ")
        }
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
