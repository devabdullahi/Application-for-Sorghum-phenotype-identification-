# `model/`: species head training (MobileNetV2)

This package builds the on-device image model: a MobileNetV2 1.0 backbone with a
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

## Status (2026-10-30)

- Done: class definitions, downloaders for iNaturalist, GBIF, Wikimedia Commons and Flickr,
  importers for the Mendeley Data and Figshare (GrainSet) datasets, folder importer, grouped
  splits, calibration maths, metadata format, training (resumable) and INT8 export code,
  unit tests. Manifests and the split are committed.
- Runs so far (test split, INT8, TF 2.17 converter unless noted). **v2-3 meets the ship bar**
  and is exported as `traits-v2`:

  | Run | Backbone | Sorghum-vs-not | Float / INT8 9-class |
  |---|---|---|---|
  | diag-1 | MobileNetV3-Small (TF 2.20) | 0.671 | 0.867 / 0.727 |
  | v2-1 | MobileNetV3-Small minimalistic | 0.765 | 0.780 / 0.693 |
  | v2-2 | MobileNetV2 1.0 | 0.857 (validation 0.936) | 0.842 / 0.810 |
  | **v2-3** | MobileNetV2 1.0, corrected split | **0.932** (validation 0.941) | 0.877 / 0.865 |

  v2-1 and v2-2 were scored with today's threshold rule. v2-2 was evaluated on a
  **defective split**: 1,499 Sorghum Disease photos chained into one near-duplicate group,
  all in test (see `SplitSettings`). v2-3 was trained and evaluated once on the corrected
  split, which was frozen before training. v2-3 test details: 6,088 photos (43% sorghum),
  sorghum precision 0.938 and recall 0.902, threshold 0.199, temperature 1.685, ECE 0.058
  before and 0.013 after temperature scaling, INT8 top-1 agreement with float 0.960.
