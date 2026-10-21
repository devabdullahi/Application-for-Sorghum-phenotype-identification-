package com.sorghum.species

import com.sorghum.imaging.PixelImage
import com.sorghum.imaging.cropCenterSquare
import com.sorghum.imaging.resizeBilinear
import kotlin.math.exp
import kotlin.math.roundToInt

/**
 * Thresholds of the species decision that are not part of the model metadata. The sorghum
 * threshold itself comes from the metadata, because it is calibrated together with the model.
 *
 * @param minNotSorghumProbability how sure the model must be that the sample is not sorghum
 *   (1 - P(sorghum)) before the app says "not sorghum". Below it the app asks for a retake
 *   instead, so a borderline photo never turns a real sorghum sample away.
 *   Initial guess, tune on real photos.
 * @param minNamedLookAlikeProbability how sure the model must be of one look-alike before the
 *   app names it ("looks like maize"). Initial guess, tune on real photos.
 * @param minNoPlantProbability how sure the model must be that there is no plant before
 *   saying so. Initial guess, tune on real photos.
 */
data class SpeciesSettings(
    val minNotSorghumProbability: Float = 0.7f,
    val minNamedLookAlikeProbability: Float = 0.6f,
    val minNoPlantProbability: Float = 0.6f,
) {
    init {
        require(minNotSorghumProbability in 0f..1f) { "minNotSorghumProbability must be within 0..1, was $minNotSorghumProbability" }
        require(minNamedLookAlikeProbability in 0f..1f) {
            "minNamedLookAlikeProbability must be within 0..1, was $minNamedLookAlikeProbability"
        }
        require(minNoPlantProbability in 0f..1f) { "minNoPlantProbability must be within 0..1, was $minNoPlantProbability" }
    }
}

/** The outcome of the species check on one photo. */
sealed interface SpeciesCheck {
    /** No usable model is installed, so the photo was not checked. The UI must say so. */
    data object Unavailable : SpeciesCheck

    /** The sample is sorghum; cultivar matching may continue. */
    data class Sorghum(val sorghumProbability: Float) : SpeciesCheck

    /**
     * The sample is not sorghum. [lookAlikeClassId] names the look-alike (e.g. "maize") when
     * the model is confident which one it is, otherwise null.
     */
    data class NotSorghum(val lookAlikeClassId: String?, val sorghumProbability: Float) : SpeciesCheck

    /** No plant in the photo; ask for a retake. */
    data object NoPlant : SpeciesCheck

    /** The model is not sure either way; ask for a retake or another photo type. */
    data class Unsure(val sorghumProbability: Float) : SpeciesCheck
}

/**
 * Decides whether a photo shows sorghum, before any cultivar matching (ADR-0006).
 *
 * Pure apart from the model call; safe to use from one background thread at a time.
 */
class SpeciesGate(
    private val metadata: ModelMetadata,
    private val model: ImageModel,
    private val settings: SpeciesSettings,
) {
    /** Uses the default settings. Swift cannot use Kotlin default arguments, hence this overload. */
    constructor(metadata: ModelMetadata, model: ImageModel) : this(metadata, model, SpeciesSettings())

    /** Checks [photo]: the upright photo cropped to the target frame, at any size. */
    fun check(photo: PixelImage): SpeciesCheck {
        val outputs = model.run(modelInputTensor(photo, metadata))
        val logits = outputs.getOrNull(metadata.speciesOutputIndex)
            ?: error("Model returned ${outputs.size} outputs; species head expects index ${metadata.speciesOutputIndex}")
        check(logits.size == metadata.speciesClasses.size) {
            "Species head returned ${logits.size} logits for ${metadata.speciesClasses.size} classes"
        }
        return decideSpecies(speciesProbabilities(logits, metadata.speciesTemperature), metadata, settings)
    }
}

/**
 * Builds the model's input tensor from a photo: centred square crop, bilinear resize to the
 * input size, then uint8 quantization q = v / scale + zeroPoint, as `model/` trained it.
 */
internal fun modelInputTensor(photo: PixelImage, metadata: ModelMetadata): ByteArray {
    val input = resizeBilinear(cropCenterSquare(photo), metadata.inputWidthPx, metadata.inputHeightPx)
    return ByteArray(input.rgb.size) { index ->
        val value = input.rgb[index].toInt() and 0xFF
        (value / metadata.inputScale + metadata.inputZeroPoint).roundToInt().coerceIn(0, 255).toByte()
    }
}

/** Calibrated class probabilities: softmax(logits / temperature), computed stably. */
internal fun speciesProbabilities(logits: FloatArray, temperature: Float): FloatArray {
    val scaled = FloatArray(logits.size) { logits[it] / temperature }
    val largest = scaled.max()
    val exponentials = FloatArray(scaled.size) { exp(scaled[it] - largest) }
    val total = exponentials.sum()
    return FloatArray(exponentials.size) { exponentials[it] / total }
}

/**
 * Turns class probabilities into a decision. Order matters: sorghum is checked first against
 * the calibrated threshold; "not sorghum" is only said when the model is confident; anything
 * else is unsure, so a doubtful sample is retaken rather than passed on or turned away.
 */
internal fun decideSpecies(probabilities: FloatArray, metadata: ModelMetadata, settings: SpeciesSettings): SpeciesCheck {
    val classes = metadata.speciesClasses
    val sorghumProbability = classes.indices
        .filter { classes[it].group == SpeciesGroup.SORGHUM }
        .sumOf { probabilities[it].toDouble() }
        .toFloat()
    if (sorghumProbability >= metadata.sorghumThreshold) return SpeciesCheck.Sorghum(sorghumProbability)

    val topIndex = probabilities.indices.maxBy { probabilities[it] }
    val topClass = classes[topIndex]
    val topProbability = probabilities[topIndex]

    return when (topClass.group) {
        SpeciesGroup.NO_PLANT ->
            if (topProbability >= settings.minNoPlantProbability) SpeciesCheck.NoPlant else SpeciesCheck.Unsure(sorghumProbability)
        SpeciesGroup.LOOK_ALIKE, SpeciesGroup.OTHER_PLANT -> {
            if (1f - sorghumProbability < settings.minNotSorghumProbability) return SpeciesCheck.Unsure(sorghumProbability)
            val isNamed = topClass.group == SpeciesGroup.LOOK_ALIKE && topProbability >= settings.minNamedLookAlikeProbability
            SpeciesCheck.NotSorghum(lookAlikeClassId = if (isNamed) topClass.id else null, sorghumProbability = sorghumProbability)
        }
        SpeciesGroup.SORGHUM -> SpeciesCheck.Unsure(sorghumProbability)
    }
}

/** Result of building the gate from the bundled model files at startup. */
sealed interface SpeciesGateLoad {
    data class Loaded(val gate: SpeciesGate) : SpeciesGateLoad

    /** The model cannot be used; the app runs without the species check and says so. */
    data class Failed(val reason: String) : SpeciesGateLoad
}

/**
 * Builds a gate from the bundled metadata and the platform's model runner. A failure is not a
 * crash: per ARCHITECTURE.md section 4.3 the app continues without the species check, tells
 * the user, and never guesses. [SpeciesGateLoad.Failed.reason] is for logs.
 */
fun loadSpeciesGate(metadataJson: String, model: ImageModel): SpeciesGateLoad = try {
    SpeciesGateLoad.Loaded(SpeciesGate(parseModelMetadata(metadataJson), model))
} catch (exception: InvalidModelMetadataException) {
    SpeciesGateLoad.Failed(exception.message ?: "invalid model metadata")
}
