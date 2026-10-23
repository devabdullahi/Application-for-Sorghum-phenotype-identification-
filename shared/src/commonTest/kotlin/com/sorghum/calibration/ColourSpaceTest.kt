package com.sorghum.calibration

import kotlin.math.abs
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class ColourSpaceTest {

    @Test
    fun `sRGB decoding matches IEC 61966-2-1 at known points`() {
        assertEquals(0.0, srgbToLinear(0.0), 1e-12)
        assertEquals(1.0, srgbToLinear(1.0), 1e-12)
        // 0.5 encoded is ((0.5 + 0.055) / 1.055)^2.4.
        assertEquals(0.214041, srgbToLinear(0.5), 1e-6)
        // Below the 0.04045 knee the curve is a straight line with slope 1 / 12.92.
        assertEquals(0.04 / 12.92, srgbToLinear(0.04), 1e-12)
    }

    @Test
    fun `sRGB encoding inverts decoding`() {
        for (encoded in listOf(0.0, 0.01, 0.04045, 0.2, 0.5, 0.8, 1.0)) {
            // 1e-7: the standard's two knee constants (0.04045, 0.0031308) are rounded and meet only approximately.
            assertEquals(encoded, linearToSrgb(srgbToLinear(encoded)), 1e-7)
        }
    }

    @Test
    fun `D50 white in Lab maps to linear sRGB white`() {
        // Bradford adaptation maps the D50 white to the D65 white, which is sRGB (1, 1, 1).
        val white = labD50ToLinearRgb(LabColour(100.0, 0.0, 0.0))

        assertEquals(1.0, white.red, 1e-3)
        assertEquals(1.0, white.green, 1e-3)
        assertEquals(1.0, white.blue, 1e-3)
    }

    @Test
    fun `Lab to linear sRGB and back is the identity`() {
        for (lab in ColorCheckerClassicMini.referenceLabD50) {
            val roundTrip = linearRgbToLabD50(labD50ToLinearRgb(lab))

            // The published matrices are rounded to 7 digits, so they are inverses only to about 1e-6.
            assertEquals(lab.lightness, roundTrip.lightness, 1e-4)
            assertEquals(lab.a, roundTrip.a, 1e-4)
            assertEquals(lab.b, roundTrip.b, 1e-4)
        }
    }

    @Test
    fun `delta E is the Euclidean distance in Lab`() {
        assertEquals(5.0, deltaE76(LabColour(50.0, 0.0, 0.0), LabColour(50.0, 3.0, 4.0)), 1e-12)
    }

    @Test
    fun `reference neutral row is near-grey and darkens from white to black`() {
        // Patches 19-24 (indices 18-23) are the neutral row. Their channels agree to within the
        // card's small published tint (white has b* = 2.9, a slight warmth), and each is darker
        // than the one before.
        val neutrals = ColorCheckerClassicMini.referenceLinearRgb.subList(18, 24)
        for ((offset, colour) in neutrals.withIndex()) {
            assertTrue(abs(colour.red - colour.green) < 0.06, "patch ${18 + offset}: $colour")
            assertTrue(abs(colour.blue - colour.green) < 0.06, "patch ${18 + offset}: $colour")
        }
        assertEquals(neutrals.sortedByDescending { it.green }, neutrals)
    }
}
