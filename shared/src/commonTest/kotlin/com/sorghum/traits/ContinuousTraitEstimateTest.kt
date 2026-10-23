package com.sorghum.traits

import kotlin.math.abs
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/** A measured value with uncertainty becomes state probabilities through the descriptor's bins. */
class ContinuousTraitEstimateTest {

    // Two bins: below 2 g is "small", 2 g and above is "large".
    private val twoClassWeight = TraitDescriptor(
        id = "testWeight",
        name = "Test weight",
        photoType = PhotoType.GRAIN,
        method = TraitMethod.MEASURED,
        states = listOf(DescriptorState("3", "Small"), DescriptorState("7", "Large")),
        continuousBins = StateBins(MeasurementUnit.GRAMS, listOf(2.0)),
    )
    private val noise = TraitNoiseSettings(minStateProbability = 0.01)

    @Test
    fun `a value on the edge splits evenly`() {
        val measured = ContinuousTraitEstimate(twoClassWeight.id, value = 2.0, standardDeviation = 0.3, unit = MeasurementUnit.GRAMS)

        val estimate = measured.toTraitEstimate(twoClassWeight, noise)

        assertClose(0.5, estimate.probabilityOf("3"), 1e-6)
    }

    @Test
    fun `a value just below the edge leans to the lower state`() {
        val measured = ContinuousTraitEstimate(twoClassWeight.id, value = 1.99, standardDeviation = 0.3, unit = MeasurementUnit.GRAMS)

        assertTrue(measured.toTraitEstimate(twoClassWeight, noise).probabilityOf("3") > 0.5)
    }

    @Test
    fun `a value just above the edge leans to the upper state`() {
        val measured = ContinuousTraitEstimate(twoClassWeight.id, value = 2.01, standardDeviation = 0.3, unit = MeasurementUnit.GRAMS)

        assertTrue(measured.toTraitEstimate(twoClassWeight, noise).probabilityOf("7") > 0.5)
    }

    @Test
    fun `one standard deviation below the edge gives the normal cdf`() {
        val measured = ContinuousTraitEstimate(twoClassWeight.id, value = 1.7, standardDeviation = 0.3, unit = MeasurementUnit.GRAMS)

        val estimate = measured.toTraitEstimate(twoClassWeight, noise)

        // P(X >= mean + 1 sd) = 0.158655; then mixed with the floor: p * (1 - 2 * 0.01) + 0.01.
        assertClose(0.158655 * 0.98 + 0.01, estimate.probabilityOf("7"), 1e-6)
    }

    @Test
    fun `a far value still leaves the floor on the other state`() {
        val measured = ContinuousTraitEstimate(twoClassWeight.id, value = 10.0, standardDeviation = 0.1, unit = MeasurementUnit.GRAMS)

        assertClose(0.01, measured.toTraitEstimate(twoClassWeight, noise).probabilityOf("3"), 1e-9)
    }

    @Test
    fun `middle bins take the mass between their edges`() {
        val seedWeight = TraitCatalogue.HUNDRED_SEED_WEIGHT
        val edges = seedWeight.continuousBins!!.upperEdges
        val middle = (edges[0] + edges[1]) / 2
        val measured = ContinuousTraitEstimate(seedWeight.id, value = middle, standardDeviation = 0.05, unit = MeasurementUnit.GRAMS)

        val estimate = measured.toTraitEstimate(seedWeight, noise)

        assertEquals(seedWeight.states[1].code, estimate.probabilities.maxBy { it.value }.key)
    }

    @Test
    fun `refuses a unit that does not match the bins`() {
        val measured = ContinuousTraitEstimate(twoClassWeight.id, value = 2.0, standardDeviation = 0.3, unit = MeasurementUnit.MILLIMETRES)

        assertFailsWith<IllegalArgumentException> { measured.toTraitEstimate(twoClassWeight, noise) }
    }

    @Test
    fun `refuses a descriptor without bins`() {
        val measured = ContinuousTraitEstimate(TraitCatalogue.GRAIN_LUSTRE.id, value = 1.0, standardDeviation = 0.3, unit = MeasurementUnit.GRAMS)

        assertFailsWith<IllegalArgumentException> { measured.toTraitEstimate(TraitCatalogue.GRAIN_LUSTRE, noise) }
    }

    @Test
    fun `refuses a zero or negative uncertainty`() {
        // A bare value with no uncertainty would be a bare state, which a trait never reports.
        assertFailsWith<IllegalArgumentException> {
            ContinuousTraitEstimate(twoClassWeight.id, value = 2.0, standardDeviation = 0.0, unit = MeasurementUnit.GRAMS)
        }
    }

    private fun assertClose(expected: Double, actual: Double, tolerance: Double) {
        assertTrue(abs(expected - actual) < tolerance, "expected $expected, was $actual")
    }
}
