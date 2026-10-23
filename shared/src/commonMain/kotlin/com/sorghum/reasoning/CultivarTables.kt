package com.sorghum.reasoning

import com.sorghum.traits.PROBABILITY_SUM_TOLERANCE
import kotlin.math.abs

/** A cultivar the app can identify; one row of `cultivars-vN.json`. */
data class Cultivar(val id: String, val name: String)

/**
 * The naive Bayes tables reasoning runs on: P(state | cultivar) per trait, plus priors.
 *
 * Build it with [parseCultivarTables], which applies the noise floor to every row. The
 * constructor re-checks the invariants reasoning relies on, so a table with a zero or a row
 * that does not sum to 1 cannot exist.
 *
 * @param schemaVersion version of the JSON layout; see [SUPPORTED_CULTIVAR_TABLES_SCHEMA_VERSION].
 * @param dataVersion version of the table contents; shown in the result details.
 * @param attribution the Genesys CC BY-SA attribution, which the licence requires the app to show.
 * @param cultivars every cultivar, in file order. Ties in the ranking keep this order.
 * @param priors prior probability by cultivar id; all positive, summing to 1.
 * @param stateProbabilitiesByTrait trait id -> cultivar id -> state code -> P(state | cultivar).
 *   Every cultivar has a row for every trait, and every row covers all of the trait's states.
 */
data class CultivarTables(
    val schemaVersion: Int,
    val dataVersion: Int,
    val attribution: String,
    val cultivars: List<Cultivar>,
    val priors: Map<String, Double>,
    val stateProbabilitiesByTrait: Map<String, Map<String, Map<String, Double>>>,
) {
    init {
        require(cultivars.isNotEmpty()) { "Tables list no cultivars" }
        val cultivarIds = cultivars.map { it.id }
        require(cultivarIds.toSet().size == cultivarIds.size) { "Cultivar ids are not unique: $cultivarIds" }
        require(priors.keys == cultivarIds.toSet()) { "Priors must cover exactly the listed cultivars" }
        requireDistribution(priors.values, "Priors")
        for ((traitId, rows) in stateProbabilitiesByTrait) {
            require(rows.keys == cultivarIds.toSet()) { "Trait $traitId must have one row per listed cultivar" }
            rows.forEach { (cultivarId, row) -> requireDistribution(row.values, "Row $traitId/$cultivarId") }
        }
    }

    /** Ids of the traits these tables can reason with. */
    val traitIds: Set<String> get() = stateProbabilitiesByTrait.keys

    /** P(state | cultivar) for [traitId], by state code. Throws if the tables lack either id. */
    fun stateProbabilities(traitId: String, cultivarId: String): Map<String, Double> {
        val rows = requireNotNull(stateProbabilitiesByTrait[traitId]) { "Tables have no trait $traitId" }
        return requireNotNull(rows[cultivarId]) { "Tables have no cultivar $cultivarId" }
    }
}

private fun requireDistribution(probabilities: Collection<Double>, name: String) {
    require(probabilities.all { it > 0.0 && it.isFinite() }) { "$name must all be positive, were $probabilities" }
    val total = probabilities.sum()
    require(abs(total - 1.0) <= PROBABILITY_SUM_TOLERANCE) { "$name sum to $total, not 1" }
}
