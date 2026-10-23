package com.sorghum.session

import com.sorghum.capture.guidance.DeviceTilt
import com.sorghum.capture.guidance.GuidanceState
import com.sorghum.capture.quality.RejectionReason
import com.sorghum.capture.sample.SampleCoverage
import com.sorghum.imaging.Rgb
import com.sorghum.imaging.uniformImage
import com.sorghum.species.ImageModel
import com.sorghum.species.SpeciesCheck
import com.sorghum.species.SpeciesGate
import com.sorghum.species.SpeciesUnavailableReason
import com.sorghum.species.metadataJson
import com.sorghum.species.parseModelMetadata
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class CaptureFlowTest {

    private val level = DeviceTilt(pitchDegrees = 0f, rollDegrees = 0f)
    private val tilted = DeviceTilt(pitchDegrees = 20f, rollDegrees = 0f)
    private val sampleInFrame = SampleCoverage(greenFraction = 0.3f, edgeGreenFraction = 0f, greenConfidence = 1f)

    @Test
    fun `guidance waits for both tilt and frame readings`() {
        val flow = CaptureFlow()

        flow.onTiltChanged(level, timestampMillis = 0)
        assertEquals(CaptureState.Guiding(guidance = null), flow.state)

        flow.onSampleCoverageMeasured(sampleInFrame, timestampMillis = 10)
        assertEquals(CaptureState.Guiding(GuidanceState.HOLD_STEADY), flow.state)
    }

    @Test
    fun `holding aligned for the hold time makes the flow ready`() {
        val flow = CaptureFlow()
        val holdMillis = flow.settings.holdDurationMillis

        flow.onTiltChanged(level, timestampMillis = 1_000)
        flow.onSampleCoverageMeasured(sampleInFrame, timestampMillis = 1_000)
        flow.onSampleCoverageMeasured(sampleInFrame, timestampMillis = 1_000 + holdMillis - 1)
        assertEquals(CaptureState.Guiding(GuidanceState.HOLD_STEADY), flow.state)

        flow.onSampleCoverageMeasured(sampleInFrame, timestampMillis = 1_000 + holdMillis)
        assertEquals(CaptureState.Guiding(GuidanceState.READY), flow.state)
    }

    @Test
    fun `tilt is reported before the sample`() {
        val flow = CaptureFlow()

        flow.onTiltChanged(tilted, timestampMillis = 0)
        flow.onSampleCoverageMeasured(sampleInFrame, timestampMillis = 0)

        assertEquals(CaptureState.Guiding(GuidanceState.TILT_TOP_DOWN), flow.state)
    }

    @Test
    fun `capture starts only from live guidance`() {
        val flow = CaptureFlow()

        assertTrue(flow.startCapture())
        assertEquals(CaptureState.CheckingPhoto, flow.state)
        assertFalse(flow.startCapture())
    }

    @Test
    fun `readings during the photo check do not bring guidance back`() {
        val flow = CaptureFlow()
        flow.startCapture()

        flow.onTiltChanged(level, timestampMillis = 0)
        flow.onSampleCoverageMeasured(sampleInFrame, timestampMillis = 0)

        assertEquals(CaptureState.CheckingPhoto, flow.state)
    }

    @Test
    fun `check result becomes accepted or rejected`() {
        val flow = CaptureFlow()

        flow.startCapture()
        flow.onPhotoChecked(rejection = null)
        assertEquals(CaptureState.PhotoAccepted(SpeciesCheck.Unavailable(SpeciesUnavailableReason.NO_MODEL)), flow.state)

        flow.retake()
        flow.startCapture()
        flow.onPhotoChecked(RejectionReason.BLURRY)
        assertEquals(CaptureState.PhotoRejected(RejectionReason.BLURRY), flow.state)
    }

    @Test
    fun `retake restarts the steady hold and waits for a fresh frame`() {
        val flow = CaptureFlow()
        flow.onTiltChanged(level, timestampMillis = 0)
        flow.onSampleCoverageMeasured(sampleInFrame, timestampMillis = 0)
        flow.startCapture()
        flow.onPhotoChecked(RejectionReason.GLARE)

        flow.retake()
        assertEquals(CaptureState.Guiding(guidance = null), flow.state)

        // An old hold must not carry over: the first aligned reading starts a new hold.
        flow.onSampleCoverageMeasured(sampleInFrame, timestampMillis = 10_000)
        assertEquals(CaptureState.Guiding(GuidanceState.HOLD_STEADY), flow.state)
    }

    @Test
    fun `settings share one green detector between live and quality checks`() {
        val settings = CaptureSettings()

        assertEquals(settings.greenDetection, settings.quality.greenDetection)
    }

    @Test
    fun `without a model the species check is unavailable`() {
        val flow = CaptureFlow()

        assertFalse(flow.isSpeciesCheckAvailable)
        assertEquals(SpeciesCheck.Unavailable(SpeciesUnavailableReason.NO_MODEL), flow.checkSpecies(uniformImage(4, 4, Rgb(60, 140, 50))))
    }

    @Test
    fun `accepted photo carries the species result`() {
        val flow = CaptureFlow()
        flow.startCapture()

        flow.onPhotoChecked(rejection = null, species = SpeciesCheck.NotSorghum(lookAlikeClassId = "maize", sorghumProbability = 0.1f))

        assertEquals(CaptureState.PhotoAccepted(SpeciesCheck.NotSorghum("maize", 0.1f)), flow.state)
    }

    @Test
    fun `an unsure sample is never matched and leads to a retake`() {
        val metadata = parseModelMetadata(metadataJson(temperature = 1f, sorghumThreshold = 0.8f))
        // P(sorghum) = 0.5: below the sorghum threshold, and too likely sorghum to say "not sorghum".
        val gate = SpeciesGate(metadata, ImageModel { listOf(floatArrayOf(0f, -100f, 0f, -100f, -100f)) })
        val flow = CaptureFlow(gate)
        flow.startCapture()

        val species = flow.checkSpecies(uniformImage(8, 8, Rgb(60, 140, 50)))
        // As the apps do once the quality check has passed the photo.
        flow.onPhotoChecked(rejection = null, species = species)

        assertTrue(species is SpeciesCheck.Unsure)
        val accepted = flow.state as CaptureState.PhotoAccepted
        assertFalse(accepted.species.allowsCultivarMatching)
        flow.retake()
        assertEquals(CaptureState.Guiding(guidance = null), flow.state)
    }

    @Test
    fun `a model that fails at run time leaves the photo unchecked`() {
        val metadata = parseModelMetadata(metadataJson())
        // Returns no outputs, as the iOS runner does after an interpreter error.
        val broken = SpeciesGate(metadata, ImageModel { emptyList() })
        val flow = CaptureFlow(broken)

        assertEquals(
            SpeciesCheck.Unavailable(SpeciesUnavailableReason.MISSING_SPECIES_OUTPUT),
            flow.checkSpecies(uniformImage(8, 8, Rgb(60, 140, 50))),
        )
    }
}
