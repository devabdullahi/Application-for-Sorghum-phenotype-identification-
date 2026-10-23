package com.sorghum.traits

import kotlin.math.abs

/** How far the probabilities of one distribution may sum from 1 (CLAUDE.md, Parity). */
const val PROBABILITY_SUM_TOLERANCE = 1e-6

/**
 * Smallest allowed [TraitNoiseSettings.minStateProbability]. A floor below the 1e-6
 * probability tolerance is lost in rounding, and its log (about -14 at 1e-6, -690 near the
 * smallest double) would let one misread trait outweigh every other trait: a veto in all but
 * name.
 */
const val MIN_STATE_PROBABILITY_FLOOR = 1e-6

/**
 * Largest allowed [TraitNoiseSettings.minStateProbability]. Above it a trait with many states
 * (panicle shape has 13) would give most of its mass to noise and say little about the photo.
 */
const val MAX_STATE_PROBABILITY_FLOOR = 0.05

/**
 * The noise floor applied to every trait estimate (and every cultivar table row), so one
 * misread trait cannot veto the true cultivar (CLAUDE.md, "No hard zeros").
 *
 * @param minStateProbability the least probability any state keeps, whatever was read. It
 *   models "the reading was wrong and the true state could be anything". 0.01 is an initial
 *   guess, tune on real photos: with six states it says about 6% of readings may be wrong.
 */
data class TraitNoiseSettings(
    val minStateProbability: Double = 0.01,
) {
    init {
        require(minStateProbability >= MIN_STATE_PROBABILITY_FLOOR && minStateProbability <= MAX_STATE_PROBABILITY_FLOOR) {
            "minStateProbability must be within [$MIN_STATE_PROBABILITY_FLOOR, $MAX_STATE_PROBABILITY_FLOOR], was $minStateProbability"
        }
    }
}

/**
 * What the app believes about one trait: a probability for each descriptor state.
 *
 * A trait never reports a bare state. Every probability is above zero and they sum to 1
 * within [PROBABILITY_SUM_TOLERANCE]; the constructor enforces this.
 *
 * The public constructor is for data that is already floored and complete, such as a parity
 * fixture or an estimate restored from storage. It checks positivity and the sum, but not the
 * noise floor or that every descriptor state is present (reasoning refuses an estimate whose
 * states differ from the descriptor's). Readers must build estimates with [withNoiseFloor] (or
 * [ContinuousTraitEstimate.toTraitEstimate]), which fills in every state and applies the floor.
 *
 * @param traitId the [TraitDescriptor.id] this estimate is for.
 * @param probabilities probability by descriptor state code.
 */
data class TraitEstimate(
    val traitId: String,
    val probabilities: Map<String, Double>,
) {
    init {
        require(probabilities.isNotEmpty()) { "Estimate for $traitId has no states" }
        require(probabilities.values.all { it > 0.0 && it.isFinite() }) {
            "Every state of $traitId needs a positive probability, were $probabilities"
        }
        val total = probabilities.values.sum()
        require(abs(total - 1.0) <= PROBABILITY_SUM_TOLERANCE) { "Probabilities of $traitId sum to $total, not 1" }
    }

    /** The probability of [stateCode]. Throws if this estimate has no such state. */
    fun probabilityOf(stateCode: String): Double =
        requireNotNull(probabilities[stateCode]) { "Estimate for $traitId has no state $stateCode" }

    companion object {
        /**
         * Builds an estimate for [descriptor] from a reader's raw output and applies the noise
         * floor.
         *
         * Raw values are first normalised to sum to 1; states missing from [rawProbabilities]
         * count as 0. The floor then mixes in uniform noise: p' = p * (1 - k * floor) + floor
         * for k states. Unlike clamping and renormalising, this leaves every state at least
         * at the floor, keeps the order of the raw probabilities and sums to 1 exactly.
         *
         * @param rawProbabilities non-negative scores by state code, not all zero.
         */
        fun withNoiseFloor(
            descriptor: TraitDescriptor,
            rawProbabilities: Map<String, Double>,
            settings: TraitNoiseSettings,
        ): TraitEstimate {
            val unknownCodes = rawProbabilities.keys.filterNot { descriptor.hasState(it) }
            require(unknownCodes.isEmpty()) { "Trait ${descriptor.id} has no states $unknownCodes" }
            require(rawProbabilities.values.all { it >= 0.0 && it.isFinite() }) {
                "Raw probabilities of ${descriptor.id} must be finite and not negative, were $rawProbabilities"
            }
            val rawTotal = rawProbabilities.values.sum()
            require(rawTotal > 0.0) { "Raw probabilities of ${descriptor.id} are all zero" }

            val stateCount = descriptor.states.size
            val noiseMass = stateCount * settings.minStateProbability
            require(noiseMass < 1.0) {
                "A floor of ${settings.minStateProbability} over $stateCount states of ${descriptor.id} leaves no mass for the reading"
            }
            val probabilities = descriptor.stateCodes.associateWith { code ->
                val normalised = (rawProbabilities[code] ?: 0.0) / rawTotal
                normalised * (1.0 - noiseMass) + settings.minStateProbability
            }
            return TraitEstimate(descriptor.id, probabilities)
        }

        /**
         * A near-certain estimate that [stateCode] is the true state, for a trait the user
         * corrected. The floor still applies, so even a wrong correction cannot zero out a
         * cultivar.
         */
        fun observedState(descriptor: TraitDescriptor, stateCode: String, settings: TraitNoiseSettings): TraitEstimate =
            withNoiseFloor(descriptor, mapOf(stateCode to 1.0), settings)
    }
}
