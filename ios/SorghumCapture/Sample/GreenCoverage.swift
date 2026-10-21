/// How much of an image region is covered by green plant tissue.
///
/// - `greenFraction`: fraction of all pixels in the region that are green.
/// - `edgeGreenFraction`: fraction of pixels in the region's edge band that are green.
///   A high value means the sample runs across the region's border, i.e. it is cut off.
/// - `greenConfidence`: how clearly green the green pixels are, 0...1: the mean of each green
///   pixel's confidence (see `greenConfidence(ofExcessGreen:settings:)`). Near 0 means the
///   "green" is barely above the threshold (dull, yellowing or tinted light); near 1 means
///   clearly green leaf. 0 if no pixel is green.
struct SampleCoverage: Equatable {
    let greenFraction: Double
    let edgeGreenFraction: Double
    let greenConfidence: Double
}

/// One pixel's colour channels, 0...255.
struct RGBPixel: Equatable {
    let red: UInt8
    let green: UInt8
    let blue: UInt8
}

/// Thresholds for deciding whether a pixel is green plant tissue.
///
/// Mirrors the Android app's `GreenDetectionSettings` so both apps agree on what counts as plant.
struct GreenDetectionSettings {
    /// Minimum excess-green index (see `isPlantPixel`). 0.1 separates leaves from grey, white,
    /// brown or black boards in typical indoor light; tune if the board is tinted.
    let minExcessGreen: Double
    /// Pixels whose r + g + b is below this are ignored, because in very dark pixels sensor
    /// noise makes the colour ratios meaningless.
    let minBrightnessSum: Int
    /// Width of the edge band, as a fraction of the region's shorter side.
    let edgeBandFraction: Double
    /// Excess-green index at and above which a pixel is certainly green (confidence 1).
    /// Healthy leaves score about 0.5–0.7; dull or yellowing tissue sits near `minExcessGreen`.
    /// Initial guess, tune on real photos.
    let fullConfidenceExcessGreen: Double

    init(
        minExcessGreen: Double = 0.1,
        minBrightnessSum: Int = 60,
        edgeBandFraction: Double = 0.03,
        fullConfidenceExcessGreen: Double = 0.3
    ) {
        precondition((0...765).contains(minBrightnessSum),
                     "minBrightnessSum must be within 0...765, was \(minBrightnessSum)")
        precondition(edgeBandFraction > 0 && edgeBandFraction < 0.5,
                     "edgeBandFraction must be within (0, 0.5), was \(edgeBandFraction)")
        precondition(fullConfidenceExcessGreen > minExcessGreen,
                     "fullConfidenceExcessGreen must be above minExcessGreen (\(minExcessGreen)), was \(fullConfidenceExcessGreen)")
        self.minExcessGreen = minExcessGreen
        self.minBrightnessSum = minBrightnessSum
        self.edgeBandFraction = edgeBandFraction
        self.fullConfidenceExcessGreen = fullConfidenceExcessGreen
    }
}

/// Measures green coverage of an image region given as pixels, row by row.
func measureSampleCoverage(
    pixels: [RGBPixel],
    width: Int,
    height: Int,
    settings: GreenDetectionSettings
) -> SampleCoverage {
    precondition(width > 0 && height > 0, "Region must have positive size, was \(width)x\(height)")
    precondition(pixels.count == width * height,
                 "Expected \(width * height) pixels for \(width)x\(height), got \(pixels.count)")

    // Always at least one pixel wide, so tiny analysis frames still have an edge band.
    let edgeBand = max(1, Int(Double(min(width, height)) * settings.edgeBandFraction))

    var greenPixels = 0
    var edgePixels = 0
    var greenEdgePixels = 0
    var confidenceSum = 0.0
    for y in 0..<height {
        for x in 0..<width {
            let excessGreen = excessGreenIndex(pixels[y * width + x], settings: settings)
            var isGreen = false
            if let excessGreen, excessGreen >= settings.minExcessGreen {
                isGreen = true
                greenPixels += 1
                confidenceSum += greenConfidence(ofExcessGreen: excessGreen, settings: settings)
            }
            let isInEdgeBand = x < edgeBand || x >= width - edgeBand ||
                y < edgeBand || y >= height - edgeBand

            if isInEdgeBand {
                edgePixels += 1
                if isGreen { greenEdgePixels += 1 }
            }
        }
    }

    return SampleCoverage(
        greenFraction: Double(greenPixels) / Double(width * height),
        edgeGreenFraction: Double(greenEdgePixels) / Double(edgePixels),
        greenConfidence: greenPixels == 0 ? 0 : confidenceSum / Double(greenPixels)
    )
}

/// Classifies one pixel with the excess-green index, ExG = 2g − r − b, computed on chromatic
/// coordinates (each channel divided by r + g + b). Dividing by brightness makes the index
/// depend on colour rather than lighting, so shaded and sunlit parts of a leaf score alike.
/// It is a standard, cheap vegetation index in plant phenotyping.
func isPlantPixel(_ pixel: RGBPixel, settings: GreenDetectionSettings) -> Bool {
    guard let excessGreen = excessGreenIndex(pixel, settings: settings) else { return false }
    return excessGreen >= settings.minExcessGreen
}

/// The excess-green index of one pixel, or nil if it is too dark for colour ratios to mean anything.
func excessGreenIndex(_ pixel: RGBPixel, settings: GreenDetectionSettings) -> Double? {
    let red = Int(pixel.red)
    let green = Int(pixel.green)
    let blue = Int(pixel.blue)
    let brightnessSum = red + green + blue
    if brightnessSum < settings.minBrightnessSum { return nil }

    return Double(2 * green - red - blue) / Double(brightnessSum)
}

/// How sure we are that a pixel with this excess-green index is green plant tissue, 0...1.
/// Rises linearly from 0 at the classification threshold to 1 at
/// `settings.fullConfidenceExcessGreen`, so pixels that only just pass the threshold count as
/// uncertain rather than as fully green.
func greenConfidence(ofExcessGreen excessGreen: Double, settings: GreenDetectionSettings) -> Double {
    let range = settings.fullConfidenceExcessGreen - settings.minExcessGreen
    return min(max((excessGreen - settings.minExcessGreen) / range, 0), 1)
}
