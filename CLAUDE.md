# Project Instructions

Always follow the rules in coding_instructions.md:

@coding_instructions.md

The rules below are specific to this repo. They add to coding_instructions.md and do not replace it.

## Project context

- Offline mobile app that identifies sorghum cultivars from leaf, panicle and grain photos. It reads visible traits (IBPGR/ICRISAT descriptors) as probabilities over descriptor states, then runs a naive Bayes network (Genesys tables) to return the best matches with reasons, or "unrecognized".
- Pipeline: capture + guidance, then quality check, then colour correction (colour card, mm scale), then trait reading (measured + learned), then reasoning + result.
- Target architecture: `docs/architecture/ARCHITECTURE.md`. Decisions: `docs/architecture/adr/`. Phase 1 capture design: `phase1_overview.md`. If this file disagrees with ARCHITECTURE.md, ARCHITECTURE.md wins. Fix this file in the same change.
- Today only phase 1 exists: its logic is in `shared/` (migration step 1), the Android app is in `app/` and a temporary Swift port is in `ios/`. Everything else below is the target, and new code must already follow it.

## Module map and dependency direction

| Today | Target | Holds |
|---|---|---|
| `shared/.../capture/{frame,guidance,quality,sample}` | `shared/src/commonMain/kotlin/com/sorghum/{imaging,capture,segmentation,calibration,traits,reasoning,session}` | All logic |
| `app/.../ui`, `app/.../camera`, `MainActivity` | `androidApp/ui`, `androidApp/platform` | Compose, CameraX, gravity sensor, LiteRT runner, asset loader |
| `ios/SorghumCapture` (links `Shared.framework`; Swift port removed) | `iosApp/UI`, `iosApp/Platform` | SwiftUI, AVFoundation, Core Motion, LiteRT runner, asset loader |
| (none) | `model/` | Training, INT8 export, Genesys table builder, test fixtures |

- Allowed: presentation -> `session` only. Platform adapters -> `session` + boundary types. `session` -> domain modules. Domain -> `imaging`. `imaging` -> Kotlin stdlib only.
- Domain graph: `capture` -> `segmentation`; `traits` -> `segmentation`, `calibration`. Everything uses `imaging`. `capture` and `traits` never import each other, and no cycles are allowed.
- `reasoning` never sees pixels. Its inputs are trait estimates, tables and priors. This is why a user correction can re-run reasoning alone.
- `shared/` imports no `android.*`, `androidx.*`, `platform.*`, CameraX, AVFoundation or LiteRT. Check with `grep -rE "^import (android|androidx|platform\.|org\.tensorflow|com\.google\.ai)" shared/src/commonMain`. Expect no output.
- Per-platform capabilities are ports (Kotlin interfaces) defined in `shared/` and implemented natively at startup: `ImageModel`, `CultivarTableSource`. Do not use `expect/actual` for domain behaviour.
- Native code has no thresholds, formulas or decisions. If a line compares a measurement to a number, it belongs in `shared/`. UI renders `SessionState` and forwards events. ViewModels and `CaptureModel` are thin adapters to `session`.
- Do not add new logic to `ios/SorghumCapture/{Frame,Sample}`. New domain code goes in Kotlin in `shared/`. Until iOS consumes `shared/` (migration step 3), a Swift copy must be a 1:1 port with mirrored tests.
- No `utils/`, `common/` or `helpers/` packages. Name packages after the module they belong to.

## Boundary contracts

Keep the KMP API plain (ADR-0003): data classes, enums, `ByteArray`, `List` and `Map` in, results out. `SessionState` is the only sealed hierarchy exposed to Swift, through SKIE or flat fields. Do not expose `Flow` or suspend functions without SKIE.

