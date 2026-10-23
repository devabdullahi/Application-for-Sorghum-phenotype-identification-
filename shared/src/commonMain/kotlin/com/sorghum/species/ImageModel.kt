package com.sorghum.species

/**
 * Port to the on-device image model (ADR-0004, ADR-0006). Each platform implements it with
 * LiteRT and hands it to the shared core at startup.
 *
 * The native runner only loads the `.tflite` file and calls the interpreter. Building the
 * input (crop, resize, quantization) and reading the outputs (head mapping, temperature,
 * decisions) happen in `shared/`, from the model metadata, so both platforms agree.
 *
 * Implementations may be called from a background thread, one call at a time.
 *
 * Contract: [run] never throws. On any interpreter failure it returns `emptyList()`, which
 * [SpeciesGate] reports as [SpeciesCheck.Unavailable]. A throw would escape through the Swift
 * bridge and crash the iPhone app, because Swift cannot catch Kotlin exceptions here.
 */
fun interface ImageModel {
    /**
     * Runs the model once.
     *
     * @param inputTensor the uint8 input tensor, height x width x 3 (RGB), row-major, exactly
     *   as `shared/` prepared it; copy it into the input tensor unchanged.
     * @return every output tensor as floats (dequantized if the model's outputs are quantized),
     *   in the model's output order. `shared/` picks each head by its `outputIndex`. Empty
     *   if the interpreter failed.
     */
    fun run(inputTensor: ByteArray): List<FloatArray>
}
