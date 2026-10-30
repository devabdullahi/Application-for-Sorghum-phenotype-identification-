package com.sorghum.reasoning

import com.sorghum.traits.PROBABILITY_SUM_TOLERANCE
import com.sorghum.traits.TraitCatalogue
import com.sorghum.traits.TraitEstimate
import com.sorghum.traits.TraitNoiseSettings
import kotlinx.serialization.Serializable
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import kotlin.math.abs

/** The only `cultivars-vN.json` schema this app understands. */
const val SUPPORTED_CULTIVAR_TABLES_SCHEMA_VERSION = 1

/**
 * Port to the bundled cultivar tables (ARCHITECTURE.md section 3.3). Each platform implements
 * it at startup by reading `cultivars-vN.json` from the app bundle; parsing and validation
 * happen in `shared/`, so both platforms accept and refuse the same files.
 */
fun interface CultivarTableSource {
    /**
     * Returns the raw UTF-8 bytes of `cultivars-vN.json`, or null when the file is missing or
     * cannot be read. Null rather than an exception because a Swift implementation cannot
     * throw through a Kotlin interface; [loadCultivarTables] turns null into the startup error.
     */
    fun readCultivarTablesJson(): ByteArray?
}

/** The cultivar tables cannot be used; the app must stop at startup (ARCHITECTURE.md section 4.3). */
class InvalidCultivarTablesException(message: String, cause: Throwable? = null) : Exception(message, cause)

/**
 * Reads and parses the tables from [source]. See [parseCultivarTables].
 *
 * Throws [InvalidCultivarTablesException] when the source has no file, too: missing and invalid
 * tables are the same startup error to the user (ARCHITECTURE.md section 4.3).
 */
@Throws(InvalidCultivarTablesException::class)
fun loadCultivarTables(source: CultivarTableSource, noise: TraitNoiseSettings = TraitNoiseSettings()): CultivarTables {
    val jsonBytes = source.readCultivarTablesJson()
        ?: throw InvalidCultivarTablesException("Cultivar tables file is missing or cannot be read")
    return parseCultivarTables(jsonBytes, noise)
}

/**
 * Parses and validates `cultivars-vN.json`, then applies the noise floor to every row.
 *
 * Schema version 1:
 * ```
 * {
 *   "schemaVersion": 1,
 *   "dataVersion": 3,                      // positive; bumped by model/ with every table change
 *   "attribution": "... Genesys ... CC BY-SA 4.0",
 *   "cultivars": [ {"id": "IS 1234", "name": "Example", "prior": 0.25}, ... ],
 *   "traits": {
 *     "<catalogue trait id>": {
 *       "<cultivar id>": {"<state code>": 0.9, "<state code>": 0.1}
 *     }
 *   }
 * }
 * ```
 * Rows hold raw genebank state frequencies: they may contain zeros and may leave states out
 * (counted as 0), but must sum to 1. The floor is applied here, in one place, rather than
 * trusted from the file. Every listed cultivar needs a row for every trait in the file: a
 * missing row is partial data, and the file is refused rather than the gap filled with a
 * uniform row (ARCHITECTURE.md section 4.3). If `model/` lacks Genesys data for a cultivar's
 * trait, it decides what row to write. ASSUMPTION — confirm both with `model/`.
 *
 * Throws [InvalidCultivarTablesException] on a schema version mismatch, an unknown trait,
 * state or cultivar, a missing row, a blank cultivar id or name, a row or prior set that does
 * not sum to 1, or malformed JSON. Reasoning never runs on partial tables.
 */
@Throws(InvalidCultivarTablesException::class)
fun parseCultivarTables(jsonBytes: ByteArray, noise: TraitNoiseSettings = TraitNoiseSettings()): CultivarTables {
    val document = try {
        tablesJson.decodeFromString<CultivarTablesDocument>(jsonBytes.decodeToString())
    } catch (exception: SerializationException) {
        throw InvalidCultivarTablesException("Cultivar tables do not match schema $SUPPORTED_CULTIVAR_TABLES_SCHEMA_VERSION", exception)
    } catch (exception: IllegalArgumentException) {
        throw InvalidCultivarTablesException("Cultivar tables have an unexpected value", exception)
    }
    return try {
        document.toCultivarTables(noise)
    } catch (exception: IllegalArgumentException) {
        throw InvalidCultivarTablesException("Cultivar tables are invalid: ${exception.message}", exception)
    }
}

// Unknown keys are ignored so model/ can add provenance fields without an app release.
private val tablesJson = Json { ignoreUnknownKeys = true }

private fun CultivarTablesDocument.toCultivarTables(noise: TraitNoiseSettings): CultivarTables {
    fun invalid(reason: String): Nothing = throw InvalidCultivarTablesException(reason)

    if (schemaVersion != SUPPORTED_CULTIVAR_TABLES_SCHEMA_VERSION) {
        invalid("schemaVersion is $schemaVersion; this app reads $SUPPORTED_CULTIVAR_TABLES_SCHEMA_VERSION")
    }
    if (dataVersion < 1) invalid("dataVersion must be positive, was $dataVersion")
    if (attribution.isBlank()) invalid("attribution is required by the Genesys CC BY-SA licence")
    if (traits.isEmpty()) invalid("tables have no traits")

    // Built first so a blank id or name is refused before rows are matched to cultivars.
    val parsedCultivars = cultivars.map { Cultivar(it.id, it.name) }
    val cultivarIds = parsedCultivars.map { it.id }.toSet()
    val stateProbabilitiesByTrait = traits.mapValues { (traitId, rows) ->
        val descriptor = TraitCatalogue.descriptorFor(traitId) ?: invalid("unknown trait $traitId")
        val unknownCultivars = rows.keys - cultivarIds
        if (unknownCultivars.isNotEmpty()) invalid("trait $traitId has rows for unlisted cultivars $unknownCultivars")

        cultivarIds.associateWith { cultivarId ->
            val rawRow = rows[cultivarId] ?: invalid("trait $traitId has no row for cultivar $cultivarId")
            val unknownStates = rawRow.keys.filterNot { descriptor.hasState(it) }
            if (unknownStates.isNotEmpty()) invalid("row $traitId/$cultivarId has unknown state codes $unknownStates")
            val total = rawRow.values.sum()
            if (abs(total - 1.0) > PROBABILITY_SUM_TOLERANCE) invalid("row $traitId/$cultivarId sums to $total, not 1")
            // Same floor rule as trait readings, so a table zero cannot veto a cultivar.
            TraitEstimate.withNoiseFloor(descriptor, rawRow, noise).probabilities
        }
    }

    return CultivarTables(
        schemaVersion = schemaVersion,
        dataVersion = dataVersion,
        attribution = attribution,
        cultivars = parsedCultivars,
        priors = cultivars.associate { it.id to it.prior },
        stateProbabilitiesByTrait = stateProbabilitiesByTrait,
    )
}

// Wire format of cultivars-vN.json; mapped to CultivarTables after validation.

@Serializable
private class CultivarTablesDocument(
    val schemaVersion: Int,
    val dataVersion: Int,
    val attribution: String,
    val cultivars: List<CultivarDocument>,
    val traits: Map<String, Map<String, Map<String, Double>>>,
)

@Serializable
private class CultivarDocument(val id: String, val name: String, val prior: Double)