- **`PixelImage(width, height, rgb: ByteArray)`**: row-major, 3 bytes per pixel (R, G, B), no alpha, no row padding, already upright. `init` requires `rgb.size == width * height * 3`. Each platform converts its frame once, in one adapter function: `ImageProxy`/`Bitmap` (ARGB) on Android, `CVPixelBuffer` (BGRA) on iOS. Each converter gets a test with a known 2x2 image, because a swapped channel or a missed rotation breaks parity silently.
- **Sizes**: live frames are at most 160 px on the long side, and the quality check runs at 640 px. Thresholds depend on these sizes. Keep them as named constants next to the settings they affect (`QUALITY_CHECK_LONG_SIDE_PIXELS`).
- **Rects**: `NormalizedRect` holds fractions of the upright image, origin top-left, y down. `PixelRect` has exclusive right and bottom. Preview-to-image mapping lives in one place per platform (`FrameMapping.kt` today). Do not repeat that math in camera code.
- **`DeviceTilt`**: degrees. (0, 0) means flat, screen up. Positive pitch means the top edge is raised and positive roll means the right edge is raised. Convert Core Motion to this convention in the iOS adapter.
- **Units**: lengths are mm after calibration and px before. Put the unit in the name (`seedLengthMm`, `longSidePx`). Inside `shared/`, colours after calibration are linear sRGB 0-1, and the name says so (`correctedLinearRgb`). Durations are `Long` ms from a monotonic clock that the caller passes in. `shared/` never reads a clock.
- **`TraitEstimate`**: a probability per descriptor state, using the catalogue's state codes, every value > 0, sum = 1 within 1e-6. Continuous traits (seed size) carry value + uncertainty and are converted to state probabilities before reasoning. A trait never reports a bare state.
- **`ImageModel`** (ADR-0006): one LiteRT model with several heads (species now, traits later). Takes a `PixelImage` already cropped and at model input size, and returns `Map<HeadId, FloatArray>`. `shared/` applies preprocessing, maps the species head to `SpeciesEstimate` and trait heads to `TraitEstimate`s and applies calibration temperatures. The native runner only loads the file and calls the interpreter.
- **Assets**: `traits-vN.tflite` and `traits-vN.json` share N. The JSON holds the input spec, trait ids, state order and temperatures. `cultivars-vN.json` holds the schema version, the data version and the Genesys CC BY-SA attribution. `shared/` validates both at load and refuses a trait-catalogue mismatch.

## Domain rules that must not drift

- **Thresholds live in `*Settings` data classes**, each with a default, KDoc saying why that value, and `require` range checks in `init`. Follow `GreenDetectionSettings`, `GuidanceSettings` and `QualitySettings`. Mark untuned defaults as "initial guess, tune on real photos". Never put a bare threshold literal in pipeline code.
- **One detector for live and post-capture.** Both call the same `segmentation` function at different resolutions, so "the sample is present" means the same thing in both. Do not add a "fast" variant.
- **Guidance gives one instruction at a time**, in fixed priority: level, then sample, then hold (800 ms). A new check takes a slot in `evaluateGuidance` and does not get its own message channel.
- **No hard zeros.** Apply the per-state noise floor to every CPT row and every trait estimate. One misread trait must not veto the true cultivar.
- **"Unrecognized" is a result.** When the best match fits poorly, return it with the compatible group. When several cultivars share a trait profile, return them as a group. Never force the argmax.
- **Corrections recompute.** `correctTrait` replaces that trait's estimate with a near-certain one (floor still applies) and re-runs reasoning from the stored estimates. It never re-runs image work and never patches the previous posterior.
- **Explanations come from the posterior's own numbers** (the traits that moved the ranking most). Never write them separately.
- **Failure behaviour is fixed by ARCHITECTURE.md section 4.3.** No colour card means reject. A missing model means measured-only mode, announced in the UI. Invalid tables mean a startup error. Never guess a learned trait.
- **Offline and private.** No networking code, HTTP clients, analytics, crash reporting or remote config. Photos stay in memory unless a feature explicitly adds on-device storage. Android keeps `INTERNET` and `ACCESS_NETWORK_STATE` removed with `tools:node="remove"` and `allowBackup="false"`. After adding any dependency, check `app/build/intermediates/merged_manifest/` for `INTERNET`. iOS adds no network entitlements or ATS keys.
- **Portrait only on both platforms.** The tilt math and frame mapping assume it.

## Parity (same photo, same answer)

- Every rule has one implementation, in `shared/`. While the Swift port exists, its defaults must equal the Kotlin defaults, and each Kotlin test has a mirrored XCTest with the same fixture values (`GreenCoverageTest.kt` and `GreenCoverageTests.swift`).
- Fixtures (images, expected coverage, quality verdicts, trait estimates, posteriors) live in `shared/src/commonTest/resources` and are produced by `model/`. Parity tests on both platforms read the same files. Tolerances: 1e-4 for fractions, 1e-6 for probabilities. Expect Float vs Double differences until the port is removed.
- The model parity test runs the same fixtures through LiteRT on Android and on iOS and compares per-trait outputs (risk R7).

## ML hygiene (`model/`)

