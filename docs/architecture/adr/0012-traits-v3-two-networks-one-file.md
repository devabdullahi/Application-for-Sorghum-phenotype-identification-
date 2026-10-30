# ADR-0012: traits-v3 packs the species and basic-race networks into one model file

Status: Accepted · Date: 2026-10-30

## Context
ADR-0006 and CLAUDE.md ("`ImageModel`") define one LiteRT model per app: one `.tflite`, run
once per photo, with one output per head, and `shared/` picks each head by `outputIndex`. The
plan was for every head to sit on one shared backbone.

The second output to ship is the experimental basic-race output basic-race-v1 (#37, locked in
#44). It was fine-tuned from the species backbone, from `block_12_expand` on, so it carries its own
copy of those backbone layers. Putting it as a head on the species network would mean training
and scoring a new model, and #45 asks for delivery only.

Facts (2026-10-30, TF 2.17.1 exports):
- traits-v2 (species) is 2,719,192 bytes and basic-race-v1 is 2,713,712 bytes. They have the
  same graph shape (183 tensors, 72 operators, 9 operator codes) and the same uint8
  224 x 224 x 3 input with scale 1 and zero point 0.
- Each model's test result was locked on its own INT8 file. Re-converting a combined Keras
  model would re-calibrate the activation ranges of both networks on a new representative set.
  That changes both models' INT8 outputs and voids both locked evaluations.

## Options
1. **One file, two networks.** Merge the two converted flatbuffers into one subgraph that
   reads one input tensor and has two outputs. This copies tensors, buffers and operators and
   re-converts nothing.
2. **Two model files.** This changes the `ImageModel` port (one runner per file) and the
   asset contract.
3. **Species only.** Ship traits-v2 again and document race as not delivered.

## Decision
Option 1. `model/sorghum_model/model_bundle.merge_models` performs the merge, and
`bundle_export` writes traits-v3 with its metadata and fixtures. Output 0 is `species` and
output 1 is `basicRace`, and `headOrder` in `traits-v3.json` records that order. The bundle
step refuses to write unless every merged output is bit-identical to its source model. It
checks all 1,293 basic-race validation and test photos and the 12 species fixtures. So the
species and basic-race evaluations carry over unchanged.

The `ImageModel` port, the input spec and `schemaVersion` 1 stay as they are. `heads.basicRace`
is an optional head. A reader that does not know a head ignores it, the same way it ignores
unknown keys.

## Consequences
- The file doubles to 5.43 MB, and inference runs both networks: 5.8 ms against 2.8 ms
  single-threaded on the development Mac with XNNPACK. Inference runs once per captured photo,
  not on live frames, so the R3 live budget is not affected. A real-iPhone timing is still open.
- `shared/` reads the basic-race output with `readBasicRace` from the same model call that the
  species gate used. The output is marked experimental in the metadata and in every reading,
  and `shared/` refuses a head that misses its goal without that mark. Nothing gates on it, and
  no UI shows it yet.
- Later learned trait heads should still share one backbone (ADR-0004). Packing whole networks
  is an exception for outputs that cannot share a backbone without retraining. Each packed
  network adds about 2.7 MB.
- The merge supports single-subgraph models with one input only. A model with control flow, or
  inputs that differ in type, shape or quantization, is refused.
