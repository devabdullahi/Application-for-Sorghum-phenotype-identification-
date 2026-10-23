# `model/`: species head training (MobileNetV3-Small)

This package builds the on-device image model: a MobileNetV3-Small backbone with a
**species head** that answers "is this sorghum?" before any cultivar matching
([ADR-0006](../docs/architecture/adr/0006-species-gate-before-cultivar.md)). Learned trait
heads come later and share the same backbone and file
([ADR-0004](../docs/architecture/adr/0004-learned-traits-behind-port.md)).

It produces:

| Output | Goes to | Used by |
|---|---|---|
| `traits-vN.tflite` (INT8, uint8 input, float logits) | app assets (Android and iOS) | `ImageModel` LiteRT runners |
| `traits-vN.json` (input spec, classes, temperature, threshold, eval numbers) | next to the `.tflite` | `shared/species` |
| Parity fixtures (`*.png` at model input size + `expected.json`) | `shared/src/commonTest/resources/species/` | Android and iOS parity tests (risk R7) |

Nothing here ships in the app, and the app never uses the network. Only this workstation
tool downloads photos.

## Status (2026-10-21)

- Done: class definitions, iNaturalist downloader, folder importer, grouped splits,
  calibration maths, metadata format, training and INT8 export code, 47 unit tests.
- Verified: unit tests pass; `inat-download` and `split` ran against the live iNaturalist API.
- **Not yet run:** `train` and `export`. TensorFlow is not installed on the dev machine yet
  (disk full). Expect small fixes on the first real run.
- **Blocking a first model:** too few commercially licensed photos for some classes (see
  [Data reality](#data-reality)).

## Decisions behind this code (2026-10-21)

- **Classes**, in head output order (`sorghum_model/species_classes.py`): `sorghum_bicolor`,
  `johnson_grass`, `maize`, `sugarcane`, `pearl_millet`, `finger_millet`, `other_grass`,
  `other_plant`, `no_plant`. Johnson grass is a **named look-alike**, not sorghum: it is
  botanically *Sorghum* but not a crop cultivar. Each class has a group (`sorghum`,
  `lookAlike`, `otherPlant`, `noPlant`) that `shared/species` uses to decide.
- **Licences:** CC0, CC BY and CC BY-SA only, so the model could ship in a commercial app.
  CC BY-NC iNaturalist photos and CropAndWeed are excluded. Every photo's attribution is kept
  in the manifest. Note that ARCHITECTURE.md section 2 allows NC data for a research app;
  this conflict is open (see `docs/KEEP_UP.md`). Widening the policy means editing
  `COMMERCIAL_LICENSES` in `manifest.py`.
- **Framework:** TensorFlow/Keras, for its built-in INT8 TFLite converter.
- **BioCLIP 2** label cleaning (recommended by the research) is a later, optional step.

## Data reality

Research-grade iNaturalist observations with a commercial licence (checked 2026-10-21):

| Class | Observations |
|---|---|
| Sorghum bicolor | 334 |
| Johnson grass | 3,368 |
| Maize | 217 |
| Sugarcane | 29 |
| Pearl millet | 11 |
| Finger millet | 4 |

Training refuses to start while any class has fewer than 50 train or 10 validation/test
photos (`TrainingSettings`). To get there:

1. Import the open CC BY 4.0 sets from the research notes: SorghumWeedDataset (Mendeley
   `4gkcyxjyss`) and the Sorghum Disease Image Dataset (Mendeley `fgb3cmfrg2`) as sorghum
   positives, GrainSet sorghum and maize kernels (Figshare), and UQ panicle crops.
2. **Collect our own photos** of pearl millet, finger millet, sugarcane and `no_plant`
   (empty board, soil, hands). No public source covers them.

## Setup

Needs [uv](https://docs.astral.sh/uv/). TensorFlow needs Python 3.11 or 3.12.

```sh
cd model
uv sync --python 3.12                 # data tools and tests (small)
uv sync --python 3.12 --extra train   # adds TensorFlow (~1.5 GB) for train/export
uv run pytest
```

## Workflow

Run all commands from `model/`. Photos go to `model/data/` (git-ignored). Manifests in
`model/manifests/` and the split in `model/splits/` **are committed**, so anyone can rebuild
the same dataset.

```sh
# 1. Download iNaturalist photos (about 1 request/second; resumable per class).
uv run sorghum-model inat-download

# 2. Add a folder of labelled photos. Put it under model/data/ first, with one
#    subfolder per plant, plot or accession, so photos of one plant never cross splits.
uv run sorghum-model import-folder data/team/pearl_millet \
    --class pearl_millet --source team-photos --license cc-by \
    --attribution "Sorghum project team" --annotator "<name>" --labelled-on 2026-11-02

# 3. Split by group (iNaturalist observer, plot or accession), never by image.
uv run sorghum-model split

# 4. Train: frozen backbone, then fine-tune; keeps the best validation loss.
uv run sorghum-model train --run-dir runs/species-v1

# 5. Quantize, check parity, calibrate, then write the model, metadata and fixtures.
uv run sorghum-model export --run-dir runs/species-v1 --version 1 \
    --out-dir runs/species-v1/export \
    --fixtures-dir ../shared/src/commonTest/resources/species
```

## How the pieces fit

| Module | Job |
|---|---|
| `species_classes.py` | Class list, order and iNaturalist taxon ids |
| `manifest.py` | One row per photo: path, class, licence, attribution, label provenance, sha256 |
| `inat.py` | Research-grade, commercially licensed iNaturalist photos |
| `local_import.py` | Folders of public-dataset or team photos; an annotator is required |
| `splits.py` | Hash-based split by group; new photos never move an existing group |
| `preprocessing.py` | EXIF upright, centre square crop, bilinear resize to 224 px |
| `settings.py` | Every tunable value, with its reason and range checks |
| `train.py` | Keras MobileNetV3-Small, class-balanced weights, light augmentation |
| `export.py` | INT8 conversion, float-vs-INT8 parity, temperature, threshold, fixtures |
| `calibration.py` | Temperature fit, ECE, sorghum threshold choice |
| `metadata.py` | Builds and validates `traits-vN.json` |

### Contract with `shared/`

- **Input:** 224 x 224 RGB, uint8. `shared/` crops the centred square, resizes bilinearly,
  then quantizes each 0-255 value with `q = v / scale + zeroPoint`, taking both from
  `input.quantization` in the JSON. MobileNetV3's own normalization is inside the model.
- **Output:** one float logits vector per head. Species logits follow the class order in
  `heads.species.classes`.
- **Decision:** `shared/species` applies `softmax(logits / temperature)` and continues only
  when P(sorghum) >= `sorghumThreshold`. The threshold is the lowest one that reaches 97%
  sorghum precision on validation (`ExportSettings`, an initial guess).

### ML hygiene this code enforces

- Splits by group, never by image; the split manifest is committed.
- Unverified labels are excluded: iNaturalist research grade only, and imports need an
  annotator.
- INT8 is compared with float per head on the test split, and the numbers go into the
  metadata.
- The temperature is fitted after quantization, on validation; ECE is reported before and
  after.
- Bump N whenever weights, class order, preprocessing or tables change.
