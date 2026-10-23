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

## Status (2026-10-23)

- Done: class definitions, downloaders for iNaturalist, GBIF, Wikimedia Commons and Flickr,
  importers for the Mendeley Data and Figshare (GrainSet) datasets, folder importer, grouped
  splits, calibration maths, metadata format, training and INT8 export code, unit tests.
- Verified: unit tests pass; every source except Flickr (no key yet) was smoke-tested against
  its live API on 2026-10-23.
- **Not yet run:** `train` and `export`. Expect small fixes on the first real run.
- **Short classes:** finger millet and `no_plant` (see [Data reality](#data-reality)).

## Decisions behind this code

- **Classes** (2026-10-21), in head output order (`sorghum_model/species_classes.py`):
  `sorghum_bicolor`, `johnson_grass`, `maize`, `sugarcane`, `pearl_millet`, `finger_millet`,
  `other_grass`, `other_plant`, `no_plant`. Johnson grass is a **named look-alike**, not
  sorghum: it is botanically *Sorghum* but not a crop cultivar. Each class has a group
  (`sorghum`, `lookAlike`, `otherPlant`, `noPlant`) that `shared/species` uses to decide.
- **Licences** (2026-10-23): CC0, CC BY, CC BY-SA, **CC BY-NC and CC BY-NC-SA**
  (`ALLOWED_LICENSES` in `manifest.py`), because the app is a non-commercial research tool
  (ARCHITECTURE.md section 2). **ASSUMPTION — confirm** before any commercial release: a
  commercial model would have to be retrained without the NC photos. No-derivatives (ND)
  licences, public-domain marks, GFDL-only files and unlicensed photos stay excluded. Every
  photo's attribution is kept in the manifest. The exported `traits-vN.json` lists the licence
  codes used under `trainingData.licenses` and sets `trainingData.nonCommercial` when any NC
  photo was used. Nothing else in the file changes, so the app's contract is unchanged.
- **Label quality differs by source.** iNaturalist research grade (two thirds of identifiers
  agree), GBIF human-identified records and the public datasets (labelled by their authors)
  count as verified. Wikimedia Commons categories and Flickr searches are **unreviewed**, and
  their `label_source` says so; review them or filter them with BioCLIP 2 before training.
- **Framework:** TensorFlow/Keras, for its built-in INT8 TFLite converter.
- **BioCLIP 2** label cleaning (recommended by the research) is a later, optional step.

## Photo sources

Each source has one module and one command, and writes its own manifest
(`manifests/species-<source>.csv`), so downloads can run in parallel. Every command is
resumable: files already on disk are not fetched again. All requests send a User-Agent naming
the project, are paced at about one per second and retry transient errors (`downloads.py`).

| Source | Command | Classes | Group (for splitting) | Key |
|---|---|---|---|---|
| iNaturalist (research grade) | `inat-download` | all plant classes | observer | none |
| GBIF occurrences (human-identified, not fossil; iNaturalist's dataset excluded) | `gbif-download` | crops, look-alikes, other grasses | recorder, else institution, else dataset | none |
| Wikimedia Commons categories | `commons-download` | all classes, incl. `no_plant` | uploader | none |
| Flickr search | `flickr-download` | `no_plant` only | owner | `FLICKR_API_KEY` |
| SorghumWeedDataset (Mendeley `4gkcyxjyss`, CC BY 4.0) | `mendeley-import sorghum-weed` | sorghum, other grass, other plant | block of 20 consecutive file numbers | none |
| Sorghum Disease Image Dataset (Mendeley `fgb3cmfrg2`, CC BY 4.0) | `mendeley-import sorghum-disease` | sorghum | disease + block of 20 file numbers | none |
| GrainSet sorghum / maize (Figshare, CC BY 4.0) | `figshare-import grainset-sorghum` / `grainset-maize` | sorghum, maize (kernels) | capture session | none |

Notes:

- **GBIF:** a photo's licence is its own media licence when it has one, else the record's
  (observation.org publishes CC BY-NC records with CC BY-NC-ND photos). Images come from
  GBIF's image cache at 500 px wide. Most millet images are **herbarium sheets**; the label
  source names the basis of record, so training can drop them if they hurt field accuracy.
- **Mendeley and Figshare:** each dataset is pinned to the version whose layout was checked,
  and its licence is read from the API before anything is downloaded. Files are checked
  against the published sha256 (Mendeley) or md5 (Figshare). The datasets publish no plant
  ids, so their grouping is a heuristic (`PublicDatasetSettings`).
- **GrainSet** zips are 7.4 GB (sorghum) and 6.0 GB (maize); a fixed sample of 3,000 kernels
  per class is extracted (`PublicDatasetSettings.grain_images_per_class`).
- **Sources that need a key:** only Flickr. Create a free key at
  <https://www.flickr.com/services/apps/create/> and `export FLICKR_API_KEY=...`; without it
  the command stops with that instruction. Pl@ntNet and observation.org photos already
  arrive through GBIF, so they need no separate client.

## Data reality

Upper bounds per class, counted on 2026-10-23 before per-photo licence checks, caps and
duplicates. iNaturalist: research-grade observations with an allowed photo licence. GBIF:
occurrences with images outside iNaturalist's dataset, split into human observations and
specimens (mostly herbarium sheets).

| Class | iNaturalist (no NC, 2026-10-21) | iNaturalist (with NC) | GBIF observations / specimens | Public datasets |
|---|---|---|---|---|
| Sorghum bicolor | 334 | 2,645 | ~665 / ~7,140 | 1,404 SorghumWeed, 7,167 disease, 3,000 grain |
| Johnson grass | 3,368 | 20,542 | ~800 / ~9,800 | |
| Maize | 217 | 2,468 | ~660 / ~3,470 | 3,000 grain |
| Sugarcane | 29 | 580 | ~80 / ~1,350 | |
| Pearl millet | 11 | 98 | ~8 / ~6,840 | |
| Finger millet | 4 | 46 | ~18 / ~1,360 | |
| Other grass (5 species) | 8,680 | 56,046 | ~4,000 / ~35,000 | 1,467 SorghumWeed grasses |
| Other plant (dicots) | millions | millions | not used | 1,441 SorghumWeed broadleaf weeds |
| No plant | none | none | none | Commons categories only (a few hundred) |

Downloads are capped per taxon (`--max-observations-per-taxon 3000`,
`--max-occurrences-per-taxon 2000`) and per record (3 and 2 photos). Training refuses to start
while any class has fewer than 50 train or 10 validation/test photos (`TrainingSettings`).
With NC photos, GBIF and the public datasets, every plant class should pass that bar, but
finger and pearl millet then rest mostly on herbarium sheets: their field-photo accuracy will
be weak until we add our own photos. **`no_plant` still needs our own photos** of the empty
board, soil and hands, the scenes the app actually sees.

## Setup

Needs [uv](https://docs.astral.sh/uv/). TensorFlow needs Python 3.11 or 3.12.

```sh
cd model
uv sync --python 3.12                 # data tools and tests (small)
uv sync --python 3.12 --extra train   # adds TensorFlow (~1.5 GB) for train/export
uv run pytest
```

## Workflow

Run all commands from `model/`. Photos go to `model/data/` (git-ignored), or to another
disk with `--data-root`. Manifests in
`model/manifests/` and the split in `model/splits/` **are committed**, so anyone can rebuild
the same dataset.

```sh
# 1. Download from the photo APIs (about 1 request/second each; resumable per class).
uv run sorghum-model inat-download
uv run sorghum-model gbif-download
uv run sorghum-model commons-download
FLICKR_API_KEY=... uv run sorghum-model flickr-download

# 2. Download and import the public datasets (licence checked from their API first).
uv run sorghum-model mendeley-import sorghum-weed
uv run sorghum-model mendeley-import sorghum-disease
uv run sorghum-model figshare-import grainset-sorghum
uv run sorghum-model figshare-import grainset-maize

#    Add a folder of our own labelled photos. Put it under the data root first, with one
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
| `species_classes.py` | Class list, order, iNaturalist taxa, GBIF taxa and Commons categories |
| `manifest.py` | One row per photo: path, class, licence, attribution, label provenance, sha256; licence policy |
| `downloads.py` | User-Agent, request pacing, retries, resumable checksum-verified downloads |
| `inat.py` | Research-grade iNaturalist photos |
| `gbif.py` | Human-identified GBIF occurrence photos, per-photo licence check |
| `commons.py` | Wikimedia Commons category photos, licence from `extmetadata` |
| `flickr.py` | Flickr search photos for `no_plant` (needs `FLICKR_API_KEY`) |
| `mendeley.py` | SorghumWeedDataset and Sorghum Disease Image Dataset |
| `figshare.py` | GrainSet sorghum and maize kernel archives |
| `dataset_layout.py` | Maps public-dataset files to `<class>/<group>/<file>` |
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
