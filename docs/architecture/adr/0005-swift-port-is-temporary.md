# ADR-0005: The Swift green-check port in ios/ is temporary

Status: Accepted · Date: 2026-10-19

## Context
`ios/` contains a SwiftUI app with Swift ports of `GreenCoverage`, `TargetFrame` and the sample status rule, plus AVFoundation camera, preview mapping and pinch-to-zoom. It was built before the KMP decision to get the green check running on iPhone.

## Decision
Keep it as a working reference until `shared/` ships as an XCFramework. Then:
- Delete the Swift domain ports (`Sample/`, `Frame/`) and their tests; use `shared/`.
- Keep the camera, preview, zoom and screen code as the iOS platform adapter (move to `iosApp/`).
Until then, any change to green detection or target-frame rules must be made in both Kotlin and Swift, with matching tests.

## Consequences
- Short-term duplication, removed in migration step 3.
- The iOS live analysis benchmark (risk R3) is taken with the Swift port as baseline.
