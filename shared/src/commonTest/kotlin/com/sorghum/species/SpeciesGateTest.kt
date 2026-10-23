package com.sorghum.species

import com.sorghum.imaging.Rgb
import com.sorghum.imaging.uniformImage
import kotlin.math.ln
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** Class order in [DEFAULT_CLASSES]: sorghum, johnson grass, maize, other plant, no plant. */
class SpeciesGateTest {

    private val metadata = parseModelMetadata(metadataJson(temperature = 1f, sorghumThreshold = 0.8f))
    private val settings = SpeciesSettings(minNotSorghumProbability = 0.7f, minNamedLookAlikeProbability = 0.6f, minNoPlantProbability = 0.6f)

    @Test
    fun `sorghum at the threshold continues`() {
        assertEquals(SpeciesCheck.Sorghum(0.8f), decide(0.8f, 0.05f, 0.05f, 0.05f, 0.05f))
    }

    @Test
    fun `sorghum just above the threshold continues`() {
        assertEquals(SpeciesCheck.Sorghum(0.81f), decide(0.81f, 0.04f, 0.05f, 0.05f, 0.05f))
    }

    @Test
    fun `sorghum just below the threshold is unsure`() {
        val check = decide(0.79f, 0.06f, 0.05f, 0.05f, 0.05f)

        assertTrue(check is SpeciesCheck.Unsure)
    }

    @Test
    fun `confident look-alike is named`() {
        val check = decide(0.1f, 0.05f, 0.75f, 0.05f, 0.05f)

        assertEquals("maize", (check as SpeciesCheck.NotSorghum).lookAlikeClassId)
    }

    @Test
    fun `look-alike exactly at the naming level is named`() {
        val check = decide(0.1f, 0.2f, 0.6f, 0.05f, 0.05f)

        assertEquals("maize", (check as SpeciesCheck.NotSorghum).lookAlikeClassId)
    }

    @Test
    fun `look-alike just below the naming level is not named`() {
        val check = decide(0.1f, 0.25f, 0.55f, 0.05f, 0.05f)

        assertEquals(null, (check as SpeciesCheck.NotSorghum).lookAlikeClassId)
    }

    @Test
    fun `not sorghum exactly at the confidence level is said`() {
        // 1 - P(sorghum) = 0.7, the minimum; maize at 0.5 is too unsure to be named.
        val check = decide(0.3f, 0.0f, 0.5f, 0.1f, 0.1f)

        assertEquals(SpeciesCheck.NotSorghum(lookAlikeClassId = null, sorghumProbability = 0.3f), check)
    }

    @Test
    fun `not sorghum is only said when confident`() {
        // Top class is maize, but 1 - P(sorghum) = 0.65 < 0.7: ask for a retake instead.
        val check = decide(0.35f, 0.0f, 0.45f, 0.1f, 0.1f)

        assertTrue(check is SpeciesCheck.Unsure)
    }

    @Test
    fun `other plant is not sorghum without a name`() {
        val check = decide(0.05f, 0.05f, 0.05f, 0.8f, 0.05f)

        assertEquals(SpeciesCheck.NotSorghum(lookAlikeClassId = null, sorghumProbability = 0.05f), check)
    }

    @Test
    fun `confident empty board is no plant`() {
        assertEquals(SpeciesCheck.NoPlant, decide(0.05f, 0.05f, 0.05f, 0.05f, 0.8f))
    }

    @Test
    fun `empty board exactly at the no-plant level is no plant`() {
        assertEquals(SpeciesCheck.NoPlant, decide(0.1f, 0.1f, 0.1f, 0.1f, 0.6f))
    }

    @Test
    fun `doubtful empty board is unsure`() {
        assertTrue(decide(0.15f, 0.1f, 0.1f, 0.1f, 0.55f) is SpeciesCheck.Unsure)
    }

    @Test
    fun `temperature softens the probabilities before deciding`() {
        // Logits giving P(sorghum) = 0.9 at T = 1 drop below 0.8 at T = 2.
        val logits = floatArrayOf(ln(0.9f), ln(0.025f), ln(0.025f), ln(0.025f), ln(0.025f))

        val atOne = speciesProbabilities(logits, temperature = 1f)
        val atTwo = speciesProbabilities(logits, temperature = 2f)

        assertEquals(0.9f, atOne[0], 1e-5f)
        assertTrue(atTwo[0] < 0.8f)
        assertEquals(1f, atTwo.sum(), 1e-6f)
    }

