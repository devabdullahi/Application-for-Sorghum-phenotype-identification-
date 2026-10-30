package com.sorghum.species

import kotlin.math.ln
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue

class BasicRaceTest {
    private val races = listOf("Bicolor", "Caudatum", "Durra", "Guinea", "Kafir")

    private fun head(groupProbabilityMass: Double = 0.89, maxGroupSize: Int = 2, temperature: Double = 1.0) =
        BasicRaceHead(
            outputIndex = 1,
            races = races,
            temperature = temperature,
            groupProbabilityMass = groupProbabilityMass,
            maxGroupSize = maxGroupSize,
            isExperimental = true,
            meetsAccuracyGoal = false,
        )

    /** Logits whose softmax (temperature 1) is exactly [probabilities]. */
    private fun logitsOf(vararg probabilities: Double) = FloatArray(probabilities.size) { ln(probabilities[it]).toFloat() }

    // Answer rule: group mass boundary (0.89), at, just below and just above.

    @Test
    fun `a top race exactly at the group mass is answered alone`() {
        assertEquals(listOf(2), basicRaceGroup(doubleArrayOf(0.04, 0.03, 0.89, 0.02, 0.02), head()))
    }

    @Test
    fun `a top race just below the group mass needs a second race`() {
        assertEquals(listOf(2, 0), basicRaceGroup(doubleArrayOf(0.081, 0.01, 0.889, 0.01, 0.01), head()))
    }

    @Test
    fun `a top race just above the group mass is answered alone`() {
        assertEquals(listOf(2), basicRaceGroup(doubleArrayOf(0.039, 0.03, 0.891, 0.02, 0.02), head()))
    }

    // Answer rule: max group size boundary (2), at and above.

    @Test
    fun `two races reaching the mass are answered as a pair`() {
        assertEquals(listOf(1, 2), basicRaceGroup(doubleArrayOf(0.05, 0.5, 0.39, 0.03, 0.03), head()))
    }

    @Test
    fun `needing three races is unrecognized`() {
        assertNull(basicRaceGroup(doubleArrayOf(0.12, 0.45, 0.33, 0.05, 0.05), head()))
    }

    @Test
    fun `a larger max group size answers the same probabilities with three races`() {
        assertEquals(listOf(1, 2, 0), basicRaceGroup(doubleArrayOf(0.12, 0.45, 0.33, 0.05, 0.05), head(maxGroupSize = 3)))
    }

    @Test
    fun `tied races go to the earlier race first`() {
        assertEquals(listOf(1, 3), basicRaceGroup(doubleArrayOf(0.02, 0.45, 0.06, 0.45, 0.02), head()))
    }

    @Test
    fun `float rounding in the summed mass does not grow the group`() {
        val group = basicRaceGroup(doubleArrayOf(0.3, 0.3, 0.3, 0.05, 0.05), head(groupProbabilityMass = 0.9, maxGroupSize = 3))

        assertEquals(listOf(0, 1, 2), group)
    }

    // readBasicRace

    @Test
    fun `reads the head's output and returns calibrated probabilities with the answer`() {
        val reading = readBasicRace(listOf(FloatArray(9), logitsOf(0.05, 0.6, 0.31, 0.02, 0.02)), head())

        reading as BasicRaceReading.Answered
        assertEquals(listOf("Caudatum", "Durra"), reading.races)
        assertEquals(0.6f, reading.probabilityByRace.getValue("Caudatum"), 1e-6f)
        assertEquals(races, reading.probabilityByRace.keys.toList())
        assertTrue(reading.isExperimental)
    }

    @Test
    fun `an answer needing too many races is unrecognized and keeps the probabilities`() {
        val reading = readBasicRace(listOf(FloatArray(9), logitsOf(0.12, 0.45, 0.33, 0.05, 0.05)), head())

        reading as BasicRaceReading.Unrecognized
        assertEquals(0.45f, reading.probabilityByRace.getValue("Caudatum"), 1e-6f)
        assertTrue(reading.isExperimental)
    }

    @Test
    fun `temperature flattens the probabilities before the rule`() {
        // At T = 1 Durra alone holds 0.9; at T = 2 it no longer reaches 0.89.
        val logits = logitsOf(0.04, 0.03, 0.9, 0.02, 0.01)

        assertTrue(readBasicRace(listOf(FloatArray(9), logits), head()) is BasicRaceReading.Answered)
        val flattened = readBasicRace(listOf(FloatArray(9), logits), head(temperature = 2.0)) as BasicRaceReading.Unrecognized
        assertEquals(basicRaceProbabilities(logits, 2.0)[2].toFloat(), flattened.probabilityByRace.getValue("Durra"))
    }

