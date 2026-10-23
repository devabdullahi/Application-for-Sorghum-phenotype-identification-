package com.sorghum.traits

import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.sqrt

/**
 * A continuous trait as measured: a value and its uncertainty, before it is turned into state
 * probabilities for reasoning (CLAUDE.md, `TraitEstimate`).
 *
 * The measurement error is modelled as normal, so the probability of each state is the normal
 * mass inside that state's bin.
 *
 * @param traitId the [TraitDescriptor.id] this measurement is for.
 * @param value the measured value, in [unit].
 * @param standardDeviation one standard deviation of the measurement error, in [unit]. Must
 *   be positive: a value with no uncertainty would be a bare state.
 * @param unit the unit of [value] and [standardDeviation]; must match the descriptor's bins.
 */
data class ContinuousTraitEstimate(
    val traitId: String,
    val value: Double,
    val standardDeviation: Double,
    val unit: MeasurementUnit,
) {
    init {
        require(value.isFinite()) { "Value of $traitId must be finite, was $value" }
        require(standardDeviation > 0.0 && standardDeviation.isFinite()) {
            "Standard deviation of $traitId must be positive, was $standardDeviation"
        }
    }

    /**
     * The state probabilities of this measurement under [descriptor]'s bins, with the noise
     * floor applied as for any other trait.
     */
    fun toTraitEstimate(descriptor: TraitDescriptor, settings: TraitNoiseSettings): TraitEstimate {
        require(descriptor.id == traitId) { "Measurement of $traitId cannot be read as ${descriptor.id}" }
        val bins = requireNotNull(descriptor.continuousBins) { "Trait ${descriptor.id} has no bins for a continuous value" }
        require(bins.unit == unit) { "Measurement of $traitId is in $unit but the bins are in ${bins.unit}" }

        val cumulativeAtEdges = listOf(0.0) + bins.upperEdges.map { normalCdf((it - value) / standardDeviation) } + listOf(1.0)
        val rawProbabilities = descriptor.stateCodes.withIndex().associate { (index, code) ->
            // Clamped because rounding in the cdf can make a far-away bin a hair below zero.
            code to (cumulativeAtEdges[index + 1] - cumulativeAtEdges[index]).coerceAtLeast(0.0)
        }
        return TraitEstimate.withNoiseFloor(descriptor, rawProbabilities, settings)
    }
}

/** Standard normal cumulative distribution function. */
internal fun normalCdf(z: Double): Double = 0.5 * complementaryErrorFunction(-z / sqrt(2.0))

/**
 * erfc(x) by the Chebyshev fit in Numerical Recipes (2nd ed., section 6.2, `erfcc`), with a
 * fractional error below 1.2e-7 everywhere. The Kotlin standard library has no erf, and this
 * accuracy is well inside the 1e-6 probability tolerance.
 */
private fun complementaryErrorFunction(x: Double): Double {
    val z = abs(x)
    val t = 1.0 / (1.0 + 0.5 * z)
    val polynomial = -z * z - 1.26551223 + t * (1.00002368 + t * (0.37409196 + t * (0.09678418 +
        t * (-0.18628806 + t * (0.27886807 + t * (-1.13520398 + t * (1.48851587 +
            t * (-0.82215223 + t * 0.17087277))))))))
    val result = t * exp(polynomial)
    return if (x >= 0.0) result else 2.0 - result
}
