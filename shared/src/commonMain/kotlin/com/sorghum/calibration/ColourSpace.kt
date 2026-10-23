package com.sorghum.calibration

import kotlin.math.cbrt
import kotlin.math.pow
import kotlin.math.sqrt

/**
 * A colour in linear-light sRGB (IEC 61966-2-1 primaries, D65 white). In-gamut colours have
 * channels in 0..1; fitted or reference values may fall slightly outside, which is kept rather
 * than clipped so least squares sees the true numbers.
 */
internal data class LinearRgb(val red: Double, val green: Double, val blue: Double)

/** A colour as the camera encoded it: 8-bit sRGB channel values 0–255 (averages, so fractional). */
internal data class SrgbColour(val red: Float, val green: Float, val blue: Float) {
    /** Removes the sRGB transfer curve, giving linear light 0..1. */
    fun toLinear(): LinearRgb = LinearRgb(
        srgbToLinear(red / 255.0),
        srgbToLinear(green / 255.0),
        srgbToLinear(blue / 255.0),
    )
}

/** A CIE 1976 L*a*b* colour relative to the ICC D50 white, the space X-Rite publishes card values in. */
internal data class LabColour(val lightness: Double, val a: Double, val b: Double)

/** Decodes one sRGB channel (0..1) to linear light, per IEC 61966-2-1. */
internal fun srgbToLinear(encoded: Double): Double =
    if (encoded <= 0.04045) encoded / 12.92 else ((encoded + 0.055) / 1.055).pow(2.4)

/** Encodes one linear channel (0..1) to sRGB, the inverse of [srgbToLinear]. */
internal fun linearToSrgb(linear: Double): Double =
    if (linear <= 0.0031308) linear * 12.92 else 1.055 * linear.pow(1 / 2.4) - 0.055

/** CIE 1976 colour difference: Euclidean distance in L*a*b*. 1 is about one just-noticeable step. */
internal fun deltaE76(first: LabColour, second: LabColour): Double {
    val dL = first.lightness - second.lightness
    val da = first.a - second.a
    val db = first.b - second.b
    return sqrt(dL * dL + da * da + db * db)
}

/**
 * Converts linear sRGB to L*a*b* (D50): sRGB -> XYZ (D65) -> Bradford chromatic adaptation to
 * D50 -> Lab. D50 because the card's reference values are D50 Lab, so the fit residual is
 * measured where the reference values were measured.
 */
internal fun linearRgbToLabD50(colour: LinearRgb): LabColour {
    val xyzD65 = multiply(LINEAR_SRGB_TO_XYZ_D65, colour.red, colour.green, colour.blue)
    val xyzD50 = multiply(BRADFORD_D65_TO_D50, xyzD65[0], xyzD65[1], xyzD65[2])
    val fx = labCompand(xyzD50[0] / D50_WHITE_X)
    val fy = labCompand(xyzD50[1] / D50_WHITE_Y)
    val fz = labCompand(xyzD50[2] / D50_WHITE_Z)
    return LabColour(lightness = 116 * fy - 16, a = 500 * (fx - fy), b = 200 * (fy - fz))
}

/** Converts L*a*b* (D50) to linear sRGB, the inverse of [linearRgbToLabD50]. */
internal fun labD50ToLinearRgb(lab: LabColour): LinearRgb {
    val fy = (lab.lightness + 16) / 116
    val fx = fy + lab.a / 500
    val fz = fy - lab.b / 200
    val xyzD65 = multiply(
        BRADFORD_D50_TO_D65,
        labUncompand(fx) * D50_WHITE_X,
        labUncompand(fy) * D50_WHITE_Y,
        labUncompand(fz) * D50_WHITE_Z,
    )
    val rgb = multiply(XYZ_D65_TO_LINEAR_SRGB, xyzD65[0], xyzD65[1], xyzD65[2])
    return LinearRgb(rgb[0], rgb[1], rgb[2])
}

// CIE constants: epsilon = (6/29)^3 and the slope of the linear segment near black.
private const val LAB_EPSILON = 216.0 / 24389.0
private const val LAB_KAPPA = 24389.0 / 27.0

private fun labCompand(ratio: Double): Double =
    if (ratio > LAB_EPSILON) cbrt(ratio) else (LAB_KAPPA * ratio + 16) / 116

private fun labUncompand(f: Double): Double {
    val cubed = f * f * f
    return if (cubed > LAB_EPSILON) cubed else (116 * f - 16) / LAB_KAPPA
}

private fun multiply(matrix: DoubleArray, x: Double, y: Double, z: Double): DoubleArray = doubleArrayOf(
    matrix[0] * x + matrix[1] * y + matrix[2] * z,
    matrix[3] * x + matrix[4] * y + matrix[5] * z,
    matrix[6] * x + matrix[7] * y + matrix[8] * z,
)

// Matrices and white point from Bruce Lindbloom's reference tables (brucelindbloom.com,
// "RGB/XYZ Matrices" and "Chromatic Adaptation"), which use the same D50 white as ICC.
private const val D50_WHITE_X = 0.96422
private const val D50_WHITE_Y = 1.0
private const val D50_WHITE_Z = 0.82521

private val LINEAR_SRGB_TO_XYZ_D65 = doubleArrayOf(
    0.4124564, 0.3575761, 0.1804375,
    0.2126729, 0.7151522, 0.0721750,
    0.0193339, 0.1191920, 0.9503041,
)

private val XYZ_D65_TO_LINEAR_SRGB = doubleArrayOf(
    3.2404542, -1.5371385, -0.4985314,
    -0.9692660, 1.8760108, 0.0415560,
    0.0556434, -0.2040259, 1.0572252,
)

private val BRADFORD_D65_TO_D50 = doubleArrayOf(
    1.0478112, 0.0228866, -0.0501270,
    0.0295424, 0.9904844, -0.0170491,
    -0.0092345, 0.0150436, 0.7521316,
)

private val BRADFORD_D50_TO_D65 = doubleArrayOf(
    0.9555766, -0.0230393, 0.0631636,
    -0.0282895, 1.0099416, 0.0210077,
    0.0122982, -0.0204830, 1.3299098,
)
