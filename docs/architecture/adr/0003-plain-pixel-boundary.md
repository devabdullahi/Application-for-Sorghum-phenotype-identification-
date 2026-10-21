# ADR-0003: Images cross into the shared core as plain RGB pixel arrays

Status: Accepted · Date: 2026-10-19

## Context
`Bitmap` (Android) and `CVPixelBuffer` (iOS) do not exist on the other platform. Phase 1 functions already take packed ARGB `IntArray`s; the Swift port takes `[RGBPixel]`.

## Options
1. `expect/actual` image type wrapping each platform's buffer. Zero copy; platform code leaks into every image function's tests.
2. **Plain `PixelImage(width, height, rgb: ByteArray)`, upright, row-major.** One copy per frame at the boundary; all image code pure and testable in `commonTest`.

## Decision
Option 2. Native adapters crop/downscale before copying where possible (live frames ≤160 px), so the copy is small.

## Consequences
- One conversion function per platform; must be tested for channel order (BGRA on iOS) and rotation.
- Full-resolution copies only when a trait needs them (awns).
