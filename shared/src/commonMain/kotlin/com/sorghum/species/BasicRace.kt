package com.sorghum.species

import kotlin.math.exp

/** Why the basic-race output could not be read for a photo. */
enum class BasicRaceUnavailableReason {
    /** The model returned no output at the head's index, e.g. after an interpreter error. */
    MISSING_OUTPUT,

    /** The output has a different number of logits than the head has races. */
    WRONG_LOGIT_COUNT,

    /** A logit is NaN or infinite, so no probability can be computed from it. */
    NON_FINITE_LOGITS,
}

/**
 * The experimental basic-race output for one photo (basic-race-v1 in traits-v3, #45).
 *
 * This is a hint over the five basic races (Bicolor, Caudatum, Durra, Guinea, Kafir). It does
 * not meet the 89% race goal (ADR-0011, `model/README.md` "Basic-race locked evaluation").
 * It is never a cultivar result, never gates the pipeline and never counts as a pass. While
 * `isExperimental` is true, a UI that shows it must label it experimental.
 */
sealed interface BasicRaceReading {
    /**
     * The fewest most likely races whose probabilities reach the head's group mass, most
     * likely first (one or two races with basic-race-v1).
     *
     * @param probabilityByRace calibrated probability of every race, in output order.
     */
    data class Answered(
        val races: List<String>,
        val probabilityByRace: Map<String, Float>,
        val isExperimental: Boolean,
    ) : BasicRaceReading

    /**
     * No group small enough reaches the group mass. This is an answer ("unrecognized"), not
     * an error.
     */
    data class Unrecognized(
        val probabilityByRace: Map<String, Float>,
        val isExperimental: Boolean,
    ) : BasicRaceReading

    /** The output could not be read, for [reason]. Says nothing about the race. */
    data class Unavailable(val reason: BasicRaceUnavailableReason) : BasicRaceReading
}

// Float sums of probabilities fall short of exact values (0.3 + 0.3 + 0.3 < 0.9), which would
// grow a group by a race it does not need. Same value as model/ race_evaluation.py.
private const val PROBABILITY_SUM_TOLERANCE = 1e-9

/**
 * Reads the basic-race head from the model's [outputs] (all of them, by output index, as
 * [ImageModel.run] returns them). Pure. Never throws: an output that does not fit [head] gives
 * [BasicRaceReading.Unavailable].
 *
 * Takes the outputs of the same model call the species gate used, so a photo runs the model once.
 */
fun readBasicRace(outputs: List<FloatArray>, head: BasicRaceHead): BasicRaceReading {
    val logits = outputs.getOrNull(head.outputIndex)
        ?: return BasicRaceReading.Unavailable(BasicRaceUnavailableReason.MISSING_OUTPUT)
    if (logits.size != head.races.size) return BasicRaceReading.Unavailable(BasicRaceUnavailableReason.WRONG_LOGIT_COUNT)
    if (logits.any { !it.isFinite() }) return BasicRaceReading.Unavailable(BasicRaceUnavailableReason.NON_FINITE_LOGITS)

    val probabilities = basicRaceProbabilities(logits, head.temperature)
    val probabilityByRace = head.races.indices.associate { head.races[it] to probabilities[it].toFloat() }
    val group = basicRaceGroup(probabilities, head)
        ?: return BasicRaceReading.Unrecognized(probabilityByRace, head.isExperimental)
    return BasicRaceReading.Answered(group.map { head.races[it] }, probabilityByRace, head.isExperimental)
}

/** Calibrated race probabilities: softmax(logits / temperature), computed stably in Double. */
internal fun basicRaceProbabilities(logits: FloatArray, temperature: Double): DoubleArray {
    val scaled = DoubleArray(logits.size) { logits[it] / temperature }
    val largest = scaled.max()
    val exponentials = DoubleArray(scaled.size) { exp(scaled[it] - largest) }
    val total = exponentials.sum()
    return DoubleArray(exponentials.size) { exponentials[it] / total }
}

/**
 * The answer rule of `model/` `race_evaluation.returned_group`: race indices of the fewest most
 * likely races whose summed probability reaches the group mass, most likely first, or null
 * ("unrecognized") when that takes more than `maxGroupSize` races. Ties go to the earlier race.
 */
internal fun basicRaceGroup(probabilities: DoubleArray, head: BasicRaceHead): List<Int>? {
    val order = probabilities.indices.sortedWith(compareByDescending<Int> { probabilities[it] }.thenBy { it })
    val group = mutableListOf<Int>()
    var mass = 0.0
    for (index in order) {
        group += index
        mass += probabilities[index]
        if (mass >= head.groupProbabilityMass - PROBABILITY_SUM_TOLERANCE) break
    }
    return if (group.size > head.maxGroupSize) null else group
}