- **Versioning**: bump N whenever weights, state order, preprocessing or tables change. Show the model and table versions in the result details.
- **Preprocessing is defined once**, in `traits-vN.json`, and applied in `shared/`. A golden test checks that the shared preprocessing of a fixture equals the training pipeline's tensor.
- **Quantization parity**: before shipping an INT8 model, compare it with the float model per head on the held-out split, and record the deltas in the metadata. Each learned trait is gated by held-out accuracy (R6).
- **Calibration**: fit temperatures per head after quantization, on validation data, and report ECE. Naive Bayes needs honest probabilities (R4).
- **Splits** are by plant, plot or accession, never by image. Commit the split manifest.
- **Label provenance**: each label records its source (accession, annotator, date). Unverified labels are excluded. Datasets stay out of git. Only manifests and checksums are committed.

## Concurrency and camera

- Frame analysis runs on the camera's background executor or queue. Results are posted to main, and guidance state has a single owner on main.
- Drop late frames (`STRATEGY_KEEP_ONLY_LATEST` / `alwaysDiscardsLateVideoFrames = true`). Never buffer frames.
- Budget: live green coverage at 160 px must take under 5 ms per frame on the oldest target iPhone (R3). Measure this before moving the hot loop to Kotlin/Native.
- Release frames deterministically: `image.use {}` for `ImageProxy`, `defer` for `CVPixelBufferUnlockBaseAddress`.
- The post-capture pipeline (quality, calibration, traits, inference) runs on one background coroutine per photo in `session`, with a progress state. Re-reasoning after a correction may run on main.
- Shared domain functions are pure and synchronous. Stateful helpers state in KDoc which thread they belong to (see `SteadyHoldTimer`).

## Testing and commands

- Domain: every public function has `commonTest` tests built from hand-made pixel arrays. Test each threshold at, just below and just above its value.
- Reasoning: use a tiny hand-written table to test the noise floor (no zero posterior), unrecognized, groups, and correction-recompute.
- Adapters and UI get no unit tests. Keep them thin enough for that, and verify them on a device: `./run.sh [AvdName]` for Android, Xcode run for iOS.
- Commands (verified 2026-10-19):
  - Android and shared: `./gradlew test :shared:allTests` from the repo root (`allTests` runs `commonTest` on the JVM and the iOS simulator).
  - iOS: `cd ios && xcodegen generate && xcodebuild test -project SorghumCapture.xcodeproj -scheme SorghumCapture -destination 'platform=iOS Simulator,name=<device>'`. Get `<device>` from `xcrun simctl list devices available`. Run `xcodegen generate` after adding or removing Swift files, and never hand-edit `project.pbxproj`.
- A change to any logic present on both platforms is done only when both suites pass.

## Change scope and review checklist

- Migration steps 1-3 (ARCHITECTURE.md section 8) are behaviour-neutral. Never mix a move into `shared/` with a behaviour change. Do one pipeline module per change where possible.
- Leave `bugreport-*.zip`, `.idea/` and generated Xcode files out of logic changes.
- Before finishing, check:
  - [ ] No OS or LiteRT import in `shared/`, and no threshold or decision in native code.
  - [ ] New tunables are in a `*Settings` type with a default, a reason and `require` checks.
  - [ ] Trait outputs are `TraitEstimate`s with a floor, using catalogue state codes.
  - [ ] Units are in the names. Rects are normalized and upright. Images are `PixelImage`.
  - [ ] Live and post-capture share the same detector.
  - [ ] The Swift port (while it exists) is updated, and its tests are mirrored.
  - [ ] No network-capable dependency was added, and the merged manifest has no `INTERNET`.
  - [ ] Asset versions are bumped if the model, tables or state order changed.
  - [ ] `./gradlew test` passes, plus the iOS tests if iOS-visible logic changed.

## Adding a new trait end-to-end

1. Add the descriptor to the `traits` catalogue: id, IBPGR/ICRISAT state codes, photo type (leaf, panicle or grain), and method (measured or learned).
2. Measured: write a pure reader in `traits` that takes a calibrated `PixelImage` plus pixels-per-mm and returns a `TraitEstimate`. Its thresholds and noise model go in a `*Settings` type. Learned: add a head in `model/`, then retrain with grouped splits, quantize, check parity, calibrate, and bump `traits-vN` (state order, temperature).
3. Add the trait's CPT rows to `cultivars-vN.json` from Genesys, with the noise floor. Bump the version.
4. Tests: a boundary test for each threshold, a fixture image with its expected estimate, and a reasoning test showing the trait shifts the posterior as expected.
5. Expose the trait through `SessionState` for explanation and correction. Both UIs only render it.
6. If the trait needs a new photo type, boundary type or failure path, update ARCHITECTURE.md (and add an ADR if a decision changed).
