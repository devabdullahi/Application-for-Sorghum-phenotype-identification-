package com.sorghum.capture.platform

import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import com.sorghum.capture.frame.TargetFrame
import com.sorghum.capture.sample.GreenDetectionSettings
import com.sorghum.capture.sample.LIVE_ANALYSIS_LONG_SIDE_PIXELS
import com.sorghum.capture.sample.SampleCoverage
import com.sorghum.capture.sample.measureSampleCoverage
import java.util.concurrent.Executor

/**
 * CameraX analyzer that measures how much green sample is inside the target frame of each
 * live preview frame.
 *
 * Runs on CameraX's analysis thread. Results are handed to [onCoverageMeasured] on
 * [callbackExecutor] (the main thread in this app) so all guidance state is only ever
 * touched from one thread.
 */
class SampleCoverageAnalyzer(
    private val targetFrame: TargetFrame,
    private val settings: GreenDetectionSettings,
    private val callbackExecutor: Executor,
    private val onCoverageMeasured: (SampleCoverage) -> Unit,
) : ImageAnalysis.Analyzer {

    override fun analyze(image: ImageProxy) {
        // Closing the image is what tells CameraX we are ready for the next frame.
        val coverage = image.use {
            val frameRegion = cropToTargetFrame(it, targetFrame, LIVE_ANALYSIS_LONG_SIDE_PIXELS)
            val result = measureSampleCoverage(frameRegion.toPixelImage(), settings)
            frameRegion.recycle()
            result
        }
        callbackExecutor.execute { onCoverageMeasured(coverage) }
    }
}
