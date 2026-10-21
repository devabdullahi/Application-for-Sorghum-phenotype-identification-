# ADR-0004: Learned traits run through a port backed by one LiteRT model

Status: Accepted; port renamed to `ImageModel` and species head added by ADR-0006 · Date: 2026-10-19

## Context
Some traits (waxy bloom, panicle shape, grain covering, awns, plumpness) need a learned classifier. LiteRT runs one `.tflite` on Android and iOS (Swift API, optional Core ML/Metal delegates). Kotlin cannot call LiteRT directly in common code.

## Decision
`shared/traits` defines `LearnedTraitModel` (`PixelImage` → per-trait outputs). Each native app implements it with LiteRT. Preprocessing (resize, normalization, colour space) and mapping outputs to `TraitEstimate` live in `shared/`, driven by the model's metadata JSON. One INT8 MobileNetV3-Small model with per-trait heads, versioned with its metadata.

## Consequences
- Native adapters are thin (tensor in, tensor out) and cannot diverge in preprocessing.
- A parity test runs shared fixtures through both runtimes and compares per-trait probabilities within tolerance.
- App works without the model (measured traits only), so ML can ship after the measured-trait pipeline.
