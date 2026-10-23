package com.sorghum.capture.platform

import android.content.res.AssetManager
import android.util.Log
import com.sorghum.species.SpeciesGate
import com.sorghum.species.SpeciesGateLoad
import com.sorghum.species.loadSpeciesGate
import java.io.Closeable
import java.io.IOException

/**
 * The species model bundled in the APK: `traits-vN.tflite` and `traits-vN.json` in
 * `app/src/main/assets/`, copied from the `model/` export. The highest N found is used.
 * Android counterpart of `ios/SorghumCapture/Model/BundledSpeciesModel.swift`.
 *
 * Owns the native interpreter behind [gate]; [close] it when the screen that uses it goes away.
 */
class BundledSpeciesModel private constructor(
    /** The shared species gate, running on this model. */
    val gate: SpeciesGate,
    private val model: LiteRTImageModel,
) : Closeable {

    /** Frees the interpreter. The gate then reports every photo as not checked. */
    override fun close() = model.close()

    companion object {
        private const val TAG = "SpeciesModel"

        /**
         * Loads the bundled model, or returns null when no usable model is bundled. Null is not
         * an error for the user: the app runs without the species check and says so
         * (ARCHITECTURE.md section 4.3). Why it is null goes to logcat.
         *
         * Reads and memory-maps assets, so it does disk I/O; the files are small and loaded
         * once per screen.
         */
        fun load(assets: AssetManager): BundledSpeciesModel? {
            val assetFileNames = assets.list("")?.toList().orEmpty()
            val version = highestModelVersion(assetFileNames)
            if (version == null) {
                Log.i(TAG, "No species model bundled; species check unavailable")
                return null
            }
            val modelFileName = "traits-v$version.tflite"
            if (modelFileName !in assetFileNames) {
                Log.e(TAG, "traits-v$version is incomplete: both .json and .tflite are needed")
                return null
            }

            val model = try {
                LiteRTImageModel(assets, modelFileName)
            } catch (exception: IOException) {
                Log.e(TAG, "$modelFileName could not be read", exception)
                return null
            } catch (exception: IllegalArgumentException) {
                // Also what LiteRT throws when a delegate (XNNPACK by default) cannot prepare a node.
                Log.e(TAG, "$modelFileName is not a valid LiteRT model or cannot be prepared", exception)
                return null
            } catch (exception: IllegalStateException) {
                Log.e(TAG, "$modelFileName could not be prepared by LiteRT", exception)
                return null
            }

            val metadataJson = try {
                assets.open("traits-v$version.json").bufferedReader().use { it.readText() }
            } catch (exception: IOException) {
                Log.e(TAG, "traits-v$version.json could not be read", exception)
                model.close()
                return null
            }

            return when (val load = loadSpeciesGate(metadataJson, model)) {
                is SpeciesGateLoad.Loaded -> {
                    Log.i(TAG, "Species model v$version loaded")
                    BundledSpeciesModel(load.gate, model)
                }
                is SpeciesGateLoad.Failed -> {
                    Log.e(TAG, "traits-v$version.json refused: ${load.reason}")
                    model.close()
                    null
                }
            }
        }
    }
}

private const val METADATA_PREFIX = "traits-v"
private const val METADATA_SUFFIX = ".json"

/**
 * The largest N with a `traits-vN.json` among [assetFileNames], or null if there is none.
 * Same rule as `BundledSpeciesModel.highestModelVersion(amongFileNames:)` on iOS, so both apps
 * pick the same model when several are bundled.
 */
internal fun highestModelVersion(assetFileNames: List<String>): Int? =
    assetFileNames
        .filter { it.startsWith(METADATA_PREFIX) && it.endsWith(METADATA_SUFFIX) }
        .mapNotNull { it.removePrefix(METADATA_PREFIX).removeSuffix(METADATA_SUFFIX).toIntOrNull() }
        .maxOrNull()
