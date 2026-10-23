package com.sorghum.capture.platform

import android.content.res.AssetManager
import com.sorghum.species.ImageModel
import org.tensorflow.lite.DataType
import org.tensorflow.lite.Interpreter
import org.tensorflow.lite.Tensor
import java.io.Closeable
import java.io.FileInputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.MappedByteBuffer
import java.nio.channels.FileChannel

/**
 * The shared [ImageModel] port on Android, backed by LiteRT (ADR-0010). Android counterpart of
 * `ios/SorghumCapture/Model/LiteRTImageModel.swift`.
 *
 * It only loads the `.tflite` file and runs the interpreter: the shared core builds the input
 * tensor and reads the outputs (ADR-0004). [run] and [close] are synchronized because the
 * interpreter is not thread-safe and is closed from the main thread when the screen goes away,
 * possibly while a background photo check is still running.
 *
 * @throws java.io.IOException if the asset is missing or compressed in the APK (it must be
 *   listed in `androidResources.noCompress` to be memory-mapped).
 * @throws IllegalArgumentException if the file is not a valid LiteRT model.
 */
class LiteRTImageModel(assets: AssetManager, assetFileName: String) : ImageModel, Closeable {

    private val interpreter = Interpreter(mapAsset(assets, assetFileName))
    private var isClosed = false

    /**
     * Returns every output as floats, dequantizing uint8 outputs. On an interpreter error, or
     * after [close], it returns no outputs, which the shared core reports as "species check
     * unavailable" rather than a guess.
     */
    @Synchronized
    override fun run(inputTensor: ByteArray): List<FloatArray> {
        if (isClosed) return emptyList()
        return try {
            // LiteRT reads inputs from a direct buffer in native byte order; the uint8 values
            // are copied unchanged, as the port requires.
            val input = ByteBuffer.allocateDirect(inputTensor.size).order(ByteOrder.nativeOrder()).put(inputTensor)
            input.rewind()
            val outputTensors = (0 until interpreter.outputTensorCount).map { interpreter.getOutputTensor(it) }
            val outputBuffers = outputTensors.map { ByteBuffer.allocateDirect(it.numBytes()).order(ByteOrder.nativeOrder()) }
            interpreter.runForMultipleInputsOutputs(arrayOf(input), outputBuffers.withIndex().associate { it.index to it.value })
            outputBuffers.forEach { it.rewind() }
            outputTensors.zip(outputBuffers) { tensor, buffer -> floatsOf(tensor, buffer) }
        } catch (exception: IllegalArgumentException) {
            // Input size or type does not match the model.
            emptyList()
        } catch (exception: IllegalStateException) {
            // The interpreter failed while running.
            emptyList()
        }
    }

    /** Frees the native interpreter. Later [run] calls return no outputs. */
    @Synchronized
    override fun close() {
        if (isClosed) return
        isClosed = true
        interpreter.close()
    }
}

/** Memory-maps an uncompressed asset, so the model is not copied onto the Java heap. */
private fun mapAsset(assets: AssetManager, assetFileName: String): MappedByteBuffer =
    assets.openFd(assetFileName).use { descriptor ->
        FileInputStream(descriptor.fileDescriptor).use { stream ->
            stream.channel.map(FileChannel.MapMode.READ_ONLY, descriptor.startOffset, descriptor.declaredLength)
        }
    }

/**
 * Reads one output tensor as floats. The species model exports float logits
 * (`model/sorghum_model/export.py`); uint8 outputs are dequantized with
 * real = scale * (q - zeroPoint). Any other type returns no values, which the shared core
 * reports as "species check unavailable". Same cases as the iOS runner.
 */
private fun floatsOf(tensor: Tensor, buffer: ByteBuffer): FloatArray = when (tensor.dataType()) {
    DataType.FLOAT32 -> {
        val floats = buffer.asFloatBuffer()
        FloatArray(floats.remaining()) { floats.get(it) }
    }
    DataType.UINT8 -> {
        val quantization = tensor.quantizationParams()
        // LiteRT reports scale 0 for a tensor without quantization; its values are then used as is.
        val isQuantized = quantization.scale != 0f
        FloatArray(buffer.remaining()) { index ->
            val quantized = buffer.get(index).toInt() and 0xFF
            if (isQuantized) quantization.scale * (quantized - quantization.zeroPoint) else quantized.toFloat()
        }
    }
    else -> FloatArray(0)
}
