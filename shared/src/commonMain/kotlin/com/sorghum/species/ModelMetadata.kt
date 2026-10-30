package com.sorghum.species

import kotlinx.serialization.Serializable
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json

/** The only `traits-vN.json` schema this app understands (`model/sorghum_model/metadata.py`). */
const val SUPPORTED_METADATA_SCHEMA_VERSION = 1

/** Head id of the species head inside `heads` of the metadata. */
const val SPECIES_HEAD_ID = "species"

/**
 * Head id of the experimental basic-race head inside `heads` (traits-v3, ADR-0012). Optional:
 * metadata without it has no race output. Heads with other ids are ignored.
 */
const val BASIC_RACE_HEAD_ID = "basicRace"

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
 * The experimental basic-race head: which output holds its logits and how [readBasicRace] turns
 * them into an answer. The answer rule was chosen on validation together with the model, so it
 * is data here, like the sorghum threshold (`model/` `race_evaluation.returned_group`).
 *
 * @param races output order of the logits (GRIN basic race names).
 * @param temperature calibration temperature; probabilities are softmax(logits / T).
 * @param groupProbabilityMass the answer is the fewest most likely races whose probabilities
 *   add up to at least this.
 * @param maxGroupSize a group with more races than this is "unrecognized".
 * @param isExperimental true while the output has not met its accuracy goal. The output may
 *   then be shown only as a labelled experimental hint, never as a result or a pass.
 * @param meetsAccuracyGoal whether the held-out evaluation met the race goal (ADR-0011).
 *   basic-race-v1 does not.
 */
data class BasicRaceHead(
    val outputIndex: Int,
    val races: List<String>,
    val temperature: Double,
    val groupProbabilityMass: Double,
    val maxGroupSize: Int,
    val isExperimental: Boolean,
    val meetsAccuracyGoal: Boolean,
)

/**
 * What the app needs from `traits-vN.json`: how to build the input tensor and how to read the
 * species head (and the basic-race head, when present). Everything the gate decides with comes
 * from here, never from platform code.
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
    /** Null when the model has no basic-race output (traits-v2 and earlier). */
    val basicRace: BasicRaceHead? = null,
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

    val species = heads.species ?: invalid("no $SPECIES_HEAD_ID head")
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
        basicRace = heads.basicRace?.toBasicRaceHead(speciesOutputIndex = species.outputIndex),
    )
}

/** The same checks `model/` applies when it writes the head (`metadata._validate_basic_race_head`). */
private fun BasicRaceHeadDocument.toBasicRaceHead(speciesOutputIndex: Int): BasicRaceHead {
    fun invalid(reason: String): Nothing = throw InvalidModelMetadataException("$BASIC_RACE_HEAD_ID head: $reason")

    if (output != "logits") invalid("output must be logits, was $output")
    if (outputIndex < 0) invalid("outputIndex must not be negative")
    if (outputIndex == speciesOutputIndex) invalid("outputIndex $outputIndex is the species output")
    if (races.isEmpty() || races.toSet().size != races.size) invalid("races must be unique and not empty")
    if (temperature <= 0.0) invalid("temperature must be positive")
    if (answerRule.groupProbabilityMass < 0.5 || answerRule.groupProbabilityMass >= 1.0) {
        invalid("groupProbabilityMass must be in [0.5, 1), was ${answerRule.groupProbabilityMass}")
    }
    if (answerRule.maxGroupSize !in 1..races.size) invalid("maxGroupSize must be within 1..${races.size}")
    // A missed goal without the experimental mark would let a failed output read as a result.
    if (!experimental && !meetsAccuracyGoal) invalid("an output that misses its accuracy goal must be experimental")

    return BasicRaceHead(
        outputIndex = outputIndex,
        races = races,
        temperature = temperature,
        groupProbabilityMass = answerRule.groupProbabilityMass,
        maxGroupSize = answerRule.maxGroupSize,
        isExperimental = experimental,
        meetsAccuracyGoal = meetsAccuracyGoal,
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
    val heads: HeadsDocument,
)

/** The heads this app reads; unknown head ids are ignored like any unknown key. */
@Serializable
private class HeadsDocument(
    val species: HeadDocument? = null,
    val basicRace: BasicRaceHeadDocument? = null,
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

// Double, not Float: the rule is compared with summed probabilities exactly as `model/` does.
@Serializable
private class BasicRaceHeadDocument(
    val outputIndex: Int,
    val output: String,
    val races: List<String>,
    val temperature: Double,
    val answerRule: AnswerRuleDocument,
    val experimental: Boolean,
    val meetsAccuracyGoal: Boolean,
)

@Serializable
private class AnswerRuleDocument(val groupProbabilityMass: Double, val maxGroupSize: Int)
