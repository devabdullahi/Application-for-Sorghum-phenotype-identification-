# ADR-0007: LiteRT on iOS through CocoaPods (TensorFlowLiteSwift 2.17.0)

Status: Accepted · Date: 2026-10-21

## Context
The iOS app needs a LiteRT (TensorFlow Lite) runtime to implement the `ImageModel` port for the species model. ARCHITECTURE.md section 10 left the install route open: CocoaPods, as the LiteRT quickstart documents, or Swift Package Manager.

## Options
1. **CocoaPods, `TensorFlowLiteSwift` 2.17.0** (latest stable, published by the TensorFlow authors). Documented route; needs `pod install` and the workspace.
2. Swift Package Manager. No official LiteRT package for this version was found; unofficial wrappers add a supply-chain risk.
3. Core ML conversion. Breaks "one model file for both platforms" and the parity test (R7).

## Decision
Option 1, pinned to exactly 2.17.0. `Podfile` and `Podfile.lock` are committed; `Pods/` and the workspace are generated. The workflow becomes `xcodegen generate && pod install`, then build `SorghumCapture.xcworkspace`. A `post_install` step builds the pods for the app's iOS 17 floor, because the pod still declares iOS 12.

## Consequences
- The native runner (`LiteRTImageModel`) only loads the file and runs the interpreter; preprocessing and decisions stay in `shared/` (ADR-0004).
- About 3-5 MB added to the app download. The library contains no networking code (checked 2026-10-21: no URLSession or network symbols, only documentation links in error messages).
- Revisit if an official SPM package appears, or when moving to the newer LiteRT runtime.
