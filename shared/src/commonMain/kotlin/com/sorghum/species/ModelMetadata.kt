package com.sorghum.species

import kotlinx.serialization.Serializable
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json

/** The only `traits-vN.json` schema this app understands (`model/sorghum_model/metadata.py`). */
const val SUPPORTED_METADATA_SCHEMA_VERSION = 1

/** Head id of the species head inside `heads` of the metadata. */
const val SPECIES_HEAD_ID = "species"

/** Preprocessing method name agreed with `model/`: centred square crop, then bilinear resize. */
const val CENTER_SQUARE_CROP_THEN_BILINEAR = "centerSquareCropThenBilinear"

/** How the species gate treats a class when it is the top prediction (ADR-0006). */
enum class SpeciesGroup {
    /** Continue to calibration, traits and reasoning. */
    SORGHUM,

    /** Stop with "not sorghum" and name the look-alike when confident. */
    LOOK_ALIKE,

    /** Stop with "not sorghum". */
    OTHER_PLANT,

    /** Stop and ask for a retake. */
    NO_PLANT,
}

/** One output of the species head, in output order. */
data class SpeciesClass(val id: String, val group: SpeciesGroup)

/**
 * What the app needs from `traits-vN.json`: how to build the input tensor and how to read the
 * species head. Everything the gate decides with comes from here, never from platform code.
 *
 * @param inputScale and [inputZeroPoint] turn a 0–255 pixel value v into the model's uint8
 *   input: q = v / scale + zeroPoint.
 * @param speciesTemperature calibration temperature; probabilities are softmax(logits / T).
 * @param sorghumThreshold minimum summed probability of the sorghum group to continue.
 */
data class ModelMetadata(
    val modelVersion: Int,
    val modelFile: String,
    val inputWidthPx: Int,
    val inputHeightPx: Int,
    val inputScale: Float,
    val inputZeroPoint: Int,
    val speciesOutputIndex: Int,
    val speciesClasses: List<SpeciesClass>,
    val speciesTemperature: Float,
    val sorghumThreshold: Float,
)

/** The metadata is missing fields or would make the gate decide wrongly; the model must not be used. */
class InvalidModelMetadataException(message: String, cause: Throwable? = null) : Exception(message, cause)

/**
 * Parses and validates `traits-vN.json`. Throws [InvalidModelMetadataException] for anything
 * the app cannot use safely; the caller then runs without the species check and says so
 * (ARCHITECTURE.md section 4.3), rather than guessing.
 */
fun parseModelMetadata(json: String): ModelMetadata {
    val document = try {
        metadataJson.decodeFromString<MetadataDocument>(json)
    } catch (exception: SerializationException) {
        throw InvalidModelMetadataException("Model metadata does not match schema $SUPPORTED_METADATA_SCHEMA_VERSION", exception)
    } catch (exception: IllegalArgumentException) {
        throw InvalidModelMetadataException("Model metadata has an unexpected value", exception)
    }
    return document.toModelMetadata()
}

// Unknown keys are ignored so model/ can add evaluation numbers without an app release.
private val metadataJson = Json { ignoreUnknownKeys = true }

private fun MetadataDocument.toModelMetadata(): ModelMetadata {
    fun invalid(reason: String): Nothing = throw InvalidModelMetadataException(reason)

    if (schemaVersion != SUPPORTED_METADATA_SCHEMA_VERSION) {
        invalid("schemaVersion is $schemaVersion; this app reads $SUPPORTED_METADATA_SCHEMA_VERSION")
    }
    if (modelFile != "traits-v$modelVersion.tflite") invalid("modelFile $modelFile does not match modelVersion $modelVersion")
    if (input.channelOrder != "RGB" || input.dtype != "uint8") {
        invalid("input must be uint8 RGB, was ${input.dtype} ${input.channelOrder}")
    }
    if (input.resize != CENTER_SQUARE_CROP_THEN_BILINEAR) invalid("unknown resize method ${input.resize}")
    if (input.widthPx <= 0 || input.heightPx <= 0) invalid("input size must be positive")
    if (input.quantization.scale <= 0f) invalid("input quantization scale must be positive")

    val species = heads[SPECIES_HEAD_ID] ?: invalid("no $SPECIES_HEAD_ID head")
    if (species.output != "logits") invalid("species head output must be logits, was ${species.output}")
    if (species.outputIndex < 0) invalid("species outputIndex must not be negative")
    val classes = species.classes.map { SpeciesClass(it.id, speciesGroupOf(it.group) ?: invalid("unknown group ${it.group}")) }
    if (classes.map { it.id }.toSet().size != classes.size) invalid("species class ids must be unique")
    if (classes.none { it.group == SpeciesGroup.SORGHUM }) invalid("species head needs a sorghum class")
    if (species.temperature <= 0f) invalid("temperature must be positive")
    if (species.sorghumThreshold <= 0f || species.sorghumThreshold >= 1f) invalid("sorghumThreshold must be in (0, 1)")

    return ModelMetadata(
        modelVersion = modelVersion,
        modelFile = modelFile,
        inputWidthPx = input.widthPx,
        inputHeightPx = input.heightPx,
        inputScale = input.quantization.scale,
        inputZeroPoint = input.quantization.zeroPoint,
        speciesOutputIndex = species.outputIndex,
        speciesClasses = classes,
        speciesTemperature = species.temperature,
        sorghumThreshold = species.sorghumThreshold,
    )
}

private fun speciesGroupOf(name: String): SpeciesGroup? = when (name) {
    "sorghum" -> SpeciesGroup.SORGHUM
    "lookAlike" -> SpeciesGroup.LOOK_ALIKE
    "otherPlant" -> SpeciesGroup.OTHER_PLANT
    "noPlant" -> SpeciesGroup.NO_PLANT
    else -> null
}

// Wire format of traits-vN.json; mapped to ModelMetadata after validation.

@Serializable
private class MetadataDocument(
    val schemaVersion: Int,
    val modelVersion: Int,
    val modelFile: String,
    val input: InputDocument,
    val heads: Map<String, HeadDocument>,
)

@Serializable
private class InputDocument(
    val widthPx: Int,
    val heightPx: Int,
    val channelOrder: String,
    val dtype: String,
    val quantization: QuantizationDocument,
    val resize: String,
)

@Serializable
private class QuantizationDocument(val scale: Float, val zeroPoint: Int)

@Serializable
private class HeadDocument(
    val outputIndex: Int,
    val output: String,
    val classes: List<ClassDocument>,
    val temperature: Float,
    val sorghumThreshold: Float,
)

@Serializable
private class ClassDocument(val id: String, val group: String)
