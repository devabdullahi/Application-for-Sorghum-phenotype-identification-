package com.sorghum.reasoning

import com.sorghum.traits.TraitCatalogue
import kotlin.test.Test
import kotlin.test.assertFailsWith

/** [CultivarTables] refuses tables reasoning could not use, however they were built. */
class CultivarTablesTest {

    private val cultivars = listOf(Cultivar("alpha", "Alpha"), Cultivar("beta", "Beta"))
    private val priors = mapOf("alpha" to 0.5, "beta" to 0.5)
    private val lustreRow = mapOf("0" to 0.5, "+" to 0.5)

    @Test
    fun `accepts rows that cover exactly the descriptor's states`() {
        tablesWithLustreRows(lustreRow, lustreRow)
    }

    @Test
    fun `refuses a row that leaves out one of the descriptor's states`() {
        assertFailsWith<IllegalArgumentException> { tablesWithLustreRows(lustreRow, mapOf("+" to 1.0)) }
    }

    @Test
    fun `refuses a row with a state the descriptor does not have`() {
        assertFailsWith<IllegalArgumentException> {
            tablesWithLustreRows(lustreRow, mapOf("0" to 0.4, "+" to 0.4, "9" to 0.2))
        }
    }

    @Test
    fun `refuses a trait the catalogue does not have`() {
        assertFailsWith<IllegalArgumentException> {
            tables(mapOf("leafHairiness" to mapOf("alpha" to lustreRow, "beta" to lustreRow)))
        }
    }

    @Test
    fun `refuses a blank cultivar id or name`() {
        assertFailsWith<IllegalArgumentException> { Cultivar(" ", "Alpha") }
        assertFailsWith<IllegalArgumentException> { Cultivar("alpha", "") }
    }

    private fun tablesWithLustreRows(alphaRow: Map<String, Double>, betaRow: Map<String, Double>): CultivarTables =
        tables(mapOf(TraitCatalogue.GRAIN_LUSTRE.id to mapOf("alpha" to alphaRow, "beta" to betaRow)))

    private fun tables(stateProbabilitiesByTrait: Map<String, Map<String, Map<String, Double>>>): CultivarTables =
        CultivarTables(
            schemaVersion = SUPPORTED_CULTIVAR_TABLES_SCHEMA_VERSION,
            dataVersion = 1,
            attribution = "Contains Genesys data, CC BY-SA 4.0",
            cultivars = cultivars,
            priors = priors,
            stateProbabilitiesByTrait = stateProbabilitiesByTrait,
        )
}