- **Short classes:** finger millet and `no_plant` (see [Data reality](#data-reality)).
- Long jobs on this Mac: a process started from a non-interactive shell can be moved to the
  macOS background band and slow down 10x; `taskpolicy -B -p <pid>` lifts it.

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
- **Label quality differs by source**, and every manifest row has a `label_status`
  (`verified` or `unreviewed`). iNaturalist research grade (two thirds of identifiers agree),
  GBIF human-identified records and the public datasets (labelled by their authors) are
  `verified`. Wikimedia Commons categories and Flickr searches are `unreviewed`. **`split`,
  `train` and `export` drop unreviewed rows**; `review-labels` can verify them.
- **BioCLIP 2 review** (`review-labels`, `label_review.py`). **ASSUMPTION — confirm:** a
  zero-shot BioCLIP 2 (imageomics/bioclip-2) agreement counts as label verification. A plant
  row is verified when BioCLIP's top class is the row's class with probability >= 0.5; a
  `no_plant` row when the summed probability of all plant classes is < 0.2 (prompts "bare
  soil", "wooden board", "human hand", ...). Both thresholds are initial guesses in
  `LabelReviewSettings`. The verdict is appended to `label_source` ("bioclip-2 agreement
  p=0.91"); rows BioCLIP disagrees with stay unreviewed.
- **Migration rule (temporary):** manifests written before `label_status` existed are read
  with `commons` and `flickr` rows as unreviewed and every other source as verified
  (`LEGACY_UNREVIEWED_SOURCES`). Drop the rule once every committed manifest has the column.
- **GBIF portals:** Pl@ntNet's "automatically identified occurrences" dataset is **skipped**:
  GBIF lists it as human observation, but its names come from Pl@ntNet's classifier alone.
  Pl@ntNet "observations" and observation.org records are kept and named in `label_source`.
- **Duplicates across sources:** Commons files imported from iNaturalist or Flickr are
  skipped on download. At split time a 64-bit dHash finds near-duplicates across all sources
  except GrainSet and the Sorghum Disease dataset (Hamming distance <= 4, `SplitSettings`;
  their lab close-ups hash alike, so they are exempt): same-class copies put their groups together into one
  group, copies with different labels are both dropped (listed as `excluded` in the split
  manifest).
- **Ship bar** (`ExportSettings`): held-out sorghum-vs-not accuracy >= 0.90,
  |float - INT8| accuracy <= 0.02, a model that loads under XNNPACK, and conversion with
  TensorFlow 2.17 (the iPhone runs TensorFlowLiteSwift 2.17.0; a TF 2.20 conversion failed
  the iOS parity test on 2026-10-23). `export` refuses (exit 1, nothing written) below the
  bar, unless `--allow-below-bar`, which is for diagnostic exports only and sets
  `belowBar: true` in the metadata.
- **Backbone** (2026-10-29): MobileNetV2 1.0 (ImageNet weights), fine-tuned from
  `block_12_expand` on (`TrainingSettings`). The Keras MobileNetV3-Small weights lose about
  10 points to full-integer quantization before any fine-tuning: frozen backbone plus a
  linear head on 6,000 of our training photos scored, on 1,200 validation photos, float
  0.764 / INT8 0.662 for MobileNetV3-Small minimalistic and 0.793 / 0.792 for MobileNetV2
  1.0. Weight-only INT8 kept 97% top-1 agreement, so the loss is in the activations.
- **Sorghum threshold** (2026-10-29): the most accurate threshold on validation among those
  with at least 95% validation sorghum precision (`ExportSettings.min_sorghum_precision`).
  It replaced "the lowest threshold with 97% precision", which stopped too many real sorghum
  photos for the accuracy bar. **ASSUMPTION — confirm** the 95% floor.
- **Framework:** TensorFlow/Keras, for its built-in INT8 TFLite converter. Training runs on
  TensorFlow 2.20 (`train` extra) and export on 2.17 (`export` extra); Keras is 3.15.1 in
  both, so the checkpoint loads the same way.

## Photo sources

Each source has one module and one command, and writes its own manifest
(`manifests/species-<source>.csv`), so different sources can download in parallel. Every
command is resumable: files already on disk are not fetched again, a half-downloaded file
continues where it stopped, and manifest rows are saved every 200 photos and whenever a run
ends. All requests send a User-Agent naming the project, are paced at about one per second,
retry transient errors and honour a 429 `Retry-After` (`downloads.py`).

**Run one process per source, and so one per host.** Pacing is per process, so two runs
against one API would double the rate. A lock file next to the manifest
(`species-<source>.csv.lock`) refuses a second process on the same source; a lock left by a
killed process is taken over automatically.

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
- **GrainSet grouping** was checked on the real archives (2026-10-23): 102,750 sorghum
  kernels in 3,316 capture sessions (12-55 kernels each) and 19,000 maize kernels in 3,324
  sessions (1-15). Groups are capture sessions, never single kernels.

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

## Cultivar data (2026-10-30)

Cultivar-labelled photos have their own manifest format (`cultivar_manifest.py`): the label
is an accession number, not a species class. Survey of sources, metric and plan:
[ADR-0011](../docs/architecture/adr/0011-cultivar-accuracy-target.md) (draft).

- `grin-download`: GRIN-Global's sorghum seed/panicle photos (USDA-ARS, public domain;
  9,394 images, 8,965 accessions, 11 plantings; 9,393 downloaded, one is a 404). Rows go to
  `manifests/cultivar-grin.csv`. GRIN's server answers slowly (about 6 s per image), so a
  full run takes most of a day; it is resumable.
- `grin-descriptors`: GRIN's race and trait observations for every photographed accession,
  mapped to IBPGR state codes (`grin_descriptors.py`), in
  `manifests/cultivar-grin-descriptors.csv`. Pages are cached, so a rerun fetches nothing.
- `cultivar-split`: writes `splits/cultivar-grin-v1.csv` and
  `splits/cultivar-grin-v1-summary.txt`. Per photo: `accession_split` (all photos of an
  accession together; for trait heads and the race model), `planting_split` (one planting
  per accession held out; for cross-planting matching), and `race` or `race_exclusion`.
  It drops exact repeated manifest rows, refuses two different rows with one source id,
  and fails if an accession or an image file is in two accession splits (checked on the
  written file). The summary reconciles the images GRIN lists, the images downloaded, the
  descriptor coverage, the race exclusions and the support per race and split.

```bash
uv run sorghum-model grin-download --data-root /Volumes/LaCie/sorghum-model/data/cultivar
uv run sorghum-model grin-descriptors
uv run sorghum-model cultivar-split
```

### Race labels and exclusions (`cultivar_races.py`)

An accession gets a scored race only when every GRIN race observation names the same one of
the fifteen Harlan & de Wet races (GRIN codes 01-15). Excluded accessions keep their photos
in the split (trait heads still use them) but are never trained on or scored by the race
model:

| `race_exclusion` | Values | Why |
|---|---|---|
| `no-race-observation` | (none) | GRIN has no race for the accession |
| `race-unknown` | Unknown (17) | GRIN itself does not know the race |
| `not-a-race` | Shattercane (16), Mixed, Breeding line | weedy form, mixed seed lot, pedigree status: not one race |
| `unmapped-value` | anything else | a value GRIN added later; map it before scoring |
| `conflicting-observations` | e.g. Durra + Durra-bicolor | plantings disagree; choosing one would be a guess |

Final counts (2026-10-30, `splits/cultivar-grin-v1-summary.txt`): 6,462 accessions / 6,715
images scored; excluded 2,204 no-race-observation, 6 race-unknown, 197 not-a-race (Mixed
182, Shattercane 13, Breeding line 2), 95 conflicting-observations, 0 unmapped-value.

Trait-mapping assumptions still to confirm (`grin_descriptors.py`): Straw glume -> IBPGR
White, Colourless midrib -> White, Lax panicle -> 1 "Very lax".

Known gap: GRIN lists an accession with several images as one row per image, but each row's
image cell shows the first image, so only the first image of those accessions is downloaded
(the repeats are dropped). Fetching the others needs the NOTE column's paths.

### Race model plan (T4, #24)

Not trained yet: training waits for the shared MobileNetV2 backbone
(`feature/species-model-v2`, ADR-0010) and for the CPU slot.

1. **Data.** Photos with a `race` in `splits/cultivar-grin-v1.csv`, split by
   `accession_split` (never by image; no accession or file crosses splits). Excluded labels
   are neither trained on nor scored.
2. **Model.** A race head (softmax over the scored races present in train) on the shared
   MobileNetV2 backbone, same input spec and preprocessing as the species head. Class
   weights balance races (support is very uneven). Augmentation must not hide traits that
   define race (no hue shift; mild crops only, panicle and spikelet shape must stay).
3. **Planting shortcut check.** Plantings differ in board, light and year, and race mix
   differs per planting. Report accuracy per planting and a planting-only baseline (predict
   the most common race of the photo's planting); the model must beat it clearly.
4. **Calibration.** Temperature fitted on validation after INT8 quantization
   (`calibration.py`), ECE reported. The group rule needs honest probabilities.
5. **Answer rule.** `race_evaluation.returned_group`: the fewest top races reaching
   `RaceEvaluationSettings.group_probability_mass`; a group above `max_group_size` is
   "unrecognized". Both are tuned on validation only.
6. **Metrics** (`race_evaluation.evaluate_races`, on test once): group-aware race accuracy
   (true race in group, over all photos, so abstaining never helps), coverage, selective
   accuracy, mean group size, per-race photo and accession support with in-group recall,
   and the confusion matrix (top-1 race, plus an "unrecognized" column). The 89% target is
   claimed only for group-aware accuracy at the reported coverage (ADR-0011); otherwise the
   measured result and its limits are published.

## Setup

Needs [uv](https://docs.astral.sh/uv/). TensorFlow needs Python 3.11 or 3.12.

```sh
cd model
uv sync --python 3.12                 # data tools and tests (small)
uv sync --python 3.12 --extra train   # adds TensorFlow 2.20 (~1.5 GB) for train
uv sync --python 3.12 --extra export  # TensorFlow 2.17 for export (a separate environment)
uv sync --python 3.12 --extra review  # adds PyTorch + open_clip for review-labels
uv run pytest
```

`review-labels` downloads BioCLIP 2's weights (~1.7 GB) into `HF_HOME` on first use. Keep
`HF_HOME`, `UV_CACHE_DIR` and `TMPDIR` on the data drive if the system disk is small.

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

#    Verify the unreviewed Commons/Flickr labels with BioCLIP 2 (needs the review extra).
uv run sorghum-model review-labels

# 3. Split by group (iNaturalist observer, plot or accession), never by image. Verified
#    labels only; near-duplicates across sources are merged into one group or dropped.
uv run sorghum-model split

# 4. Train: frozen backbone, then fine-tune; keeps the best validation loss. Every epoch is
#    logged to <run-dir>/history.csv with its weights; after a crash, add --resume to
#    continue from the last finished epoch. Decoded 224 px inputs are cached in
#    <run-dir>/input-cache (about 5 GB), so only the first epoch reads the photos.
uv run sorghum-model train --run-dir runs/species-v1

# 5. Quantize, check parity, calibrate, then write the model, metadata and fixtures.
#    Run it in the `export` environment (TensorFlow 2.17); export refuses any other version.
uv run --extra export sorghum-model export --run-dir runs/species-v1 --version 1 \
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
| `near_duplicates.py` | dHash near-duplicates across sources, merged into one group or dropped |
| `label_review.py`, `bioclip_classifier.py` | BioCLIP 2 zero-shot review of unreviewed labels |
| `ship_bar.py` | The export ship bar check |
| `quantization.py` | Round-half-up input quantization and the logit step for parity fixtures |
| `preprocessing.py` | EXIF upright, centre square crop, bilinear resize to 224 px |
| `settings.py` | Every tunable value, with its reason and range checks |
| `train.py` | Keras MobileNetV2, class-balanced weights, light augmentation, input cache, resume |
| `training_history.py` | Per-epoch history that `train --resume` continues from |
| `export.py` | INT8 conversion, float-vs-INT8 parity, temperature, threshold, fixtures |
| `calibration.py` | Temperature fit, ECE, sorghum threshold choice |
| `metadata.py` | Builds and validates `traits-vN.json` |

### Contract with `shared/`

- **Input:** 224 x 224 RGB, uint8. `shared/` crops the centred square, resizes bilinearly,
  then quantizes each 0-255 value with `q = v / scale + zeroPoint`, rounding half up
  (Kotlin `roundToInt`; Python matches with `floor(x + 0.5)`), taking both from
  `input.quantization` in the JSON. The backbone's own normalization is inside the model.
- **Fixtures:** `expected.json` has a top-level `logitStep`, the quantization step of the
  species logits (scale of the int8 tensor feeding the final DEQUANTIZE, or of an int8
  output). It is always present, because the iOS parity test checks each logit within
  2 x logitStep. If the model has no int8 logit tensor, `logitStep` holds (and
  `logitParityMaxDelta` repeats) the
  largest float-vs-INT8 logit difference on the test split. `logitToleranceSource` says which.
- **Output:** one float logits vector per head. Species logits follow the class order in
  `heads.species.classes`.
- **Decision:** `shared/species` applies `softmax(logits / temperature)` and continues only
  when P(sorghum) >= `sorghumThreshold`. The threshold is the most accurate one on
  validation with at least 95% sorghum precision (`ExportSettings`, an assumption).

### ML hygiene this code enforces

- Splits by group, never by image; the split manifest is committed.
- Unverified labels are excluded: `label_status` must be `verified` for split, train and
  export; imports need an annotator.
- INT8 is compared with float per head on the test split, and the numbers go into the
  metadata.
- The temperature is fitted after quantization, on validation; ECE is reported before and
  after.
- Bump N whenever weights, class order, preprocessing or tables change.
