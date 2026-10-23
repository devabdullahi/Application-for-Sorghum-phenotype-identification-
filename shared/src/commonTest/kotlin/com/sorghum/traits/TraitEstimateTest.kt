package com.sorghum.traits

import com.sorghum.imaging.PhotoType
import kotlin.math.abs
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/** Checks the invariants of [TraitEstimate] and the noise floor every trait reading goes through. */
class TraitEstimateTest {

    private val lustre = TraitCatalogue.GRAIN_LUSTRE
    private val midrib = TraitCatalogue.MIDRIB_COLOUR

    @Test
    fun `accepts a distribution that sums to one`() {
        val estimate = TraitEstimate(lustre.id, mapOf("0" to 0.3, "+" to 0.7))

        assertEquals(0.7, estimate.probabilityOf("+"))
    }

    @Test
    fun `refuses a zero probability`() {
        assertFailsWith<IllegalArgumentException> { TraitEstimate(lustre.id, mapOf("0" to 0.0, "+" to 1.0)) }
    }

    @Test
    fun `refuses a sum off by more than the tolerance`() {
        assertFailsWith<IllegalArgumentException> { TraitEstimate(lustre.id, mapOf("0" to 0.3, "+" to 0.7 + 2e-6)) }
    }

    @Test
    fun `accepts a sum off by less than the tolerance`() {
        TraitEstimate(lustre.id, mapOf("0" to 0.3, "+" to 0.7 + 5e-7))
    }

    @Test
    fun `refuses an empty distribution`() {
        assertFailsWith<IllegalArgumentException> { TraitEstimate(lustre.id, emptyMap()) }
    }

    @Test
    fun `a state the estimate does not hold has no probability`() {
        assertFailsWith<IllegalArgumentException> { TraitEstimate(lustre.id, mapOf("0" to 0.5, "+" to 0.5)).probabilityOf("9") }
    }

    @Test
    fun `floored estimate covers every catalogue state`() {
        val estimate = TraitEstimate.withNoiseFloor(midrib, mapOf("1" to 1.0), TraitNoiseSettings())

        assertEquals(midrib.stateCodes.toSet(), estimate.probabilities.keys)
    }

    @Test
    fun `a state read as impossible gets exactly the floor`() {
        val settings = TraitNoiseSettings(minStateProbability = 0.01)

        val estimate = TraitEstimate.withNoiseFloor(lustre, mapOf("0" to 0.0, "+" to 1.0), settings)

        assertClose(0.01, estimate.probabilityOf("0"))
        assertClose(0.99, estimate.probabilityOf("+"))
    }

    @Test
    fun `a state just above zero ends just above the floor`() {
        val settings = TraitNoiseSettings(minStateProbability = 0.01)

        val estimate = TraitEstimate.withNoiseFloor(lustre, mapOf("0" to 0.001, "+" to 0.999), settings)

        assertTrue(estimate.probabilityOf("0") > 0.01)
    }

    @Test
    fun `floor keeps the order of the raw probabilities`() {
        val estimate = TraitEstimate.withNoiseFloor(midrib, mapOf("1" to 0.6, "2" to 0.3, "3" to 0.1), TraitNoiseSettings())

        assertTrue(estimate.probabilityOf("1") > estimate.probabilityOf("2"))
        assertTrue(estimate.probabilityOf("2") > estimate.probabilityOf("3"))
        assertTrue(estimate.probabilityOf("3") > estimate.probabilityOf("4"))
    }

    @Test
    fun `raw scores that do not sum to one are normalised first`() {
        val fromScores = TraitEstimate.withNoiseFloor(lustre, mapOf("0" to 1.0, "+" to 3.0), TraitNoiseSettings())
        val fromProbabilities = TraitEstimate.withNoiseFloor(lustre, mapOf("0" to 0.25, "+" to 0.75), TraitNoiseSettings())

        assertClose(fromProbabilities.probabilityOf("+"), fromScores.probabilityOf("+"))
    }

    @Test
    fun `refuses a state code the descriptor does not have`() {
        assertFailsWith<IllegalArgumentException> {
            TraitEstimate.withNoiseFloor(lustre, mapOf("1" to 1.0), TraitNoiseSettings())
        }
    }

    @Test
    fun `refuses negative or all-zero raw probabilities`() {
        assertFailsWith<IllegalArgumentException> {
            TraitEstimate.withNoiseFloor(lustre, mapOf("0" to -0.1, "+" to 1.1), TraitNoiseSettings())
        }
        assertFailsWith<IllegalArgumentException> {
            TraitEstimate.withNoiseFloor(lustre, mapOf("0" to 0.0, "+" to 0.0), TraitNoiseSettings())
        }
    }

    @Test
    fun `refuses a floor that would leave no room for the reading`() {
        // 21 states at the largest allowed floor would hand more than all the mass to noise.
        val manyStates = TraitDescriptor(
            id = "manyStates",
            name = "Many states",
            photoType = PhotoType.LEAF,
            method = TraitMethod.LEARNED,
            states = (1..21).map { DescriptorState(it.toString(), "State $it") },
        )
        assertFailsWith<IllegalArgumentException> {
            TraitEstimate.withNoiseFloor(manyStates, mapOf("1" to 1.0), TraitNoiseSettings(minStateProbability = MAX_STATE_PROBABILITY_FLOOR))
        }
    }

    @Test
    fun `an observed state is near certain but keeps the floor`() {
        val settings = TraitNoiseSettings(minStateProbability = 0.01)

        val estimate = TraitEstimate.observedState(midrib, "2", settings)

        assertClose(1.0 - 5 * 0.01, estimate.probabilityOf("2"))
        assertClose(0.01, estimate.probabilityOf("4"))
    }

    @Test
    fun `noise settings accept the smallest positive and the largest allowed floor`() {
        TraitNoiseSettings(minStateProbability = Double.MIN_VALUE)
        TraitNoiseSettings(minStateProbability = MAX_STATE_PROBABILITY_FLOOR)
    }

    @Test
    fun `noise settings refuse a zero floor and one above the maximum`() {
        assertFailsWith<IllegalArgumentException> { TraitNoiseSettings(minStateProbability = 0.0) }
        assertFailsWith<IllegalArgumentException> { TraitNoiseSettings(minStateProbability = MAX_STATE_PROBABILITY_FLOOR + 1e-9) }
    }

    private fun assertClose(expected: Double, actual: Double) {
        assertTrue(abs(expected - actual) < 1e-9, "expected $expected, was $actual")
    }
}
