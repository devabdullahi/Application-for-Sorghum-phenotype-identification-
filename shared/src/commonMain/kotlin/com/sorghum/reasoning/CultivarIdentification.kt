package com.sorghum.reasoning

import com.sorghum.traits.TraitCatalogue
import com.sorghum.traits.TraitEstimate
import com.sorghum.traits.TraitNoiseSettings
import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.ln

/**
 * A reading whose every state is within this of 1/k (k states) is uniform: it says nothing
 * about the sample, so reasoning treats it as not read. 1e-6 is the parity tolerance for
 * probabilities (CLAUDE.md, Parity), so two estimates the platforms may legitimately differ by
 * are treated alike.
 *
 * Why it matters: a uniform reading gives every cultivar the same likelihood 1/k, so it cannot
 * move the ranking, but it would pull [CultivarMatch.fitScore] towards exactly 1.0, the
 * default [ReasoningSettings.minFitScore], where rounding alone would decide "recognized".
 */
const val UNIFORM_READING_TOLERANCE = 1e-6

/**
 * Thresholds of the cultivar decision.
 *
 * @param topMatchCount how many ranked cultivars the result lists. 5 fits one phone screen.
 * @param minFitScore the least [CultivarMatch.fitScore] the best match needs to count as
 *   recognized. 1.0 means "explains the readings better than a cultivar about which nothing is
 *   known": below it, the readings fit the best match worse than chance, so the sample is
 *   probably a cultivar the tables do not hold. Initial guess, tune on real photos.
 * @param minGroupLikelihoodRatio a cultivar joins the top match's group when the readings are
 *   at least this likely under it as under the top match. 0.5 means the evidence prefers the top
 *   match by at most 2:1, too little to tell them apart (DUS-style groups). Must be in (0, 1];
 *   1.0 groups only exact ties. Initial guess, tune on real photos.
 * @param traitNoise the floor for the near-certain estimate a user correction creates.
 */
data class ReasoningSettings(
    val topMatchCount: Int = 5,
    val minFitScore: Double = 1.0,
    val minGroupLikelihoodRatio: Double = 0.5,
    val traitNoise: TraitNoiseSettings = TraitNoiseSettings(),
) {
    init {
        require(topMatchCount >= 1) { "topMatchCount must be at least 1, was $topMatchCount" }
        require(minFitScore > 0.0 && minFitScore.isFinite()) { "minFitScore must be positive, was $minFitScore" }
        require(minGroupLikelihoodRatio > 0.0 && minGroupLikelihoodRatio <= 1.0) {
            "minGroupLikelihoodRatio must be within (0, 1], was $minGroupLikelihoodRatio"
        }
    }
}

/**
 * One cultivar in the ranking.
 *
 * @param posterior P(cultivar | readings); all posteriors of a ranking sum to 1.
 * @param logLikelihood natural log of P(readings | cultivar), the product over traits of
 *   sum over states of P(state | cultivar) * estimate(state). Kept in log space because the
 *   product of many small numbers underflows.
 * @param fitScore how well this cultivar explains the readings, independent of the other
 *   cultivars: the geometric mean over traits of (number of states * per-trait likelihood).
 *   1.0 is what a cultivar with uniform rows scores, so above 1 means "fits better than
 *   chance". Scaling by the state count makes traits with 2 and 13 states comparable. 1.0 when
 *   there are no readings. Uniform readings are left out (see [UNIFORM_READING_TOLERANCE]).
 */
data class CultivarMatch(
    val cultivarId: String,
    val cultivarName: String,
    val posterior: Double,
    val logLikelihood: Double,
    val fitScore: Double,
)

/** What the readings support. A plain enum, because only `SessionState` is sealed (ADR-0003). */
enum class IdentificationOutcome {
    /**
     * One cultivar fits and the evidence separates it from all others. Never returned without
     * evidence: with no informative reading of a table trait the outcome is [GROUP], even when
     * the tables hold a single cultivar.
     */
    SINGLE_MATCH,

    /** Several cultivars fit and the readings cannot tell them apart; show all of them. */
    GROUP,

    /** Even the best match explains the readings poorly; the group lists the closest cultivars. */
    UNRECOGNIZED,
}

/**
 * How much one trait separated the top match from the compared cultivar.
 *
 * @param logLikelihoodRatio ln P(reading | top match) - ln P(reading | compared cultivar).
 *   Positive means the trait favoured the top match. The ratios of all traits plus the log
 *   prior ratio add up to the log posterior ratio of the two, so the explanation is the
 *   posterior's own arithmetic, not a separate story.
 */
data class TraitInfluence(val traitId: String, val logLikelihoodRatio: Double)

