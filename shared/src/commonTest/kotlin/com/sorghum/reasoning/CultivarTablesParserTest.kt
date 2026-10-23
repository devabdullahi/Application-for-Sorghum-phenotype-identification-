package com.sorghum.reasoning

import com.sorghum.traits.TraitCatalogue
import kotlin.math.abs
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/** `cultivars-vN.json` must parse exactly, or the app stops at startup (ARCHITECTURE.md section 4.3). */
class CultivarTablesParserTest {

    @Test
    fun `parses versions attribution cultivars and priors`() {
        val tables = testTables()

        assertEquals(1, tables.schemaVersion)
        assertEquals(3, tables.dataVersion)
        assertTrue("CC BY-SA" in tables.attribution)
        assertEquals(listOf("alpha", "beta", "gamma", "delta"), tables.cultivars.map { it.id })
        assertEquals(0.25, tables.priors.getValue("gamma"))
    }

    @Test
    fun `applies the noise floor to every table row`() {
        val row = testTables().stateProbabilities(MIDRIB, "gamma")

        assertClose(0.01, row.getValue("2"))
        assertClose(1.0 - 5 * 0.01, row.getValue("1"))
        assertEquals(TraitCatalogue.MIDRIB_COLOUR.stateCodes.toSet(), row.keys)
    }

    @Test
    fun `a cultivar without a row for a trait gets a uniform row`() {
        val tables = parseCultivarTables(
            testTablesJson(gammaMidribRow = "null").replace(""""gamma": null,""", "").encodeToByteArray(),
            testNoise,
        )

        val row = tables.stateProbabilities(MIDRIB, "gamma")

        row.values.forEach { assertClose(1.0 / 6, it) }
    }

    @Test
    fun `accepts a row that sums to one within the tolerance`() {
        parseCultivarTables(testTablesJson(gammaMidribRow = """{"1": 0.6, "2": 0.4000005}""").encodeToByteArray(), testNoise)
    }

    @Test
    fun `refuses a row that does not sum to one`() {
        assertInvalid(testTablesJson(gammaMidribRow = """{"1": 0.6, "2": 0.3}"""))
        assertInvalid(testTablesJson(gammaMidribRow = """{"1": 0.6, "2": 0.400002}"""))
    }

    @Test
    fun `refuses a negative table probability`() {
        assertInvalid(testTablesJson(gammaMidribRow = """{"1": 1.1, "2": -0.1}"""))
    }

    @Test
    fun `refuses another schema version`() {
        assertInvalid(testTablesJson(schemaVersion = 2))
    }

    @Test
    fun `refuses a trait the catalogue does not have`() {
        assertInvalid(testTablesJson(midribTraitId = "leafHairiness"))
    }

    @Test
    fun `refuses a state code the trait does not have`() {
        assertInvalid(testTablesJson(gammaMidribRow = """{"9": 1.0}"""))
    }

    @Test
    fun `refuses a row for a cultivar that is not listed`() {
        assertInvalid(testTablesJson(extraLustreRow = """"omega": {"+": 1.0},"""))
    }

    @Test
    fun `refuses duplicate cultivar ids`() {
        assertInvalid(testTablesJson(secondCultivarId = "alpha"))
    }

    @Test
    fun `refuses priors that do not sum to one`() {
        assertInvalid(testTablesJson(alphaPrior = "0.3"))
    }

    @Test
    fun `refuses a zero prior`() {
        assertInvalid(testTablesJson(alphaPrior = "0.0"))
    }

    @Test
    fun `refuses a missing attribution`() {
        assertInvalid(testTablesJson(attribution = " "))
    }

    @Test
    fun `refuses malformed json`() {
        assertInvalid("""{"schemaVersion": 1""")
    }

    @Test
    fun `loads through the table source port`() {
        val source = CultivarTableSource { testTablesJson().encodeToByteArray() }

        assertEquals(4, loadCultivarTables(source).cultivars.size)
    }

    private fun assertInvalid(json: String) {
        assertFailsWith<InvalidCultivarTablesException> { parseCultivarTables(json.encodeToByteArray(), testNoise) }
    }

    private fun assertClose(expected: Double, actual: Double) {
        assertTrue(abs(expected - actual) < 1e-9, "expected $expected, was $actual")
    }
}
