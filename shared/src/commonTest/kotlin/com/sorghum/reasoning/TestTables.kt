package com.sorghum.reasoning

import com.sorghum.traits.TraitCatalogue
import com.sorghum.traits.TraitEstimate
import com.sorghum.traits.TraitNoiseSettings

/**
 * A tiny hand-written table in the `cultivars-v1.json` shape. Raw rows hold hard zeros on
 * purpose, so tests can show the parser's noise floor removes them.
 *
 * Profiles (midrib colour, grain lustre, glume colour):
 * - alpha and beta: dull green (2), lustrous (+), red (4). Same profile, so they form a group.
 * - gamma: white (1), not lustrous (0), black (6).
 * - delta: yellow (3), not lustrous (0), mostly purple (5) but sometimes black (6).
 */
internal fun testTablesJson(
    schemaVersion: Int = 1,
    attribution: String = "Contains Genesys data (ICRISAT characterization), CC BY-SA 4.0",
    alphaPrior: String = "0.25",
    otherPriors: List<String> = listOf("0.25", "0.25", "0.25"),
    midribTraitId: String = TraitCatalogue.MIDRIB_COLOUR.id,
    gammaMidribRow: String = """{"1": 1.0}""",
    extraLustreRow: String = "",
    secondCultivarId: String = "beta",
    secondCultivarName: String = "Beta",
): String = """
{
  "schemaVersion": $schemaVersion,
  "dataVersion": 3,
  "attribution": "$attribution",
  "cultivars": [
    {"id": "alpha", "name": "Alpha", "prior": $alphaPrior},
    {"id": "$secondCultivarId", "name": "$secondCultivarName", "prior": ${otherPriors[0]}},
    {"id": "gamma", "name": "Gamma", "prior": ${otherPriors[1]}},
    {"id": "delta", "name": "Delta", "prior": ${otherPriors[2]}}
  ],
  "traits": {
    "$midribTraitId": {
      "alpha": {"2": 1.0},
      "beta": {"2": 1.0},
      "gamma": $gammaMidribRow,
      "delta": {"3": 1.0}
    },
    "grainLustre": {
      $extraLustreRow
      "alpha": {"+": 1.0},
      "beta": {"+": 1.0},
      "gamma": {"0": 1.0},
      "delta": {"0": 1.0}
    },
    "glumeColour": {
      "alpha": {"4": 1.0},
      "beta": {"4": 1.0},
      "gamma": {"6": 1.0},
      "delta": {"5": 0.8, "6": 0.2}
    }
  }
}
"""

/**
 * Tables that hold one cultivar, "solo": white midrib (1), lustrous grain (+). With a single
 * cultivar the group always has one member, so these show when the outcome must not be
 * [IdentificationOutcome.SINGLE_MATCH].
 */
internal fun singleCultivarTables(): CultivarTables = parseCultivarTables(
    """
    {
      "schemaVersion": 1,
      "dataVersion": 1,
      "attribution": "Contains Genesys data (ICRISAT characterization), CC BY-SA 4.0",
      "cultivars": [ {"id": "solo", "name": "Solo", "prior": 1.0} ],
      "traits": {
        "midribColour": { "solo": {"1": 1.0} },
        "grainLustre": { "solo": {"+": 1.0} }
      }
    }
    """.encodeToByteArray(),
    testNoise,
)

/** The floor every test uses for tables and estimates. */
internal val testNoise = TraitNoiseSettings(minStateProbability = 0.01)

/** The parsed test table. */
internal fun testTables(): CultivarTables = parseCultivarTables(testTablesJson().encodeToByteArray(), testNoise)

/** A near-certain reading of each given trait state, keyed by trait id. */
internal fun observed(vararg traitStates: Pair<String, String>): Map<String, TraitEstimate> =
    traitStates.associate { (traitId, stateCode) ->
        traitId to TraitEstimate.observedState(TraitCatalogue.descriptorFor(traitId)!!, stateCode, testNoise)
    }

internal val MIDRIB = TraitCatalogue.MIDRIB_COLOUR.id
internal val LUSTRE = TraitCatalogue.GRAIN_LUSTRE.id
internal val GLUME = TraitCatalogue.GLUME_COLOUR.id