    @Test
    fun `a missing output is unavailable`() {
        assertEquals(
            BasicRaceReading.Unavailable(BasicRaceUnavailableReason.MISSING_OUTPUT),
            readBasicRace(listOf(FloatArray(9)), head()),
        )
    }

    @Test
    fun `an output with the wrong logit count is unavailable`() {
        assertEquals(
            BasicRaceReading.Unavailable(BasicRaceUnavailableReason.WRONG_LOGIT_COUNT),
            readBasicRace(listOf(FloatArray(9), FloatArray(4)), head()),
        )
    }

    @Test
    fun `a non-finite logit is unavailable`() {
        assertEquals(
            BasicRaceReading.Unavailable(BasicRaceUnavailableReason.NON_FINITE_LOGITS),
            readBasicRace(listOf(FloatArray(9), floatArrayOf(0f, Float.NaN, 0f, 0f, 0f)), head()),
        )
    }

    // Metadata

    @Test
    fun `parses the basic race head model export writes`() {
        val head = parseModelMetadata(metadataJson(extraHeads = basicRaceHeadJson())).basicRace

        assertEquals(
            BasicRaceHead(
                outputIndex = 1, races = races, temperature = 1.385, groupProbabilityMass = 0.89, maxGroupSize = 2,
                isExperimental = true, meetsAccuracyGoal = false,
            ),
            head,
        )
    }

    @Test
    fun `metadata without a basic race head has none`() {
        assertNull(parseModelMetadata(metadataJson()).basicRace)
    }

    @Test
    fun `heads this app does not know are ignored`() {
        val metadata = parseModelMetadata(metadataJson(extraHeads = """, "leafShape": {"outputIndex": 2, "whatever": true}"""))

        assertNull(metadata.basicRace)
    }

    @Test
    fun `refuses an invalid basic race head`() {
        val invalidHeads = listOf(
            basicRaceHeadJson(groupProbabilityMass = 0.49),
            basicRaceHeadJson(groupProbabilityMass = 1.0),
            basicRaceHeadJson(maxGroupSize = 0),
            basicRaceHeadJson(maxGroupSize = 6),
            basicRaceHeadJson(temperature = 0.0),
            basicRaceHeadJson(outputIndex = 0),
            basicRaceHeadJson(outputIndex = -1),
            basicRaceHeadJson(races = """["Durra", "Durra"]"""),
            basicRaceHeadJson(races = "[]"),
            basicRaceHeadJson(output = "probabilities"),
        )
        for (json in invalidHeads) {
            assertFailsWith<InvalidModelMetadataException>(json) { parseModelMetadata(metadataJson(extraHeads = json)) }
        }
    }

    @Test
    fun `accepts the group mass range ends that are allowed`() {
        val lowestMass = parseModelMetadata(metadataJson(extraHeads = basicRaceHeadJson(groupProbabilityMass = 0.5)))
        val largestGroup = parseModelMetadata(metadataJson(extraHeads = basicRaceHeadJson(maxGroupSize = 5)))

        assertEquals(0.5, lowestMass.basicRace?.groupProbabilityMass)
        assertEquals(5, largestGroup.basicRace?.maxGroupSize)
    }

    @Test
    fun `refuses an output that misses its goal without the experimental mark`() {
        assertFailsWith<InvalidModelMetadataException> {
            parseModelMetadata(metadataJson(extraHeads = basicRaceHeadJson(experimental = false)))
        }
    }

    @Test
    fun `an invalid basic race head fails the species gate load instead of crashing`() {
        val load = loadSpeciesGate(metadataJson(extraHeads = basicRaceHeadJson(maxGroupSize = 0)), model = { emptyList() })

        assertTrue((load as SpeciesGateLoad.Failed).reason.contains(BASIC_RACE_HEAD_ID))
    }

    private fun basicRaceHeadJson(
        outputIndex: Int = 1,
        output: String = "logits",
        races: String = """["Bicolor", "Caudatum", "Durra", "Guinea", "Kafir"]""",
        temperature: Double = 1.385,
        groupProbabilityMass: Double = 0.89,
        maxGroupSize: Int = 2,
        experimental: Boolean = true,
    ) = """,
    "basicRace": {
      "answerRule": {"groupProbabilityMass": $groupProbabilityMass, "maxGroupSize": $maxGroupSize},
      "evaluation": {"testInt8": {"coverage": 0.793}},
      "experimental": $experimental,
      "meetsAccuracyGoal": false,
      "output": "$output",
      "outputIndex": $outputIndex,
      "races": $races,
      "status": "EXPERIMENTAL",
      "temperature": $temperature
    }"""
}
