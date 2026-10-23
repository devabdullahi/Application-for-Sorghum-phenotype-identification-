package com.sorghum.reasoning

import com.sorghum.traits.TraitCatalogue
import com.sorghum.traits.TraitEstimate
import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.ln
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/** Naive Bayes ranking, decision, explanation and correction on the tiny test table. */
class CultivarIdentificationTest {

    private val tables = testTables()
    private val settings = ReasoningSettings(traitNoise = testNoise)

    @Test
    fun `no cultivar gets a zero posterior even when a reading contradicts its table`() {
        val ranking = rankCultivars(tables, observed(MIDRIB to "1", LUSTRE to "0", GLUME to "6"))

        assertEquals(4, ranking.size)
        assertTrue(ranking.all { it.posterior > 0.0 })
        assertClose(1.0, ranking.sumOf { it.posterior }, 1e-9)
    }

    @Test
    fun `a unique profile gives a single match`() {
        val result = identifyCultivar(tables, observed(MIDRIB to "1", LUSTRE to "0", GLUME to "6"), settings)

        assertEquals(IdentificationOutcome.SINGLE_MATCH, result.outcome)
        assertEquals(listOf("gamma"), result.group.map { it.cultivarId })
        assertEquals("gamma", result.topMatches.first().cultivarId)
    }

    @Test
    fun `cultivars sharing the observed profile come back as a group`() {
        val result = identifyCultivar(tables, observed(MIDRIB to "2", LUSTRE to "+", GLUME to "4"), settings)

        assertEquals(IdentificationOutcome.GROUP, result.outcome)
        assertEquals(setOf("alpha", "beta"), result.group.map { it.cultivarId }.toSet())
    }

    @Test
    fun `readings no cultivar explains are unrecognized with the compatible group`() {
        val result = identifyCultivar(tables, observed(MIDRIB to "5", LUSTRE to "+", GLUME to "7"), settings)

        assertEquals(IdentificationOutcome.UNRECOGNIZED, result.outcome)
        assertTrue(result.group.isNotEmpty())
        assertTrue(result.group.first().fitScore < settings.minFitScore)
    }

    @Test
    fun `no readings leave every cultivar in one group`() {
        val result = identifyCultivar(tables, emptyMap(), settings)

        assertEquals(IdentificationOutcome.GROUP, result.outcome)
        assertEquals(4, result.group.size)
        assertEquals(1.0, result.group.first().fitScore)
    }

    @Test
    fun `fit threshold boundary decides recognized or unrecognized`() {
        val estimates = observed(MIDRIB to "1", LUSTRE to "0", GLUME to "6")
        val fit = identifyCultivar(tables, estimates, settings).group.first().fitScore

        assertEquals(IdentificationOutcome.SINGLE_MATCH, outcomeWith(estimates, minFitScore = fit))
        assertEquals(IdentificationOutcome.SINGLE_MATCH, outcomeWith(estimates, minFitScore = fit * 0.999))
        assertEquals(IdentificationOutcome.UNRECOGNIZED, outcomeWith(estimates, minFitScore = fit * 1.001))
    }

    @Test
    fun `group likelihood ratio boundary decides who joins the group`() {
        // Midrib read as white (gamma) or yellow (delta) with almost equal weight, so delta is
        // the runner-up at some likelihood ratio below the top match.
        val estimates = mapOf(
            MIDRIB to TraitEstimate.withNoiseFloor(TraitCatalogue.MIDRIB_COLOUR, mapOf("1" to 0.55, "3" to 0.45), testNoise),
        ) + observed(LUSTRE to "0", GLUME to "6")
        val ranking = rankCultivars(tables, estimates)
        val best = ranking[0]
        val second = ranking[1]
        val ratio = exp(second.logLikelihood - best.logLikelihood)

        assertTrue(second.cultivarId in groupWith(estimates, ratio))
        assertTrue(second.cultivarId in groupWith(estimates, ratio * 0.999))
        assertTrue(second.cultivarId !in groupWith(estimates, ratio * 1.001))
    }

    @Test
    fun `explanation orders traits by how much they separated the top match from the runner-up`() {
        val estimates = mapOf(
            LUSTRE to TraitEstimate.withNoiseFloor(TraitCatalogue.GRAIN_LUSTRE, mapOf("0" to 0.6, "+" to 0.4), testNoise),
        ) + observed(MIDRIB to "1", GLUME to "6")

        val result = identifyCultivar(tables, estimates, settings)

        assertEquals("gamma", result.group.single().cultivarId)
        assertEquals("delta", result.comparedCultivarId)
        assertEquals(listOf(MIDRIB, GLUME, LUSTRE), result.explanation.map { it.traitId })
        val magnitudes = result.explanation.map { abs(it.logLikelihoodRatio) }
        assertEquals(magnitudes.sortedDescending(), magnitudes)
    }

