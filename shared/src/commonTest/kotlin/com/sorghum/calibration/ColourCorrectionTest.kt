package com.sorghum.calibration

import com.sorghum.imaging.Rgb
import com.sorghum.imaging.pixelImage
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class ColourCorrectionTest {

    private val reference = ColorCheckerClassicMini.referenceLinearRgb
    private val referenceLab = ColorCheckerClassicMini.referenceLabD50

    private fun fit(measured: List<LinearRgb>, target: List<LinearRgb> = reference) =
        fitAffineColourCorrection(measured, target, target.map(::linearRgbToLabD50))

    @Test
    fun `fit on already correct colours is the identity`() {
        val correction = assertNotNull(fit(reference))

        for (colour in reference) {
            val corrected = correction.correct(colour)
            assertEquals(colour.red, corrected.red, 1e-9)
            assertEquals(colour.green, corrected.green, 1e-9)
            assertEquals(colour.blue, corrected.blue, 1e-9)
        }
    }

    @Test
    fun `fit undoes a known affine cast exactly`() {
        val measured = reference.map { applyTestCast(it) }

        val correction = assertNotNull(fit(measured))

        for (index in reference.indices) {
            val corrected = correction.correct(measured[index])
            assertEquals(reference[index].red, corrected.red, 1e-9)
            assertEquals(reference[index].green, corrected.green, 1e-9)
            assertEquals(reference[index].blue, corrected.blue, 1e-9)
        }
    }

    @Test
    fun `fit fails when all patches look the same`() {
        // A flat grey card carries no colour information; the system has no unique solution.
        val measured = List(reference.size) { LinearRgb(0.3, 0.3, 0.3) }

        assertNull(fit(measured))
    }

    @Test
    fun `mean delta E is zero for a perfect fit and grows with error`() {
        assertEquals(0f, assertNotNull(fit(reference)).meanDeltaE, 1e-4f)

        // Measured colours that no affine map can explain: swap two patches.
        val swapped = reference.toMutableList().also { it[0] = reference[15]; it[15] = reference[0] }
        val error = assertNotNull(fitAffineColourCorrection(swapped, reference, referenceLab)).meanDeltaE
        assertTrue(error > 3f, "mean delta E was $error")
    }

    @Test
    fun `applying a correction yields linear sRGB floats clamped to 0-1`() {
        // Identity correction: the output is just the decoded input.
        val identity = assertNotNull(fit(reference))
        val image = pixelImage(2, 1) { x, _ -> if (x == 0) Rgb(0, 128, 255) else Rgb(255, 255, 255) }

        val corrected = applyColourCorrection(image, identity)

        assertEquals(2, corrected.width)
        assertEquals(1, corrected.height)
        assertEquals(0f, corrected.correctedLinearRgb[0], 1e-6f)
        assertEquals(srgbToLinear(128 / 255.0).toFloat(), corrected.correctedLinearRgb[1], 1e-6f)
        assertEquals(1f, corrected.correctedLinearRgb[2], 1e-6f)
        assertEquals(1f, corrected.correctedLinearRgb[3], 1e-6f)
    }

    @Test
    fun `applying a brightening correction clamps at 1`() {
        // Fit a correction that doubles every channel, then apply it to white.
        val doubled = reference.map { LinearRgb(it.red * 2, it.green * 2, it.blue * 2) }
        val correction = assertNotNull(fit(reference, target = doubled))

        val corrected = applyColourCorrection(pixelImage(1, 1) { _, _ -> Rgb(255, 255, 255) }, correction)

        assertEquals(1f, corrected.correctedLinearRgb[0])
    }
}
