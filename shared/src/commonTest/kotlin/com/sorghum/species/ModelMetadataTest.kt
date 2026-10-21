package com.sorghum.species

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

/** Parses metadata in the exact shape `model/sorghum_model/metadata.py` writes. */
class ModelMetadataTest {

    @Test
    fun `parses the metadata model export writes`() {
        val metadata = parseModelMetadata(metadataJson())

        assertEquals(1, metadata.modelVersion)
        assertEquals(224, metadata.inputWidthPx)
        assertEquals(1f, metadata.inputScale)
        assertEquals(0, metadata.inputZeroPoint)
        assertEquals(0, metadata.speciesOutputIndex)
        assertEquals(SpeciesClass("sorghum_bicolor", SpeciesGroup.SORGHUM), metadata.speciesClasses.first())
        assertEquals(SpeciesGroup.NO_PLANT, metadata.speciesClasses.last().group)
        assertEquals(1.5f, metadata.speciesTemperature)
        assertEquals(0.8f, metadata.sorghumThreshold)
    }

    @Test
    fun `unknown keys such as evaluation numbers are ignored`() {
        parseModelMetadata(metadataJson(extraSpeciesKeys = "\"evaluation\": {\"accuracy\": 0.9},"))
    }

    @Test
    fun `refuses another schema version`() {
        assertFailsWith<InvalidModelMetadataException> { parseModelMetadata(metadataJson(schemaVersion = 2)) }
    }

    @Test
    fun `refuses a model file that does not match the version`() {
        assertFailsWith<InvalidModelMetadataException> { parseModelMetadata(metadataJson(modelFile = "traits-v2.tflite")) }
    }

    @Test
    fun `refuses an unknown resize method`() {
        assertFailsWith<InvalidModelMetadataException> { parseModelMetadata(metadataJson(resize = "stretch")) }
    }

    @Test
    fun `refuses a head without a sorghum class`() {
        assertFailsWith<InvalidModelMetadataException> {
            parseModelMetadata(metadataJson(classes = """[{"id": "maize", "group": "lookAlike"}]"""))
        }
    }

    @Test
    fun `refuses an unknown class group`() {
        assertFailsWith<InvalidModelMetadataException> {
            parseModelMetadata(metadataJson(classes = """[{"id": "sorghum_bicolor", "group": "cereal"}]"""))
        }
    }

    @Test
    fun `refuses a sorghum threshold outside 0 to 1`() {
        assertFailsWith<InvalidModelMetadataException> { parseModelMetadata(metadataJson(sorghumThreshold = 1.0f)) }
        assertFailsWith<InvalidModelMetadataException> { parseModelMetadata(metadataJson(sorghumThreshold = 0f)) }
    }

    @Test
    fun `refuses a non-positive temperature`() {
        assertFailsWith<InvalidModelMetadataException> { parseModelMetadata(metadataJson(temperature = 0f)) }
    }

    @Test
    fun `refuses text that is not metadata`() {
        assertFailsWith<InvalidModelMetadataException> { parseModelMetadata("{\"hello\": 1}") }
        assertFailsWith<InvalidModelMetadataException> { parseModelMetadata("not json") }
    }

    @Test
    fun `failed load gives a reason instead of a gate`() {
        val load = loadSpeciesGate("not json", model = { emptyList() })

        assertEquals(true, load is SpeciesGateLoad.Failed)
    }
}

/** Metadata as `model/` writes it, with the given fields replaced. */
internal fun metadataJson(
    schemaVersion: Int = 1,
    modelFile: String = "traits-v1.tflite",
    resize: String = "centerSquareCropThenBilinear",
    classes: String = DEFAULT_CLASSES,
    temperature: Float = 1.5f,
    sorghumThreshold: Float = 0.8f,
    scale: Float = 1f,
    zeroPoint: Int = 0,
    extraSpeciesKeys: String = "",
): String = """
{
  "backbone": "MobileNetV3-Small (ImageNet weights)",
  "createdOn": "2026-10-21",
  "heads": {
    "species": {
      $extraSpeciesKeys
      "classes": $classes,
      "output": "logits",
      "outputIndex": 0,
      "quantizationParity": {},
      "sorghumThreshold": $sorghumThreshold,
      "temperature": $temperature
    }
  },
  "input": {
    "channelOrder": "RGB",
    "colorSpace": "sRGB",
    "dtype": "uint8",
    "heightPx": 224,
    "pixelValueRange": [0, 255],
    "quantization": {"scale": $scale, "zeroPoint": $zeroPoint},
    "resize": "$resize",
    "widthPx": 224
  },
  "modelFile": "$modelFile",
  "modelVersion": 1,
  "schemaVersion": $schemaVersion,
  "trainingData": {},
  "traits": []
}
"""

internal const val DEFAULT_CLASSES = """[
  {"id": "sorghum_bicolor", "group": "sorghum"},
  {"id": "johnson_grass", "group": "lookAlike"},
  {"id": "maize", "group": "lookAlike"},
  {"id": "other_plant", "group": "otherPlant"},
  {"id": "no_plant", "group": "noPlant"}
]"""