/**
 * The result of reasoning over all readings so far.
 *
 * @param group the top match plus every cultivar the readings cannot tell from it, best first.
 *   For [IdentificationOutcome.UNRECOGNIZED] this is the compatible group to show next to
 *   "unrecognized".
 * @param topMatches the best [ReasoningSettings.topMatchCount] cultivars by posterior.
 * @param explanation every trait used, ordered by how strongly it separated the top match from
 *   [comparedCultivarId] (largest |ratio| first). Empty when there is nothing to compare with.
 * @param comparedCultivarId the cultivar the explanation contrasts with: the best one outside
 *   the group, or the second best when everything is in the group; null with one cultivar.
 */
data class CultivarIdentification(
    val outcome: IdentificationOutcome,
    val group: List<CultivarMatch>,
    val topMatches: List<CultivarMatch>,
    val explanation: List<TraitInfluence>,
    val comparedCultivarId: String?,
)

/** The estimates after a user correction and the reasoning recomputed from them. */
data class CorrectedIdentification(
    val estimates: Map<String, TraitEstimate>,
    val identification: CultivarIdentification,
)

/**
 * Ranks every cultivar by naive Bayes posterior given the trait readings, best first.
 *
 * Each trait is marginalised over its uncertain reading (soft evidence): P(reading | cultivar)
 * = sum over states of P(state | cultivar) * estimate(state). Traits the tables do not cover,
 * and uniform readings ([UNIFORM_READING_TOLERANCE]), are ignored. Pure and cheap (cultivars x
 * traits x states), so it may run on the main thread.
 *
 * ASSUMPTION — confirm with `model/`: the sum treats each estimate as a likelihood of the
 * photo given the true state, up to a constant. That holds for measured readers, and for a
 * learned head only if it outputs calibrated probabilities under a uniform state prior
 * (trained on state-balanced data, or with the training state frequencies divided out). A
 * head that has learned the training set's state frequencies counts that prior a second time,
 * on top of the cultivar tables, and drags every result towards common states.
 *
 * @param estimates trait readings keyed by their own [TraitEstimate.traitId]. Each estimate of
 *   a table trait must cover exactly its descriptor's state codes. Throws
 *   [IllegalArgumentException] otherwise, because a misfiled or partial estimate is a bug in
 *   the caller, not a reading to reason with.
 */
fun rankCultivars(tables: CultivarTables, estimates: Map<String, TraitEstimate>): List<CultivarMatch> =
    scoreCultivars(tables, informativeEstimates(tables, estimates)).map { it.match }

/**
 * Ranks the cultivars and decides what the readings support: a single match, a group, or
 * "unrecognized" with the compatible group. Never forces a single pick when the evidence
 * cannot separate cultivars.
 *
 * With no evidence (no informative reading of any table trait) the outcome is
 * [IdentificationOutcome.GROUP] with every cultivar: nothing was read, so nothing can be told
 * apart. Not UNRECOGNIZED, which means the readings contradict the tables, and there are no
 * readings to contradict them. See [rankCultivars] for the requirements on [estimates].
 */
fun identifyCultivar(
    tables: CultivarTables,
    estimates: Map<String, TraitEstimate>,
    settings: ReasoningSettings,
): CultivarIdentification {
    val evidence = informativeEstimates(tables, estimates)
    val scores = scoreCultivars(tables, evidence)
    val best = scores.first()
    val group = scores.filter { exp(it.match.logLikelihood - best.match.logLikelihood) >= settings.minGroupLikelihoodRatio }
    val outcome = when {
        evidence.isEmpty() -> IdentificationOutcome.GROUP
        best.match.fitScore < settings.minFitScore -> IdentificationOutcome.UNRECOGNIZED
        group.size == 1 -> IdentificationOutcome.SINGLE_MATCH
        else -> IdentificationOutcome.GROUP
    }
    val compared = scores.firstOrNull { it !in group } ?: scores.getOrNull(1)
    val explanation = if (compared == null) emptyList() else explainRanking(best, compared)

    return CultivarIdentification(
        outcome = outcome,
        group = group.map { it.match },
        topMatches = scores.take(settings.topMatchCount).map { it.match },
        explanation = explanation,
        comparedCultivarId = compared?.match?.cultivarId,
    )
}

/**
 * Applies a user correction: replaces [traitId]'s estimate with a near-certain reading of
 * [stateCode] (the noise floor still applies) and reasons again from the stored estimates.
 * No image work runs, and the previous posterior is not patched.
 */
fun correctTrait(
    tables: CultivarTables,
    estimates: Map<String, TraitEstimate>,
    traitId: String,
    stateCode: String,
    settings: ReasoningSettings,
): CorrectedIdentification {
    val descriptor = requireNotNull(TraitCatalogue.descriptorFor(traitId)) { "Unknown trait $traitId" }
    require(descriptor.hasState(stateCode)) { "Trait $traitId has no state $stateCode" }
    val corrected = estimates + (traitId to TraitEstimate.observedState(descriptor, stateCode, settings.traitNoise))
    return CorrectedIdentification(corrected, identifyCultivar(tables, corrected, settings))
}

