import CoreGraphics

/// Where the user should place the sample: a rectangle centred on the preview.
///
/// Mirrors the Android app's `TargetFrame`.
struct TargetFrame {
    /// Frame width as a fraction of the preview width.
    let widthFraction: CGFloat
    /// Frame width divided by frame height. Values below 1 give a tall frame, which suits
    /// long sorghum leaves and whole plants.
    let aspectRatio: CGFloat

    init(widthFraction: CGFloat = 0.8, aspectRatio: CGFloat = 0.5) {
        precondition(widthFraction > 0 && widthFraction <= 1,
                     "widthFraction must be in (0, 1], was \(widthFraction)")
        precondition(aspectRatio > 0, "aspectRatio must be positive, was \(aspectRatio)")
        self.widthFraction = widthFraction
        self.aspectRatio = aspectRatio
    }

    /// Returns the frame's rectangle inside an area of the given size. If the requested frame
    /// would be taller than the area, it is shrunk so it fits while keeping its aspect ratio.
    func rect(in area: CGSize) -> CGRect {
        precondition(area.width > 0 && area.height > 0, "Area must have positive size, was \(area)")
        let requestedWidth = area.width * widthFraction
        let requestedHeight = requestedWidth / aspectRatio
        let shrinkToFit = min(1, area.height / requestedHeight)

        let width = requestedWidth * shrinkToFit
        let height = requestedHeight * shrinkToFit
        return CGRect(x: (area.width - width) / 2, y: (area.height - height) / 2, width: width, height: height)
    }
}
