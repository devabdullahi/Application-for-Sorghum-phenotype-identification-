package com.sorghum.calibration

/**
 * The reference card: Calibrite (formerly X-Rite) ColorChecker Classic Mini, 24 patches in a
 * 4 x 6 grid, chosen in ADR-0008. The Mini carries the same patches as the full-size Classic
 * at 1/8 of the area, small enough to sit on the photo board beside the sample.
 *
 * Patch order is the card's own: row by row from the top-left "dark skin" patch, with the card
 * held landscape so the neutral row (white to black) is at the bottom.
 */
object ColorCheckerClassicMini {
    const val ROWS = 4
    const val COLUMNS = 6
    const val PATCH_COUNT = ROWS * COLUMNS

    /**
     * Centre-to-centre distance between neighbouring patches, in mm. X-Rite lists the Mini's
     * colour chip area as 57 x 86 mm (2.25 x 3.375 in) for 4 x 6 patches: 57 / 4 = 14.25 and
     * 86 / 6 = 14.33, so the pitch is about 14.3 mm both ways.
     *
     * ASSUMPTION — confirm: derived from the published chip area, not measured. Measure the
     * pitch of the team's physical cards (ruler across 6 patches) before trusting mm traits
     * such as seed size; an error here scales every length the app reports.
     */
    const val PATCH_PITCH_MM = 14.3f

    /** Patch names in card order, as X-Rite names them. */
    val PATCH_NAMES: List<String> = listOf(
        "dark skin", "light skin", "blue sky", "foliage", "blue flower", "bluish green",
        "orange", "purplish blue", "moderate red", "purple", "yellow green", "orange yellow",
        "blue", "green", "red", "yellow", "magenta", "cyan",
        "white 9.5", "neutral 8", "neutral 6.5", "neutral 5", "neutral 3.5", "black 2",
    )

    /**
     * Reference L*a*b* (D50, 2° observer) of each patch for cards made after November 2014,
     * when X-Rite changed the pigments. Source: X-Rite (2016), "New color specifications for
     * ColorChecker SG and Classic Charts", as tabulated by the colour-science package
     * (`DATA_COLORCHECKER24_AFTER_NOV2014_CIE_LAB`). Older cards differ by up to a few ΔE.
     */
    val referenceLabD50: List<LabColour> = listOf(
        LabColour(37.54, 14.37, 14.92),
        LabColour(64.66, 19.27, 17.5),
        LabColour(49.32, -3.82, -22.54),
        LabColour(43.46, -12.74, 22.72),
        LabColour(54.94, 9.61, -24.79),
        LabColour(70.48, -32.26, -0.37),
        LabColour(62.73, 35.83, 56.5),
        LabColour(39.43, 10.75, -45.17),
        LabColour(50.57, 48.64, 16.67),
        LabColour(30.1, 22.54, -20.87),
        LabColour(71.77, -24.13, 58.19),
        LabColour(71.51, 18.24, 67.37),
        LabColour(28.37, 15.42, -49.8),
        LabColour(54.38, -39.72, 32.27),
        LabColour(42.43, 51.05, 28.62),
        LabColour(81.8, 2.67, 80.41),
        LabColour(50.63, 51.28, -14.12),
        LabColour(49.57, -29.71, -28.32),
        LabColour(95.19, -1.03, 2.93),
        LabColour(81.29, -0.57, 0.44),
        LabColour(66.89, -0.75, -0.06),
        LabColour(50.76, -0.13, 0.14),
        LabColour(35.63, -0.46, -0.48),
        LabColour(20.64, 0.07, -0.46),
    )

    /**
     * [referenceLabD50] in linear sRGB (D65, Bradford-adapted): the targets of the colour fit.
     * Computed rather than typed in so the Lab table stays the single source. Cyan sits just
     * outside the sRGB gamut, so one channel is slightly negative.
     */
    val referenceLinearRgb: List<LinearRgb> = referenceLabD50.map(::labD50ToLinearRgb)
}
