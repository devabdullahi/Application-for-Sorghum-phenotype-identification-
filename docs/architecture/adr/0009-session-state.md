# ADR-0009: SessionState and the identification session API, exposed to Swift through SKIE

Status: Proposed · Date: 2026-10-23

## Context
Phase 1 has one shared state machine, `CaptureFlow` with `CaptureState` (`shared/session/CaptureFlow.kt`). It covers one photo: live guidance, quality check, species check. The native apps adapt it: the Android `CaptureViewModel` maps it to its own `CaptureUiState`; the iOS `CaptureModel` casts it (`flow.state as? CaptureStateGuiding`, then a `default:` branch) and runs the quality and species checks itself on a detached task.

The next steps need much more from `session` (ARCHITECTURE.md §3.2, §4.1-4.3): several photo types, colour card calibration, trait reading, reasoning over the readings of all photos, user corrections, measured-only mode, and a startup error for invalid tables. The pure pieces exist or are in review: `species/SpeciesGate`, `calibration/calibrateWithColourCard`, `traits/TraitEstimate` and `TraitCatalogue`, and `reasoning/identifyCultivar` and `correctTrait` (PR #8, unmerged).

Two rules fix the shape of the answer. CLAUDE.md: "`SessionState` is the only sealed hierarchy exposed to Swift, through SKIE or flat fields. Do not expose `Flow` or suspend functions without SKIE." CLAUDE.md, Concurrency: "The post-capture pipeline runs on one background coroutine per photo in `session`, with a progress state."

Facts about the build that bear on the choice:
- `shared/` is a static framework named `Shared`, built by `embedAndSignAppleFrameworkForXcode` in an Xcode build phase (`ios/project.yml`). CocoaPods is used only for LiteRT (ADR-0007) and does not touch `Shared`.
- Kotlin is 2.2.10 (`gradle/libs.versions.toml`). `shared/` has no kotlinx.coroutines dependency yet.
- iOS is the lead platform, so the iOS screen is where a missed state would show first.

### What the web says (checked 2026-10-23)
- **SKIE** (Touchlab) is a Kotlin compiler plugin that changes the Swift API of the produced framework. Latest release 0.10.15 (25 Sep 2026), which added Kotlin 2.4.20 ([releases](https://github.com/touchlab/SKIE/releases), [0.10.15 notes](https://skie.touchlab.co/changelog/0.10.15)). The 0.10 line covers Kotlin 2.2: 0.10.4 has `kgp_2.2.0` artifacts ([Scaladex](https://index.scala-lang.org/touchlab/skie/artifacts)), and 0.10.7 added "Kotlin 2.2.20 and 2.2.21" ([0.10.7 notes](https://skie.touchlab.co/changelog/0.10.7)). No page states 2.2.10 explicitly. Each SKIE release supports a specific list of Kotlin versions, and support for a new Kotlin version arrives after its stable release ([Kotlin Slack](https://slack-chats.kotlinlang.org/t/25753811/skie-0-9-4-is-out-with-support-for-kotlin-2-1-0-tada)).
- **Installation**: plugin `co.touchlab.skie`, applied in the module that has a `framework` block or the CocoaPods plugin ([installation](https://skie.touchlab.co/Installation)). Our `framework` block qualifies.
- **Sealed classes**: SKIE generates a Swift enum plus `onEnum(of:)`, so `switch onEnum(of: state)` is exhaustive with no `default` ([sealed](https://skie.touchlab.co/features/sealed)).
- **Flow**: `StateFlow<T>` becomes `SkieSwiftStateFlow<T>`, an `AsyncSequence` with the type argument kept. Cancelling the Swift task cancels collection, and a `for await` loop in a SwiftUI `.task` ends when the view goes away ([flows](https://skie.touchlab.co/features/flows)). SwiftUI helpers (`Observing`, `collect`) exist but are a preview and opt-in ([flows in SwiftUI](https://skie.touchlab.co/features/flows-in-swiftui)).
- **Suspend functions**: with SKIE they are real Swift `async` functions with two-way cancellation, callable from any thread. Without SKIE they are completion handlers with no cancellation and are callable only from the main thread ([suspend](https://skie.touchlab.co/features/suspend)). The Kotlin docs call the plain `async` bridge "highly experimental" ([Kotlin ObjC interop](https://kotlinlang.org/docs/native-objc-interop.html)).
- **Plain Kotlin/Native export without SKIE**: Kotlin enums arrive in Swift as classes, and a `switch` over them needs a `default` ([Kotlin ObjC interop](https://kotlinlang.org/docs/native-objc-interop.html)). Sealed classes arrive as a class hierarchy, so Swift casts (what `CaptureModel.publishState` does today).
- **Scoping**: SKIE features can be switched off globally and on again per package prefix, `skie { features { group { … } group("com.sorghum.session") { … } } }`, with the last match winning ([configuration](https://skie.touchlab.co/configuration/)).
- **Kotlin Swift export**, the long-term official answer, maps sealed classes to Swift enums and `Flow` to `AsyncSequence`, but it is Alpha with breaking changes expected ([Swift export](https://kotlinlang.org/docs/native-swift-export.html)).

## Options
1. **SKIE, scoped to `session`.** `SessionState` is a sealed Kotlin hierarchy. The session publishes it as `StateFlow<SessionState>`. Swift iterates it as an `AsyncSequence` and switches exhaustively with `onEnum(of:)`. No public suspend functions.
2. **Flat fields plus a listener, no plugin.** Kotlin keeps the sealed type internally and exposes a flat snapshot to Swift: `SessionSnapshot(kind: SessionStateKind, guidance: GuidanceState?, rejection: RejectionReason?, identification: CultivarIdentification?, …)`, delivered by `fun interface SessionListener { fun onStateChanged(snapshot: SessionSnapshot) }`, called on main.
3. **Kotlin Swift export.** It gives the same Swift shape as option 1 without a third-party plugin, but it is Alpha and needs a different Xcode integration.
4. **No session state machine in shared.** Each app sequences the pipeline itself from the pure functions. This puts decisions in native code (which CLAUDE.md forbids) and duplicates the sequencing.

| Criterion | 1 SKIE | 2 Flat + listener |
| --- | --- | --- |
| Swift notices a new state at compile time | Yes, `onEnum` switch is exhaustive | No, `kind` is a Kotlin enum, so its switch needs `default` |
| Invalid states representable | No (each state carries only its own fields) | Yes, every field is nullable on every kind (coding standard §40) |
| Observation lifetime | `for await` in `.task`, cancelled with the view | Hand-written register/unregister. A Swift closure held by a Kotlin object risks a retain cycle |
| One state type for Android and iOS | Yes | Either two shapes (sealed for Android, flat for iOS) or Android also uses the flat one |
| Build cost | Plugin runs at framework link. SKIE also compiles generated Swift, so expect a slower link (measure) | None |
| Kotlin upgrades | Wait for a SKIE release that supports the new Kotlin version | Free |
| Privacy | Build-time plugin plus a small runtime. No networking (confirm when adding: Shared has no network symbols) | Nothing added |

## Decision
**Option 1: SKIE, scoped to the `session` API.** Reasons:
1. Exhaustiveness is the property that matters most. The hierarchy below has 15 states, and S7 and later steps will add more. With SKIE a forgotten state fails the iOS build. With flat fields it renders nothing, on the lead platform, and the parity rule cannot catch it because parity tests cover `shared/`, not screens.
2. Flat fields make invalid combinations representable (`kind = RESULT_READY` with `identification = null`). Every Swift consumer then needs runtime checks that the type system would otherwise do.
3. The pipeline must run on a session-owned coroutine with progress states (CLAUDE.md). A `StateFlow` is the natural output. SKIE gives Swift a cancellable `AsyncSequence`, while a listener would need its own lifetime and threading contract.
4. It fits the build. SKIE goes in `shared/build.gradle.kts`, the module with the `framework` block. `embedAndSign` is unchanged and the LiteRT Podfile is untouched.
5. The fallback is cheap. `SessionState` is a plain Kotlin sealed hierarchy either way. If SKIE blocks a Kotlin upgrade or fails the build, option 2 can be added as a flattening adapter inside `session` without changing the Kotlin types or Android.

**Scope of SKIE** (keeps generated Swift and link time small, and keeps the "only one sealed hierarchy" rule true):

```kotlin
// shared/build.gradle.kts
plugins { id("co.touchlab.skie") version "<0.10.x that supports our Kotlin>" }
skie {
    features {
        group {                              // everything: off
            SealedInterop.Enabled(false)
            FlowInterop.Enabled(false)
            SuspendInterop.Enabled(false)
        }
        group("com.sorghum.session") {       // session API: on
            SealedInterop.Enabled(true)
            FlowInterop.Enabled(true)
        }
    }
}
```

Enum interop stays at SKIE's default (on), so `RejectionReason`, `CardNotFoundReason`, `PhotoType`, `GuidanceState`, `ProcessingStep` and `IdentificationOutcome` become exhaustive Swift enums too. No public `suspend` function is exposed. The session API is plain functions in and one `StateFlow` out.

Other sealed types (`CaptureState`, `SpeciesCheck`, `SpeciesGateLoad`, `ColourCardCalibration`) stay as classes in Swift and leave the native API when the apps switch to the session (S7, A2). `SessionState` carries their content as plain fields and enums, not as the sealed types themselves.

### SessionState

New file `shared/src/commonMain/kotlin/com/sorghum/session/SessionState.kt`:

```kotlin
/** Everything an identification screen can show. Exactly one is active at a time. */
sealed interface SessionState {

    // Startup
    /** Tables missing or invalid (ARCHITECTURE.md §4.3). Terminal: reasoning never runs on partial tables. */
    data class StartupFailed(val failure: StartupFailure, val detailForLog: String) : SessionState

    // Between photos
    /** Pick leaf, panicle or grain. [photoTypesTaken] have readings already; [hasResult] offers "back to result". */
    data class ChoosingPhotoType(
        val photoTypesTaken: List<PhotoType>,
        val hasResult: Boolean,
        val capabilities: SessionCapabilities,
    ) : SessionState

    // One photo (phase 1 states, now tagged with the photo type)
    /** Live guidance. [guidance] is null until the first tilt and frame readings arrive. */
    data class Guiding(val photoType: PhotoType, val guidance: GuidanceState?, val coverage: SampleCoverage?) : SessionState
    /** READY was held, or the shutter was pressed: the platform takes the still now, once per entry. */
    data class TakingPhoto(val photoType: PhotoType) : SessionState
    /** Quality check and species gate (fast; can end in a retake). */
    data class CheckingPhoto(val photoType: PhotoType) : SessionState
    data class PhotoRejected(val photoType: PhotoType, val reason: RejectionReason) : SessionState
    /** Species gate: confident it is not sorghum. [lookAlikeClassId] is set only when the look-alike is confident ("maize"). */
    data class NotSorghum(val photoType: PhotoType, val lookAlikeClassId: String?) : SessionState
    /** Species gate: not sure, or no plant. Ask for a retake or another photo type; never matched. */
    data class SpeciesUnsure(val photoType: PhotoType, val isPlantMissing: Boolean) : SessionState
    /** No usable colour card: reject (§4.3). */
    data class CalibrationFailed(val photoType: PhotoType, val reason: CardNotFoundReason) : SessionState
    /** Accepted as sorghum; calibration, trait reading and reasoning run on the worker. */
    data class Processing(val photoType: PhotoType, val step: ProcessingStep) : SessionState
    /** The photo passed every check but no trait could be read from it. Retake or another photo type. */
    data class NoTraitsRead(val photoType: PhotoType) : SessionState

    // Result (after any photo, and after every correction)
    data class ResultReady(
        val identification: CultivarIdentification,   // outcome SINGLE_MATCH / GROUP / UNRECOGNIZED, group, topMatches, explanation
        val readings: List<TraitReading>,               // what the explanation and the correction picker show
        val photoTypesTaken: List<PhotoType>,
        val capabilities: SessionCapabilities,          // measured-only flag, versions
    ) : SessionState

    // Platform failures (phase 1)
    data object CaptureFailed : SessionState
    data object CameraUnavailable : SessionState
    data object LevelSensorUnavailable : SessionState
}

enum class StartupFailure { TABLES_MISSING, TABLES_INVALID }

enum class ProcessingStep { CALIBRATING, READING_TRAITS, MATCHING_CULTIVARS }

/**
 * One trait as the session holds it.
 * @param descriptor gives the state labels the correction picker lists.
 * @param isCorrected the user set this trait; [estimate] is then the near-certain one from correctTrait.
 */
data class TraitReading(
    val descriptor: TraitDescriptor,
    val estimate: TraitEstimate,
    val photoType: PhotoType,
    val isCorrected: Boolean,
)

/** Fixed at startup, except that a model failing at run time switches to measured-only mode. */
data class SessionCapabilities(
    val availablePhotoTypes: List<PhotoType>,   // only types whose sample detector exists (LEAF today)
    val isSpeciesCheckAvailable: Boolean,
    val isMeasuredOnlyMode: Boolean,            // learned traits exist in the catalogue but no model can read them
    val versions: AssetVersions,
)

/** Shown in the result details (CLAUDE.md, ML hygiene). [modelVersion] is null without a model. */
data class AssetVersions(
    val modelVersion: Int?,
    val tablesSchemaVersion: Int,
    val tablesDataVersion: Int,
    val tablesAttribution: String,              // Genesys CC BY-SA; the licence requires showing it
)
```

`ResultReady` carries `CultivarIdentification` from PR #8 as it is (plain data classes and the `IdentificationOutcome` enum), so the explanation is the posterior's own numbers (`TraitInfluence`) and is never rewritten in `session`. There is no separate `Correcting` state. The correction picker is presentation: it reads `readings[i].descriptor.states`, and `correctTrait` returns a new `ResultReady`. A separate state would copy `ResultReady` and add nothing that shared needs to decide.

**Mapping from today's `CaptureState`** (no phase 1 behaviour is lost):

| `CaptureState` | `SessionState` |
| --- | --- |
| `Guiding(guidance)` | `Guiding(photoType, guidance, coverage)`. Coverage was native-only state on iOS; it moves into the state. |
| (native compares guidance with READY) | `TakingPhoto`. The "is it READY, held 800 ms" decision moves into shared. |
| `CheckingPhoto` | `CheckingPhoto(photoType)` |
| `PhotoAccepted(species)` | `species = Sorghum` → `Processing` → `ResultReady` / `NoTraitsRead` / `CalibrationFailed`. `NotSorghum` → `NotSorghum`. `Unsure` / `NoPlant` → `SpeciesUnsure`. `Unavailable` → continue, with `isSpeciesCheckAvailable = false` |
| `PhotoRejected(reason)` | `PhotoRejected(photoType, reason)` |
| `CaptureFailed`, `CameraUnavailable`, `LevelSensorUnavailable` | same |

`CaptureFlow` is not rewritten. `IdentificationSession` owns one `CaptureFlow` and delegates live guidance, the steady hold, the quality check and the species check to it, so guidance and quality behave exactly as in phase 1 and keep their tests. `CaptureFlow` and `CaptureState` stay public until both apps use the session (S7, A2), then become `internal`.

### Session API

New file `shared/src/commonMain/kotlin/com/sorghum/session/IdentificationSession.kt` (signatures only):

```kotlin
/**
 * One identification: photos of one sample, the readings they give, and the result.
 *
 * Threads: every event function and [state] belong to the main thread (single owner, no locks),
 * except [measureLiveFrame], which is pure and runs on the camera thread. The post-capture
 * pipeline runs on one worker coroutine per photo, started by [onPhotoTaken]; it posts progress
 * and its outcome back to main. shared/ never reads a clock: timestamps come from the caller's
 * monotonic clock.
 */
class IdentificationSession(
    assets: SessionAssets,
    settings: SessionSettings,
    mainDispatcher: CoroutineDispatcher,     // Dispatchers.Main in the apps; a test dispatcher in commonTest
    workerDispatcher: CoroutineDispatcher,   // Dispatchers.Default
) {
    /** Default settings and dispatchers. Swift cannot use Kotlin default arguments, hence the overload. */
    constructor(assets: SessionAssets)

    val state: StateFlow<SessionState>

    fun startPhoto(photoType: PhotoType): Boolean            // from ChoosingPhotoType, ResultReady or any retake state
    fun onTiltChanged(tilt: DeviceTilt, timestampMillis: Long)
    fun measureLiveFrame(image: PixelImage): SampleCoverage  // any thread; same detector as post-capture
    fun onLiveFrameMeasured(coverage: SampleCoverage, timestampMillis: Long)
    fun captureNow(): Boolean                                // shutter button: Guiding -> TakingPhoto
    fun onPhotoTaken(photo: CapturedPhoto): Boolean          // TakingPhoto (or library pick) -> CheckingPhoto; starts the worker
    fun onCaptureFailed()
    fun onCameraUnavailable()
    fun onLevelSensorUnavailable()
    fun retake(): Boolean                                    // any per-photo retake state -> Guiding, same type
    fun choosePhotoType(): Boolean                           // -> ChoosingPhotoType, readings kept
    fun correctTrait(traitId: String, stateCode: String): Boolean  // ResultReady only; reasoning only
    fun reset()                                              // new sample: cancels the worker, clears readings
    fun close()                                              // cancels the session scope; call from onCleared / deinit
}

/**
 * A still photo for the pipeline.
 * @param image the whole upright photo, long side at most PIPELINE_PHOTO_LONG_SIDE_PIXELS.
 * @param targetRegion the target frame in [image] fractions (preview-to-image mapping stays native, one place per platform).
 */
data class CapturedPhoto(val image: PixelImage, val targetRegion: NormalizedRect, val source: PhotoSource)

data class SessionSettings(
    val capture: CaptureSettings,
    val species: SpeciesSettings,
    val colourCard: ColourCardSettings,
    val boardLayout: BoardLayout,      // where the card slot is, as a NormalizedRect of the target frame
    val traitNoise: TraitNoiseSettings,
    val reasoning: ReasoningSettings,
)
```

Event functions return `false` and change nothing when the current state does not accept them, as `CaptureFlow.startCapture` does today. This makes a double tap, a late READY or a correction during processing harmless.

**Pipeline per photo** (worker, one coroutine, `ensureActive()` between steps so `reset()` stops it at the next step): crop the target region → downscale to `QUALITY_CHECK_LONG_SIDE_PIXELS` → quality → species → `Processing(CALIBRATING)`: card in the board's slot → `Processing(READING_TRAITS)`: measured readers for the photo type, then trait heads when the model has them → `Processing(MATCHING_CULTIVARS)`: `identifyCultivar` over **all** stored estimates. Each outcome is applied on main and only if the photo is still current (a generation counter, so a result for a photo the user reset away is dropped). The `PixelImage` is released when the worker ends. The session keeps estimates, never pixels.

**Accumulation across leaf, panicle and grain:**
- The session holds `estimates: Map<traitId, TraitEstimate>`, `photoTypesTaken`, and `correctedTraitIds`.
- An accepted photo of type T replaces the estimates of T's traits (a retake of the leaf replaces the leaf readings). Other photo types' readings stay.
- A photo that ends in `PhotoRejected`, `NotSorghum`, `SpeciesUnsure`, `CalibrationFailed` or `NoTraitsRead` adds nothing and removes nothing.
- Reasoning always runs from the stored estimates with `identifyCultivar`. It never patches the previous posterior.
- `correctTrait` calls `reasoning.correctTrait`, stores the returned estimates, marks the trait corrected and publishes a new `ResultReady` on main (cheap: cultivars × traits × states). A later photo does not overwrite a corrected trait.
- `reset()` clears everything and returns to `ChoosingPhotoType`.

**Threads:**

| Work | Thread |
| --- | --- |
| `measureLiveFrame` | camera queue/executor (late frames dropped natively, as now) |
| tilt, frame result, every event, `state` writes | main |
| quality, species, calibration, traits, model, reasoning for a photo | worker coroutine (`workerDispatcher`), one per photo |
| progress and outcome publishing | main (`withContext(mainDispatcher)`) |
| re-reasoning after a correction | main, synchronous |

**Failure paths** (ARCHITECTURE.md §4.3):

| Failure | Session behaviour |
| --- | --- |
| Blurry / dark / glare / no sample | `PhotoRejected(reason)` → `retake()` |
| Not sorghum | `NotSorghum(lookAlike?)`; no result from this photo |
| Species unsure or no plant | `SpeciesUnsure`; never passed to matching |
| Colour card not found | `CalibrationFailed(reason)` |
| Model file missing, fails to load, or metadata invalid | Session starts with `isMeasuredOnlyMode = true` and `isSpeciesCheckAvailable = false`; both are shown on `ChoosingPhotoType` and `ResultReady`. Learned traits are absent, not guessed. |
| Model fails at run time (wrong outputs) | That photo continues measured-only; capabilities switch to measured-only for the rest of the session |
| Tables file missing | `StartupFailed(TABLES_MISSING)` |
| Tables invalid (schema, version, trait/state mismatch, zero rows) | `StartupFailed(TABLES_INVALID)` |
| Poor best match / indistinguishable cultivars | `ResultReady` with outcome `UNRECOGNIZED` or `GROUP` (decided in `reasoning`) |
| Photo readable by no trait reader | `NoTraitsRead` |

### Ports wired at startup

```kotlin
/** Native reads the bundled cultivars-vN.json. null = file not in the bundle. Parsing and validation are shared. */
fun interface CultivarTableSource { fun readCultivarTablesJson(): ByteArray? }

/** What the platform loaded at startup. Built once, on main, before the first screen. */
data class SessionAssets(
    val cultivarTables: CultivarTableSource,
    val imageModel: ImageModel?,        // null when the .tflite is missing or the interpreter failed to load
    val modelMetadataJson: String?,     // traits-vN.json; null when missing
)
```

The `IdentificationSession` constructor loads the tables (`loadCultivarTables`, PR #8) and the gate (`loadSpeciesGate`), and checks the metadata's trait catalogue against the tables. Its first state is `StartupFailed` or `ChoosingPhotoType`, so there is no second sealed "load result" type for Swift. PR #8's `readCultivarTablesJson(): ByteArray` becomes `ByteArray?` in S6a.
- iOS: `BundledCultivarTables` (reads `cultivars-vN.json` from the bundle) and `LiteRTImageModel` (ADR-0007); `BundledSpeciesModel` becomes the code that fills `SessionAssets`.
- Android: an asset-reading `CultivarTableSource`. `imageModel = null` until the Android LiteRT runner exists, so Android runs measured-only and says so.

## Migration
Each step is one PR and leaves both apps working.
- **S6a.1 Add SKIE (build only).** Add the plugin with the scoped config above and pin a version that supports our Kotlin version. Check that `ios/` still builds: enum interop changes how Kotlin enums look in Swift. Measure the framework link time before and after. No Kotlin changes.
- **S6a.2 Session pipeline in shared.** Needs PR #8 merged. Add `kotlinx-coroutines-core` (commonMain) and `kotlinx-coroutines-test` (commonTest). Add `SessionState`, `IdentificationSession`, `SessionSettings`, `BoardLayout`, `CapturedPhoto` and `SessionAssets`, and make `CultivarTableSource` return `ByteArray?`. `commonTest` gets one test per failure path, plus accumulation across two photo types, a correction that recomputes (and survives a later photo), `reset()` dropping an in-flight photo, and an event rejected in the wrong state, using a fake `ImageModel`, a hand-written table and a test dispatcher. No app changes. `CaptureFlow` is untouched.
- **S7 iOS screens.** `CaptureModel` becomes a thin `@MainActor @Observable` adapter: `.task { for await state in session.state { self.state = state } }`, `switch onEnum(of: state)`, and photo-type, processing and result screens that only render. The detached quality and species checks move out of Swift. Verify on a device (adapters and UI get no unit tests).
- **A2 Android.** `CaptureViewModel` holds the session, exposes `session.state`, calls `close()` in `onCleared`, and Compose renders it. `CaptureUiState` is deleted.
- After S7 and A2: `CaptureFlow` and `CaptureState` become `internal`.

## Consequences
- One state machine for both apps, with every rule in `shared/`. The iOS adapter loses its own photo-check orchestration, and the READY → capture decision moves into shared.
- Kotlin upgrades now wait on a SKIE release that supports the new version. The fallback (option 2 as an adapter in `session`) is noted above and needs no Kotlin type changes.
- The iOS framework link gets slower because SKIE compiles generated Swift. Scoping the features limits this; S6a.1 measures it. This matters on the current memory-constrained build machine.
- `shared/` gains kotlinx.coroutines. It is not network-capable. CLAUDE.md's dependency check still applies, so run the merged-manifest `INTERNET` check in A2.
- Once the apps use the session, a colour card is required for every photo, leaf included (§4.3). Phase 1 leaf photos without a card will then be rejected. This is a user-visible change, so it ships with S7/A2, not S6a.
- The SKIE features used (sealed, flow) are stable. The SwiftUI `Observing` helpers are a preview and are not used.

## Assumptions
- ASSUMPTION — confirm: a SKIE 0.10.x release supports Kotlin 2.2.10 (0.10.7 lists 2.2.20/2.2.21; no page names 2.2.10). If none does, bump Kotlin to 2.2.21 in S6a.1.
- ASSUMPTION — confirm: SKIE works with our static framework built by `embedAndSignAppleFrameworkForXcode`. The docs only say "a module with a `framework` block".
- ASSUMPTION — confirm: the `SealedInterop` and `SuspendInterop` feature names in the group config. Only `FlowInterop` appears in the configuration page example.
- ASSUMPTION — confirm with product owner: with no model, photos continue without the species gate in measured-only mode, labelled "species not checked". ADR-0006 says unsure samples never continue, but "unchecked" is a different case, and this keeps the phase 1 behaviour (`PhotoAccepted(Unavailable)`).
- ASSUMPTION — confirm: a later photo judged `NotSorghum` keeps the readings of earlier sorghum photos. The alternative is to invalidate the whole sample.
- ASSUMPTION — confirm: a user correction survives a later photo of the same type.
- ASSUMPTION — confirm: the colour card sits in a fixed slot inside the target frame, given by `BoardLayout` (see `calibrateWithColourCard`).
- ASSUMPTION — confirm: photos cross the boundary at most 2048 px on the long side (`PIPELINE_PHOTO_LONG_SIDE_PIXELS`, initial guess; about 9 MB RGB). That is enough for the card (about 1000 px) and the measured readers. Full-resolution crops for awns are decided with that learned trait.
- ASSUMPTION — confirm: parsing the tables on main at startup takes milliseconds for the v1 cultivar list. If not, move startup loading to the worker and start in a loading state.
