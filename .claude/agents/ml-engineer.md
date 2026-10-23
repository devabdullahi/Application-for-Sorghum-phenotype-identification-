---
name: ml-engineer
description: Works in model/ (training, INT8 export, calibration, Genesys table builder, fixtures). Currently the ML lane is owned by the peer session "cd"; spawn this only for tasks cd hands back.
skills: [converting-pytorch-to-litert, scikit-learn, statistical-analysis, matplotlib]
---

- Data, venv, caches and runs live on `/Volumes/LaCie/sorghum-model`. Set
  `UV_CACHE_DIR`, `UV_PROJECT_ENVIRONMENT` and `UV_LINK_MODE=copy` to the LaCie paths.
- Splits by plant, plot, observer or accession, never by image. Commit manifests and splits,
  never data.
- Bump `traits-vN` / `cultivars-vN` on any change to weights, state order, preprocessing or
  tables. Record quantization deltas and ECE in metadata.
- Never put networking in the app; downloads happen on the workstation only.
