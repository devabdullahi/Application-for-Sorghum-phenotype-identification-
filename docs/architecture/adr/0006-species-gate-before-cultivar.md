# ADR-0006: Check "is this sorghum?" before identifying the cultivar

Status: Accepted (product owner, 2026-10-19) · Date: 2026-10-19

## Context
The product goal is a sorghum identifier. The trait pipeline (ADR-0001) assumes the sample is sorghum: shown a maize leaf or millet grain, it still returns the "closest" sorghum cultivars, or at best "unrecognized" without saying why. Species recognition is a different task from cultivar recognition: classes look clearly different, and public plant-photo datasets exist, so it does not need the labelled descriptor photos that learned traits need.

## Options
1. **No species check.** Rely on "unrecognized" from reasoning. Misleading results on non-sorghum samples.
2. **Species gate with a direct classifier (MobileNetV3-Small head), before trait reading.** Clear "not sorghum" answer; can ship before any trait model.
3. Species as one more trait in naive Bayes. Mixes a near-certain categorical fact into a model built for noisy descriptors; still runs the whole trait pipeline on non-sorghum photos.

## Decision
Option 2. After the quality check, a `species` step classifies the photo as **sorghum / look-alike (named) / other plant / no plant**, as a probability distribution. Only "sorghum" above a calibrated threshold continues to calibration, traits and reasoning; otherwise the user sees "not sorghum" (with the look-alike name when confident) or "unsure — retake".

- The species head shares the MobileNetV3-Small backbone with the later per-trait heads (ADR-0004): one `.tflite`, one runtime, heads added over time. (2026-10-30: the backbone is now MobileNetV2, because MobileNetV3-Small loses about 10 points to INT8; see ADR-0010.) (2026-10-30: traits-v3 also packs the separately fine-tuned basic-race network into the same file, as a second output; see ADR-0012.)
- Runs through the same `LearnedTraitModel`-style port, renamed `ImageModel`, with preprocessing in `shared/`.
- Classes and threshold are data in the model metadata, not code.
- Runs on iPhone and Android with the same model file and the same shared decision code; iOS is integrated first (LiteRT for iOS), Android next. A parity test checks both give the same species probabilities on shared fixtures.

## Consequences
- MobileNetV3 + LiteRT integration moves earlier: it is now migration step 4, before calibration.
- Needs a training set per photo type (leaf, panicle, grain on the board) for sorghum and look-alikes; public datasets help for leaves and panicles, grain may need our own photos.
- Weedy *Sorghum* species (e.g. Johnson grass, *S. halepense*) are botanically sorghum but not crop cultivars; class definition must decide where they go.
  - Resolved 2026-10-21: Johnson grass is a named look-alike class (`johnson_grass`), so the gate says "not sorghum (Johnson grass)". Full class list: `model/sorghum_model/species_classes.py`.
- Open: does the gate run on the board photos the app already takes, or on a separate whole-plant photo?
