# Keep up: project status for the Android side

Last updated: **2026-10-21**. Add a dated entry to the [log](#log) whenever something
lands or a decision changes, and keep the sections above it current.

## 1. In one paragraph

An offline phone app that tells you **which sorghum cultivar** a sample is, from photos of
a leaf, panicle or grain on a plain board. First it checks the sample **is sorghum** with a
small on-device image model (MobileNetV3-Small). Then it reads visible traits (colours,
shapes, seed size) as probabilities and runs a naive Bayes model over genebank tables. It
returns the best matches with reasons, or "unrecognized". It runs on Android and iPhone.
All logic lives once, in Kotlin Multiplatform (`shared/`), and the native apps are thin
shells. The whole design is in [ARCHITECTURE.md](architecture/ARCHITECTURE.md).

## 2. Where things stand

| Area | State | Branch |
|---|---|---|
| Phase 1 capture (Android): live level + green guidance, auto-capture, quality check | Built and working | `main` |
| Phase 1 logic moved into `shared/` (KMP), images passed as `PixelImage` | Done (migration step 1) | `feature/kmp-shared` |
| Capture state machine moved from `CaptureViewModel` to `shared/session/CaptureFlow` | Done (step 2) | `feature/kmp-shared` |
| iOS app uses `Shared.framework` instead of Swift copies | In progress (step 3) | `feature/kmp-shared` |
| Species model ("is it sorghum?") training code in `model/` | Code written, 47 tests pass; training not run yet | `feature/model-species-head` |
| `shared/species`, `ImageModel` port, LiteRT runners | Not started (step 4) | — |
| Colour card calibration, trait readers, reasoning | Not started (steps 5-7) | — |

Migration steps (ARCHITECTURE.md section 8): 1 shared module, 2 session, 3 iOS on shared,
4 species gate, 5 calibration, 6 measured traits + reasoning, 7 learned traits.
**Steps 1-3 must not change behaviour.** If the app behaves differently after them, that
is a bug.

## 3. Android code map today (`feature/kmp-shared`)

| File | What it does | Has logic? |
|---|---|---|
| `app/.../MainActivity.kt` | Entry point, camera permission | No |
| `app/.../ui/CaptureScreen.kt` | Compose UI: preview, target frame overlay, one instruction | No |
| `app/.../ui/CaptureViewModel.kt` | Thin adapter: forwards events to `CaptureFlow`, maps `CaptureState` to `CaptureUiState`, keeps the accepted `Bitmap` | No (on purpose) |
| `app/.../camera/CameraSession.kt` | CameraX binding: preview, analysis (RGBA, 640x480, keep-only-latest), still capture | No |
| `app/.../camera/SampleCoverageAnalyzer.kt` | Per frame: crop to target, at most 160 px, convert, measure green coverage | Calls shared |
| `app/.../camera/FrameCropper.kt` | Crop `ImageProxy` to the target frame, downscale `Bitmap` | Geometry only |
| `app/.../camera/PixelImageConversion.kt` | **The one** `Bitmap` (ARGB) to `PixelImage` (RGB) converter, with a 2x2 test | Conversion only |
| `app/.../camera/TiltSensor.kt` | Gravity sensor (accelerometer fallback) to `DeviceTilt` flow | No |
| `shared/.../session/CaptureFlow.kt` | Capture state machine: guiding, checking, accepted, rejected, failures | Yes |
| `shared/.../capture/guidance/*` | Tilt to instruction, steady-hold timer (800 ms) | Yes |
| `shared/.../capture/sample/GreenCoverage.kt` | Excess-green plant detector, used live **and** after capture | Yes |
| `shared/.../capture/quality/PhotoQuality.kt` | No sample / too dark / glare / blurry at 640 px | Yes |
| `shared/.../imaging/PixelImage.kt` | Plain RGB image type crossing the native/shared boundary | Type only |

Diagrams of these flows: [docs/flows/](flows/README.md), especially 02, 03, 04 and 05.

## 4. Rules that matter when you touch Android

The full list is in [CLAUDE.md](../CLAUDE.md). These are the ones Android work trips over.

1. **No thresholds or decisions in `app/`.** If a line compares a measurement to a number,
   it belongs in `shared/`. ViewModels forward events and render state.
2. **Images cross into `shared/` only as `PixelImage`**: RGB, row-major, upright, no
   padding. Convert once, in `PixelImageConversion.kt`. A swapped channel or a missed
   rotation breaks Android/iOS parity without any error.
3. **One detector.** Live frames and the captured photo use the same `measureSampleCoverage`
   at different sizes (160 px live, 640 px quality check). Do not add a "fast" variant.
4. **Camera threading:** analysis on the camera executor, results posted to main, frames
   closed with `image.use {}`, `STRATEGY_KEEP_ONLY_LATEST`. Never buffer frames.
5. **Offline:** `INTERNET` and `ACCESS_NETWORK_STATE` are removed in the manifest
   (`tools:node="remove"`), and `allowBackup="false"`. After adding any dependency, check
   `app/build/intermediates/merged_manifest/` for `INTERNET`.
6. **Portrait only.** The tilt maths and frame mapping assume it.
7. **Logic changes need both suites green**: `./gradlew test :shared:allTests`, plus the iOS
   tests if iOS-visible logic changed.

## 5. Build, run, test

```sh
./gradlew test :shared:allTests   # Android + shared tests (JVM and iOS simulator)
./run.sh [AvdName]                # build, install and launch on an emulator or device
cd model && uv sync --python 3.12 && uv run pytest   # model/ tests (Python)
```

Adapters and UI have no unit tests, so check them on a device.

## 6. What is coming for Android

In order. Items marked *ready* can start now.

1. **Review the KMP PR** (`feature/kmp-shared`) on a real device: guidance, auto-capture and
   rejections must behave exactly as on `main`. *Ready once the PR is open.*
2. **Species gate on Android** (step 4; iOS goes first, then Android):
   - An `ImageModel` implementation using LiteRT: load `traits-vN.tflite` from assets once,
     feed the uint8 input, return `Map<HeadId, FloatArray>`. No preprocessing in Kotlin
     Android code; `shared/` does it from `traits-vN.json`.
   - An asset loader that hands the model and JSON bytes to `shared/`.
   - UI states to render: "not sorghum" (with the look-alike name), "unsure, retake", and
     "measured-traits-only mode" when the model fails to load.
   - The parity test: run the fixtures in `shared/src/commonTest/resources/species/`
     through LiteRT on Android and compare with `expected.json`.
   - Check the merged manifest after adding LiteRT: still no `INTERNET`.
   - See [flow 06](flows/06-species-gate.mermaid).
3. **Module rename** `app/` to `androidApp/{ui,platform}` (target layout). It is not
   scheduled; do it as its own behaviour-neutral PR.

## 7. The species model, in short

Details in `model/README.md` on `feature/model-species-head`.

- **Classes** (output order): sorghum_bicolor, johnson_grass, maize, sugarcane,
  pearl_millet, finger_millet, other_grass, other_plant, no_plant. Johnson grass counts as a
  named look-alike, not sorghum.
- **Model I/O:** 224x224 RGB uint8 in, float logits out. `traits-vN.json` holds the input
  quantization, class order and groups, temperature, sorghum threshold and evaluation
  numbers.
- **Data problem:** commercially licensed iNaturalist photos are thin (334 sorghum, 217
  maize, 29 sugarcane, 11 pearl millet, 4 finger millet observations). **We need our own
  photos** of millets, sugarcane and empty boards (`no_plant`) before a first model can
  train. If you are near fields, photos help. One folder per plant or plot.

## 8. Open questions and decisions needed

| Question | Why it matters | Owner |
|---|---|---|
| **Licence policy conflict:** ARCHITECTURE.md section 2 allows non-commercial (NC) data for a research app, but `model/` was built commercial-safe only (CC0/BY/BY-SA, decided 2026-10-21). Which one holds? | NC would add many more iNaturalist photos | Product owner |
| Does the species gate run on the board photos or on a separate whole-plant photo? | Changes what users photograph and what data we collect | Product owner |
| Oldest Android device to support? | Sets the live-analysis performance budget | Team |
| Which named cultivars and regions does v1 target? | Sets tables and priors | Product owner |

## 9. How we work

- Each stream has its own branch, **git worktree** and PR, so parallel work (including
  Claude sessions) never shares a checkout. See [flow 11](flows/11-team-workflow.mermaid).
- One pipeline module per PR where possible. Never mix a move into `shared/` with a
  behaviour change.
- Decisions go into `docs/architecture/adr/`. If CLAUDE.md and ARCHITECTURE.md disagree,
  ARCHITECTURE.md wins, and CLAUDE.md is fixed in the same change.

## Log

Newest first. One line per change that someone on Android should know about.

- **2026-10-21:** `model/` species-head pipeline written (`feature/model-species-head`):
  classes, iNaturalist downloader, grouped splits, Keras training, INT8 export, calibration.
  Not trained yet (no data, and the dev disk is full).
- **2026-10-21:** Capture state machine moved to `shared/session/CaptureFlow`;
  `CaptureViewModel` is now a thin adapter (`feature/kmp-shared`).
- **2026-10-21:** Phase 1 logic moved to `shared/` and images passed as `PixelImage`
  (`feature/kmp-shared`).
- **2026-10-21:** iOS app adds a `CVPixelBuffer` to `PixelImage` converter and starts linking
  `Shared.framework` (`feature/kmp-shared`, in progress).
- **2026-10-19:** Target architecture and ADR-0001 to 0006 written; species gate added
  before cultivar matching (ADR-0006).
