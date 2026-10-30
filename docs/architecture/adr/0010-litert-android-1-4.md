# ADR-0010: LiteRT on Android through `com.google.ai.edge.litert:litert` 1.4.2

Status: Proposed (Android engineer, awaiting product owner) · Date: 2026-10-23

## Context
The Android app needs a LiteRT runtime to implement the `ImageModel` port for the species model, as ADR-0007 did for iOS. Google moved the Android runtime from `org.tensorflow:tensorflow-lite` (last release 2.17.0) to `com.google.ai.edge.litert:litert`. The current docs (developers.google.com/edge/litert/android, checked 2026-10-23) list `litert:2.3.0` and recommend the new `CompiledModel` API, with `Interpreter` kept for compatibility. The app must stay offline (ARCHITECTURE.md section 6) and ship 16 KB-aligned native libraries for targetSdk 36.

## Options
1. **`litert` 2.3.0** (latest). Its `litert-api` pulls in `com.google.android.play:ai-delivery` 0.1.1-alpha01 (Play services, Play asset delivery) and merges `FOREGROUND_SERVICE` and `FOREGROUND_SERVICE_DATA_SYNC` permissions. That is network-capable model download code that we do not use.
2. **`litert` 1.4.2** (latest 1.x, March 2026). Official artifact, no transitive dependencies, no manifest permissions, 16 KB-aligned `.so` files, same `org.tensorflow.lite.Interpreter` API as iOS's TensorFlowLiteSwift.
3. `org.tensorflow:tensorflow-lite` 2.17.0. Same version as iOS, but the old artifact name, no longer updated by Google.
4. Play services LiteRT (`play-services-tflite-java`). The runtime is delivered by Google Play, so it needs Play services and a download.

## Decision
Option 2, pinned to exactly 1.4.2, using the `Interpreter` API. `LiteRTImageModel` memory-maps `traits-vN.tflite` from assets (stored uncompressed through `androidResources.noCompress`) and only runs the interpreter. Preprocessing and decisions stay in `shared/` (ADR-0004).

## Consequences
- The Android and iOS runtimes are different builds (1.4.2 vs TensorFlowLiteSwift 2.17.0). The model parity test (risk R7) must compare their per-head outputs before the model ships.
- Before moving to LiteRT 2.x, check again that it no longer brings Play delivery code or permissions, and recheck the merged manifest for `INTERNET`.
- About 3-4 MB of native libraries per ABI in the APK.
