# ADR-0010: MobileNetV2 backbone, converted with TensorFlow 2.17

Status: Accepted · Date: 2026-10-30

## Context
ADR-0006 and ADR-0004 named MobileNetV3-Small as the backbone of the one on-device model.
Phones run its full-integer (INT8) TFLite export, and the ship bar (`model/`
`ExportSettings`) requires |float - INT8| top-1 accuracy <= 0.02 on the test split and
sorghum-vs-not test accuracy >= 0.90.

- diag-1 (MobileNetV3-Small, 2026-10-23): float 0.867, INT8 0.727 on test.
- v2-1 (MobileNetV3-Small minimalistic, ReLU and no squeeze-and-excitation, the variant
  meant for quantization; best checkpoint epoch 18): validation float 0.830, INT8 0.740,
  even with the TF 2.17 converter.
- On the v2-1 checkpoint, INT8 weights with float activations keep 97% top-1 agreement,
  int16 activations 94%, full INT8 80%. Keeping the layers with the worst activation
  outliers in float did not help (0.731 to 0.736 on 1,200 validation photos).
- Frozen ImageNet backbone plus a linear head trained on the same 6,000 training photos,
  scored on 1,200 validation photos (TF 2.17 converter, 2026-10-29):

  | Backbone | Float | INT8 | Top-1 agreement |
  |---|---|---|---|
  | MobileNetV3-Small minimalistic | 0.764 | 0.662 | 0.79 |
  | MobileNetV2 1.0 | 0.793 | 0.792 | 0.94 |
  | MobileNetV2 0.75 | 0.793 | 0.768 | 0.92 |

  So the INT8 loss already sits in the Keras MobileNetV3 ImageNet weights, before any
  fine-tuning.
- iPhone runtime: TensorFlowLiteSwift 2.17.0 is the last stable pod (ADR-0007). A model
  converted with TF 2.20 gave logits 3 to 12 output steps away from iOS's on the parity
  fixtures (bar: 2 steps).

## Options
1. **MobileNetV2 1.0 with post-training quantization.** About 5x the compute of
   MobileNetV3-Small (300 M multiply-adds), still a few milliseconds on an iPhone. No new
   tooling.
2. **Keep MobileNetV3-Small and add quantization-aware training.** The TF Model
   Optimization toolkit does not support Keras 3, so the fake-quant graph would be
   hand-written and maintained by us.
3. **Keep MobileNetV3-Small and keep some ops in float.** Did not help in the experiment
   above, and gives a mixed model on the phones.

## Decision
Option 1. The species head (and later trait heads) sit on MobileNetV2 1.0 with ImageNet
weights, fine-tuned from `block_12_expand` on (`TrainingSettings.first_fine_tuned_layer`).
Training runs on TensorFlow 2.20; `export` runs in a separate TensorFlow 2.17 environment
(the `export` extra) and refuses any other converter version
(`ExportSettings.converter_tensorflow_version`). Keras is 3.15.1 in both, so the checkpoint
loads the same way.

The `traits-vN.json` contract does not change: 224 px uint8 input with the backbone's
normalisation inside the graph, float logits out. `backbone` in the metadata names the
backbone.

## Consequences
- The model file grows from about 1 MB to about 2.5 MB, and inference costs more. Both are
  small on the target iPhones; the parity test on device checks the runtime.
- A CPU training epoch is slower: 0.38 s against 0.16 s per batch of 32 when fine-tuning
  from `block_12_expand`.
- Two TensorFlow environments to keep (train and export). When the iOS runtime moves past
  2.17, change `converter_tensorflow_version` and the `export` extra together, and re-run
  the iOS parity test.
- If a later trait head needs more accuracy than PTQ allows, revisit option 2.
