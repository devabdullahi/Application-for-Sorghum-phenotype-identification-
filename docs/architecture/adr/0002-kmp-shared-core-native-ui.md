# ADR-0002: Kotlin Multiplatform shared core with native UI

Status: Accepted (from design doc) · Date: 2026-10-19

## Context
The app must run on Android and iPhone, offline. Phase 1 logic is pure Kotlin (`frame`, `guidance`, `quality`, `sample`) with JVM tests. A small Swift port of the green check already exists, showing the cost of keeping two copies of every rule in sync.

## Options
1. **Two native apps, logic duplicated** in Kotlin and Swift. No build tooling cost; every rule and threshold maintained twice; parity drift.
2. **KMP shared core + SwiftUI / Compose.** One copy of logic; native camera and UI; Swift sees Kotlin through an Objective-C bridge.
3. **Compose Multiplatform for UI too.** Less UI code; iOS UI less native; camera still native.
4. **Flutter / React Native.** Rewrite of working Kotlin; camera and pixel work through plugins/bridges.

## Decision
Option 2. All logic in `shared/`; native apps own UI, camera, sensors, and model execution only. KMP is Stable since Kotlin 1.9.20 (Nov 2023).

## Consequences
- Build setup cost (Gradle KMP + XCFramework into Xcode).
- Shared API must stay simple for Swift (plain data, sealed states; SKIE optional).
- Risk R3: Kotlin/Native performance of per-pixel loops must be measured on iPhone.
- Phase 1 scope (iOS excluded) is widened; migration steps 1–3 are behaviour-neutral.
