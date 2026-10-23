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
    fun `the largest floor still leaves mass for the reading with 19 states`() {
        // 19 * 0.05 = 0.95, so 5% of the mass is left for what was read.
        val estimate = TraitEstimate.withNoiseFloor(descriptorWithStates(19), mapOf("1" to 1.0), largestFloor)

        assertTrue(estimate.probabilityOf("1") > MAX_STATE_PROBABILITY_FLOOR)
    }

    @Test
    fun `refuses the largest floor with 20 states where noise takes all the mass`() {
        assertFailsWith<IllegalArgumentException> {
            TraitEstimate.withNoiseFloor(descriptorWithStates(20), mapOf("1" to 1.0), largestFloor)
        }
    }

    @Test
    fun `refuses the largest floor with 21 states where noise takes more than all the mass`() {
        assertFailsWith<IllegalArgumentException> {
            TraitEstimate.withNoiseFloor(descriptorWithStates(21), mapOf("1" to 1.0), largestFloor)
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
    fun `noise settings accept the smallest and the largest allowed floor`() {
        TraitNoiseSettings(minStateProbability = MIN_STATE_PROBABILITY_FLOOR)
        TraitNoiseSettings(minStateProbability = MIN_STATE_PROBABILITY_FLOOR * 1.01)
        TraitNoiseSettings(minStateProbability = MAX_STATE_PROBABILITY_FLOOR)
    }

    @Test
    fun `noise settings refuse a floor just below the smallest allowed`() {
        assertFailsWith<IllegalArgumentException> { TraitNoiseSettings(minStateProbability = MIN_STATE_PROBABILITY_FLOOR * 0.99) }
        assertFailsWith<IllegalArgumentException> { TraitNoiseSettings(minStateProbability = Double.MIN_VALUE) }
        assertFailsWith<IllegalArgumentException> { TraitNoiseSettings(minStateProbability = 0.0) }
    }

    @Test
    fun `noise settings refuse a floor just above the largest allowed`() {
        assertFailsWith<IllegalArgumentException> { TraitNoiseSettings(minStateProbability = MAX_STATE_PROBABILITY_FLOOR + 1e-9) }
    }

    private val largestFloor = TraitNoiseSettings(minStateProbability = MAX_STATE_PROBABILITY_FLOOR)

    private fun descriptorWithStates(stateCount: Int) = TraitDescriptor(
        id = "states$stateCount",
        name = "$stateCount states",
        photoType = PhotoType.LEAF,
        method = TraitMethod.LEARNED,
        states = (1..stateCount).map { DescriptorState(it.toString(), "State $it") },
    )

    private fun assertClose(expected: Double, actual: Double) {
        assertTrue(abs(expected - actual) < 1e-9, "expected $expected, was $actual")
    }
}