    @Test
    fun `input tensor is a quantized 224 px square`() {
        val quantized = parseModelMetadata(metadataJson(scale = 2f, zeroPoint = 10))
        val photo = uniformImage(300, 200, Rgb(100, 50, 0))

        val tensor = modelInputTensor(photo, quantized)

        assertEquals(224 * 224 * 3, tensor.size)
        // q = v / scale + zeroPoint: 100 -> 60, 50 -> 35, 0 -> 10.
        assertEquals(listOf(60, 35, 10), listOf(tensor[0].toInt() and 0xFF, tensor[1].toInt() and 0xFF, tensor[2].toInt() and 0xFF))
    }

    @Test
    fun `gate runs the model and reads the species head`() {
        var receivedSize = 0
        val model = ImageModel { input ->
            receivedSize = input.size
            listOf(floatArrayOf(5f, 0f, 0f, 0f, 0f))
        }

        val check = SpeciesGate(metadata, model, settings).check(uniformImage(50, 50, Rgb(60, 140, 50)))

        assertEquals(224 * 224 * 3, receivedSize)
        assertTrue(check is SpeciesCheck.Sorghum)
    }

    @Test
    fun `too few logits leave the photo unchecked`() {
        val gate = SpeciesGate(metadata, { listOf(floatArrayOf(5f, 0f, 0f, 0f)) }, settings)

        assertEquals(unavailable(SpeciesUnavailableReason.WRONG_LOGIT_COUNT), gate.check(anyPhoto))
    }

    @Test
    fun `too many logits leave the photo unchecked`() {
        val gate = SpeciesGate(metadata, { listOf(floatArrayOf(5f, 0f, 0f, 0f, 0f, 0f)) }, settings)

        assertEquals(unavailable(SpeciesUnavailableReason.WRONG_LOGIT_COUNT), gate.check(anyPhoto))
    }

    @Test
    fun `no outputs leave the photo unchecked`() {
        // What both platform runners return after an interpreter error.
        val gate = SpeciesGate(metadata, { emptyList() }, settings)

        assertEquals(unavailable(SpeciesUnavailableReason.MISSING_SPECIES_OUTPUT), gate.check(anyPhoto))
    }

    @Test
    fun `fewer outputs than the species index leave the photo unchecked`() {
        val secondOutput = parseModelMetadata(metadataJson(temperature = 1f, outputIndex = 1))
        val gate = SpeciesGate(secondOutput, { listOf(floatArrayOf(5f, 0f, 0f, 0f, 0f)) }, settings)

        assertEquals(unavailable(SpeciesUnavailableReason.MISSING_SPECIES_OUTPUT), gate.check(anyPhoto))
    }

    @Test
    fun `the species head is read at its output index`() {
        val secondOutput = parseModelMetadata(metadataJson(temperature = 1f, outputIndex = 1))
        val gate = SpeciesGate(secondOutput, { listOf(floatArrayOf(0f), floatArrayOf(5f, 0f, 0f, 0f, 0f)) }, settings)

        assertTrue(gate.check(anyPhoto) is SpeciesCheck.Sorghum)
    }

    @Test
    fun `only sorghum and an unchecked photo go on to cultivar matching`() {
        assertTrue(SpeciesCheck.Sorghum(0.9f).allowsCultivarMatching)
        assertTrue(SpeciesCheck.Unavailable(SpeciesUnavailableReason.NO_MODEL).allowsCultivarMatching)
        assertFalse(SpeciesCheck.Unsure(0.5f).allowsCultivarMatching)
        assertFalse(SpeciesCheck.NoPlant.allowsCultivarMatching)
        assertFalse(SpeciesCheck.NotSorghum(lookAlikeClassId = "maize", sorghumProbability = 0.1f).allowsCultivarMatching)
    }

    private val anyPhoto = uniformImage(10, 10, Rgb(0, 0, 0))

    private fun unavailable(reason: SpeciesUnavailableReason) = SpeciesCheck.Unavailable(reason)

    private fun decide(vararg probabilities: Float) = decideSpecies(probabilities, metadata, settings)
}