/** A cultivar's ranking entry plus the per-trait log-likelihoods the explanation needs. */
private class CultivarScore(val match: CultivarMatch, val logLikelihoodByTrait: Map<String, Double>)

/** A cultivar's score before the posterior is normalised; logJoint = ln prior + ln likelihood. */
private class UnnormalisedScore(
    val cultivar: Cultivar,
    val logJoint: Double,
    val logLikelihoodByTrait: Map<String, Double>,
    val fitScore: Double,
)

/**
 * The estimates reasoning uses: those of table traits that say something about the sample.
 * Checks each one first, so a caller bug fails loudly instead of skewing the result.
 */
private fun informativeEstimates(tables: CultivarTables, estimates: Map<String, TraitEstimate>): Map<String, TraitEstimate> {
    for ((traitId, estimate) in estimates) {
        require(traitId == estimate.traitId) { "Estimate for ${estimate.traitId} is filed under $traitId" }
    }
    val coveredEstimates = estimates.filterKeys { it in tables.traitIds }
    for ((traitId, estimate) in coveredEstimates) {
        // The tables only hold catalogue traits (CultivarTables.init), so the descriptor exists.
        val stateCodes = TraitCatalogue.descriptorFor(traitId)!!.stateCodes.toSet()
        require(estimate.probabilities.keys == stateCodes) {
            "Estimate for $traitId has states ${estimate.probabilities.keys}; the descriptor has $stateCodes"
        }
    }
    return coveredEstimates.filterValues { !isUniform(it) }
}

private fun isUniform(estimate: TraitEstimate): Boolean {
    val uniformProbability = 1.0 / estimate.probabilities.size
    return estimate.probabilities.values.all { abs(it - uniformProbability) <= UNIFORM_READING_TOLERANCE }
}

/** Scores every cultivar against [usedEstimates], which [informativeEstimates] has checked and filtered. */
private fun scoreCultivars(tables: CultivarTables, usedEstimates: Map<String, TraitEstimate>): List<CultivarScore> {
    val unnormalised = tables.cultivars.map { cultivar ->
        val logLikelihoodByTrait = usedEstimates.mapValues { (traitId, estimate) ->
            ln(traitLikelihood(tables.stateProbabilities(traitId, cultivar.id), estimate))
        }
        val logLikelihood = logLikelihoodByTrait.values.sum()
        val fitScore = if (usedEstimates.isEmpty()) {
            1.0
        } else {
            val meanScaledLogLikelihood = usedEstimates.keys.sumOf { traitId ->
                val stateCount = tables.stateProbabilities(traitId, cultivar.id).size
                logLikelihoodByTrait.getValue(traitId) + ln(stateCount.toDouble())
            } / usedEstimates.size
            exp(meanScaledLogLikelihood)
        }
        UnnormalisedScore(cultivar, ln(tables.priors.getValue(cultivar.id)) + logLikelihood, logLikelihoodByTrait, fitScore)
    }

    // Log-sum-exp normalisation: subtracting the largest term keeps exp() from underflowing.
    val largestLogJoint = unnormalised.maxOf { it.logJoint }
    val logEvidence = largestLogJoint + ln(unnormalised.sumOf { exp(it.logJoint - largestLogJoint) })

    return unnormalised
        .map { entry ->
            val match = CultivarMatch(
                cultivarId = entry.cultivar.id,
                cultivarName = entry.cultivar.name,
                posterior = exp(entry.logJoint - logEvidence),
                logLikelihood = entry.logLikelihoodByTrait.values.sum(),
                fitScore = entry.fitScore,
            )
            CultivarScore(match, entry.logLikelihoodByTrait)
        }
        // Stable sort: equal posteriors keep the table's order, so results are deterministic.
        .sortedByDescending { it.match.posterior }
}

/** P(reading | cultivar) for one trait: the reading's estimate marginalised over the table row. */
private fun traitLikelihood(row: Map<String, Double>, estimate: TraitEstimate): Double =
    estimate.probabilities.entries.sumOf { (stateCode, probability) ->
        val stateProbability = requireNotNull(row[stateCode]) { "Tables have no state $stateCode for ${estimate.traitId}" }
        stateProbability * probability
    }

private fun explainRanking(top: CultivarScore, compared: CultivarScore): List<TraitInfluence> =
    top.logLikelihoodByTrait
        .map { (traitId, logLikelihood) ->
            TraitInfluence(traitId, logLikelihood - compared.logLikelihoodByTrait.getValue(traitId))
        }
        .sortedByDescending { abs(it.logLikelihoodRatio) }
