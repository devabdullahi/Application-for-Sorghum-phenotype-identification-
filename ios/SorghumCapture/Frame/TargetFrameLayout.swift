import CoreGraphics
import Shared

extension TargetFrame {
    /// The shared target frame laid out in an on-screen area, in points. The frame's geometry
    /// (size, aspect ratio, shrink-to-fit) is decided in the shared core; this only scales its
    /// fractions to the view. Points are rounded to whole numbers first, as on Android.
    func rect(in area: CGSize) -> CGRect {
        let fractions = normalizedRectIn(areaWidth: Int32(area.width.rounded()), areaHeight: Int32(area.height.rounded()))
        return CGRect(
            x: CGFloat(fractions.left) * area.width,
            y: CGFloat(fractions.top) * area.height,
            width: CGFloat(fractions.right - fractions.left) * area.width,
            height: CGFloat(fractions.bottom - fractions.top) * area.height
        )
    }
}