    @Test
    fun `explanation adds up to the posterior ratio of the top match and the runner-up`() {
        val estimates = observed(MIDRIB to "1", LUSTRE to "0", GLUME to "6")

        val result = identifyCultivar(tables, estimates, settings)

        val ranking = rankCultivars(tables, estimates)
        val top = ranking.single { it.cultivarId == result.group.first().cultivarId }
        val compared = ranking.single { it.cultivarId == result.comparedCultivarId }
        val priorLogRatio = ln(tables.priors.getValue(top.cultivarId) / tables.priors.getValue(compared.cultivarId))
        assertClose(ln(top.posterior / compared.posterior), priorLogRatio + result.explanation.sumOf { it.logLikelihoodRatio }, 1e-9)
    }

    @Test
    fun `top matches are limited and ordered by posterior`() {
        val result = identifyCultivar(tables, observed(MIDRIB to "1"), ReasoningSettings(topMatchCount = 2, traitNoise = testNoise))

        assertEquals(2, result.topMatches.size)
        assertTrue(result.topMatches[0].posterior >= result.topMatches[1].posterior)
    }

    @Test
    fun `a trait the tables do not cover is ignored`() {
        val withSeed = observed(MIDRIB to "1") + observed(TraitCatalogue.GRAIN_COLOUR.id to "2")

        assertEquals(
            rankCultivars(tables, observed(MIDRIB to "1")).map { it.posterior },
            rankCultivars(tables, withSeed).map { it.posterior },
        )
    }

    @Test
    fun `a correction replaces the trait and recomputes from the stored estimates`() {
        val ambiguousMidrib = TraitEstimate.withNoiseFloor(TraitCatalogue.MIDRIB_COLOUR, mapOf("1" to 0.5, "3" to 0.5), testNoise)
        val stored = mapOf(MIDRIB to ambiguousMidrib) + observed(LUSTRE to "0", GLUME to "6")

        val corrected = correctTrait(tables, stored, MIDRIB, "3", settings)

        assertEquals(TraitEstimate.observedState(TraitCatalogue.MIDRIB_COLOUR, "3", testNoise), corrected.estimates.getValue(MIDRIB))
        assertEquals(stored.getValue(LUSTRE), corrected.estimates.getValue(LUSTRE))
        assertEquals(identifyCultivar(tables, corrected.estimates, settings), corrected.identification)
        assertEquals("delta", corrected.identification.group.first().cultivarId)
    }

    @Test
    fun `a correction keeps the noise floor`() {
        val corrected = correctTrait(tables, emptyMap(), MIDRIB, "3", settings)

        assertTrue(corrected.estimates.getValue(MIDRIB).probabilities.values.all { it >= testNoise.minStateProbability })
    }

    @Test
    fun `a correction refuses an unknown trait or state`() {
        assertFailsWith<IllegalArgumentException> { correctTrait(tables, emptyMap(), "leafHairiness", "1", settings) }
        assertFailsWith<IllegalArgumentException> { correctTrait(tables, emptyMap(), MIDRIB, "9", settings) }
    }

    @Test
    fun `settings refuse values outside their ranges`() {
        assertFailsWith<IllegalArgumentException> { ReasoningSettings(topMatchCount = 0) }
        assertFailsWith<IllegalArgumentException> { ReasoningSettings(minFitScore = 0.0) }
        assertFailsWith<IllegalArgumentException> { ReasoningSettings(minGroupLikelihoodRatio = 0.0) }
        assertFailsWith<IllegalArgumentException> { ReasoningSettings(minGroupLikelihoodRatio = 1.0 + 1e-9) }
        ReasoningSettings(topMatchCount = 1, minGroupLikelihoodRatio = 1.0)
    }

    private fun outcomeWith(estimates: Map<String, TraitEstimate>, minFitScore: Double): IdentificationOutcome =
        identifyCultivar(tables, estimates, settings.copy(minFitScore = minFitScore)).outcome

    private fun groupWith(estimates: Map<String, TraitEstimate>, minGroupLikelihoodRatio: Double): List<String> =
        identifyCultivar(tables, estimates, settings.copy(minGroupLikelihoodRatio = minGroupLikelihoodRatio)).group.map { it.cultivarId }

    private fun assertClose(expected: Double, actual: Double, tolerance: Double) {
        assertTrue(abs(expected - actual) < tolerance, "expected $expected, was $actual")
    }
}
