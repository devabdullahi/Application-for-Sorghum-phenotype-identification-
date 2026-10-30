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
  9,410 images, 8,965 accessions, 11 plantings; all downloaded on 2026-10-30). Rows go to
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

Final counts (2026-10-30, after #36, `splits/cultivar-grin-v1-summary.txt`): 6,463 accessions
/ 6,721 images scored; excluded 2,204 no-race-observation, 6 race-unknown, 197 not-a-race (Mixed
182, Shattercane 13, Breeding line 2), 95 conflicting-observations, 0 unmapped-value.

Trait-mapping assumptions still to confirm (`grin_descriptors.py`): Straw glume -> IBPGR
White, Colourless midrib -> White, Lax panicle -> 1 "Very lax".

Which image a study-page row names (#36, 2026-10-30): a row's IMAGE cell shows the
accession's first image in GRIN, which can belong to another planting, and repeats it on the
"Second/Third/Fourth image" rows. The NOTE column links the row's own image on the old NPGS
server; `grin.parse_study_page` maps that link to the same file on the GRIN-Global server and
uses it. Before this, all 426 accessions photographed in two or more plantings had **the same
file** in each planting, so `planting_split` test photos were copies of training photos, and
the extra images of 13 accessions were never fetched. A rerun of `grin-download` re-fetches a
file only when the old manifest says it came from another URL, and reads the study pages from
the `grin-descriptors` page cache.

### Race model plan (T4, #24)

Trained and scored once on test as race-v1 (T9, #32); results below. The plan as followed:

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

### Race model results (race-v1, T9 #32, 2026-10-30)

**The 89% gate was missed.** On the untouched test split (1,029 photos, 15 races) the INT8 model
answers 79.7% of photos with selective group-aware accuracy **0.768** (gate: 0.89 at >= 80%
coverage). Every threshold was chosen on validation only; test was scored once.

```sh
# train extra (TF 2.20), about 21 min on the 16 GB Mac (CPU): 50 s per frozen epoch, 75 s per fine-tune epoch
python -m sorghum_model.cli race-train --data-root <data>/cultivar \
  --starting-model <runs>/v2-3/run/species.keras --run-dir <runs>/race-v1/run
# export extra (TF 2.17): INT8, temperatures and answer rules on validation, one test scoring
python -m sorghum_model.cli race-export --data-root <data>/cultivar \
  --run-dir <runs>/race-v1/run --version 1 --out-dir <runs>/race-v1/export
```

- **Model:** traits-v2 MobileNetV2 1.0 backbone (run v2-3) with a new 15-race head, same uint8
  224 px centre-crop input. 10 head epochs on the frozen backbone, then 10 fine-tune epochs from
  `block_12_expand` with BatchNorm frozen (`RaceTrainingSettings`). Unweighted loss, best
  validation loss at the last epoch (1.537). Exported with the TF 2.17 converter.
- **Answer rules** (`race_evaluation.choose_answer_rule`, on INT8 validation outputs, target
  coverage + 0.02): 80% point mass 0.62, max group 3; 90% point mass 0.54, max group 3.

| Test (1,029 photos) | coverage | selective acc. | acc. over all photos | mean group | top-1 |
|---|---|---|---|---|---|
| INT8, 80% rule | 0.797 | **0.768** | 0.612 | 1.78 | 0.558 |
| float, same rule | 0.789 | 0.777 | 0.613 | 1.80 | 0.535 |
| INT8, 90% rule | 0.912 | 0.715 | 0.652 | 1.70 | |
| majority baseline (Caudatum) | 1.000 | 0.359 | 0.359 | 1.00 | 0.359 |
| planting baseline | 1.000 | 0.493 | 0.493 | 1.00 | 0.493 |

Gate: selective accuracy 0.768 < 0.89 and coverage 0.797 < 0.80 (validation coverage 0.829).
Passed: +0.275 over the better baseline (bar 0.10) and float/INT8 delta 0.009 (bar 0.02).
Temperature 1.33 (INT8); test ECE 0.093 before, 0.050 after. Per-race recall, support and the
confusion matrix are in `race-v1-report.txt` next to the model; in short, Caudatum (0.84) and
Durra (0.81) are found, and most intermediates are not (Kafir-caudatum 0.18, Caudatum-bicolor
0.09, Kafir-bicolor 0 of 7): they are answered as their dominant parent (Kafir-durra as Durra
31 of 57, Kafir-caudatum as Caudatum 30 of 57).

- **Secondary, not the gate:** read at the five basic races (a hit when a parent of the true
  race is among the parents of the returned group, `evaluate_basic_races`), the same answers
  score 0.978 at 0.797 coverage. Lenient by construction.
- **Planting shortcut:** inside every planting with more than 12 test photos the model beats
  that planting's commonest training race by +0.15 (Sudan 1993) to +0.73 (SP42 2006), so it
  is not only recognising the board. But a leave-one-planting-out check on train+validation
  (frozen features, linear head) shows race signal transfers to an unseen planting only
  partly: held-out top-1 0.58 (Sudan) to 0.16 (Isabela 2010).
- **What was tried on validation** (selective accuracy near 82% coverage): frozen-feature
  linear head 0.735 balanced, 0.773 unweighted; ImageNet backbone 0.749; MLP heads no better;
  fine-tuning at 1e-4 with balanced weights overfitted from its first epoch (0.658); letterbox
  instead of centre crop 0.771; 448 px input 0.777-0.795. None comes within 9 points of 0.89.
- **Why, and what would close the gap:** the intermediates are defined by spikelet and glume
  detail that a whole-board 224 px photo barely resolves, have 7-74 test photos each, and are
  scored against single GRIN labels whose own agreement is unknown. Closer data would be grain
  and spikelet close-ups per accession (the app's own grain photo), several plantings per
  accession, and many more photos of the ten intermediates; a measured inter-rater agreement on
  GRIN race labels would show the ceiling.

### Basic-race output (basic-race-v1, T14 #37, 2026-10-30)

A separately named output over the five basic races (Bicolor, Caudatum, Durra, Guinea, Kafir).
It is **not** the 15-race result and never replaces it.

- **Label rule** (`race_photos.split_basic_and_intermediate`): trained and scored only on
  accessions GRIN names as one basic race (4,223 photos: 2,930 / 645 / 648). The ten
  intermediates are **excluded**, not given a split parent target: an intermediate is not both
  parents at once, and a half-and-half target would teach the head that two basic races look
  alike. How the output answers intermediates is reported apart (below).
- **Model and rule:** same pipeline as race-v1 (`race-train --basic-races-only`,
  `race-export --basic-races-only`): traits-v2 backbone, 10 head + 10 fine-tune epochs, INT8,
  temperature (1.385) and answer rule chosen on INT8 validation. Groups hold at most two basic
  races (`BASIC_RACE_RULE_SEARCH`, set before scoring: three of five names most of the
  taxonomy). Test scored once.

| Test, 648 photos | rule (mass, max group) | coverage | selective acc. | acc. over all photos | mean group |
|---|---|---|---|---|---|
| INT8, 80% rule | 0.89, 2 | 0.793 | **0.965** | 0.765 | 1.29 |
| float, same rule | | 0.809 | 0.958 | 0.775 | 1.32 |
| INT8, 90% rule | 0.81, 2 | 0.904 | 0.945 | 0.855 | 1.26 |
| majority baseline (Caudatum) | | 1.000 | 0.573 | 0.573 | 1.00 |
| planting baseline | | 1.000 | 0.784 | 0.784 | 1.00 |
| race-v1 on the same photos, read at basic level (lenient: a parent in the group) | 0.62, 3 | 0.852 | 0.986 | | |
| race-v1, strict (the group's parents are exactly the true basic race) | | 0.852 | 0.531 | | |

Top-1: 0.861 INT8 (race-v1's top race has the true basic race as a parent on 0.883 of these
photos). ECE 0.045 before and 0.030 after temperature. The race gate (0.89 selective at >= 0.80
coverage with the 80% rule) is **missed on coverage alone**: 0.793 on test against 0.833 on
validation. The 90% rule, chosen on validation at the same time, reaches 0.945 at 0.904 on
test; it is reported, not substituted for the gate rule after the fact. Per-race in-group
recall at the 80% rule: Caudatum 0.83, Durra 0.82, Guinea 0.46, Bicolor 0.44, Kafir 0.18 (22
photos; mostly "unrecognized"). Report: `basic-race-v1-report.txt`.

Intermediates (384 test photos, never trained on), same rule: answered 0.654, and among the
answered a parent of the true intermediate is in the group 0.940 (Guinea-kafir 0.25, the rest
0.86-1.0). race-v1 predates the #36 image fix; its numbers above are its fixed model re-run on
the current files, with nothing re-chosen.

## Trait heads (T12, #35, 2026-10-30)

Learned trait heads trained from GRIN descriptors on the GRIN photos, scored once on the
untouched `accession_split` test split. **No head passes the R6 gate**, so none is ready to
ship; the model is a research artifact (not bundled, `traits-vN` contract unchanged).

### Labels (`cultivar_traits.py`, `sorghum-model trait-labels`)

An accession gets a state for a trait only when every GRIN observation of it maps to the same
IBPGR state (`grin_descriptors.py` mappings). Otherwise it has no label for that trait (its
photos still serve the other traits), with the reason recorded:

| Exclusion | Meaning | Glume | Grain | Panicle |
|---|---|---|---|---|
| `no-observation` | GRIN has no value | 3,868 | 2,537 | 3,576 |
| `no-single-state` | only values without one IBPGR state (Tan, Mixed, Segregating; loose or semi-loose panicles, whose IBPGR state needs the branch habit GRIN does not record) | 973 | 938 | 2,188 |
| `conflicting-observations` | plantings name different states, or a state and a value without one | 51 | 79 | 37 |
| `unmapped-value` | a value missing from GRIN's code table | 0 | 0 | 0 |

Panicle uses each study's combined compactness + shape row; a study with only one of the two
counts as a value without a state. A head outputs the catalogue states with at least 20
training accessions (`TraitLabelSettings`); rarer states (grain 6 "Other", panicle 12 "Broom
corn") get no output and `shared/` would give them the floor. Coverage and per-state support
per split: `splits/cultivar-grin-v1-trait-summary.txt`. Not candidates: grain lustre (GRIN has
no lustre descriptor), midrib colour and plant pigmentation (leaf traits the panicle-and-grain
photos do not show). 100-seed weight is labelled for the probe only (a measured trait in the
catalogue).

Limits: the loose and semi-loose elliptical panicles (1,163 accessions) are absent from
training and scoring, so the panicle head has never seen them; GRIN boards have no colour card,
so colour is uncalibrated camera colour.

### Frozen-feature probe (validation only)

Linear heads on the cached traits-v2 backbone embedding (1280-d, flip-augmented), L2 chosen
by validation loss, ECE after a 2-fold temperature on validation accessions:

| Trait | Val photos | Accuracy | Macro recall | ECE | Majority | Planting |
|---|---|---|---|---|---|---|
| glumeColour | 652 | 0.584 | 0.290 | 0.028 | 0.485 | 0.560 |
| grainColour | 857 | 0.671 | 0.463 | 0.034 | 0.462 | 0.457 |
| panicleCompactnessAndShape | 515 | 0.676 | 0.565 | 0.038 | 0.456 | 0.546 |
| hundredSeedWeight (probe only) | 1,443 | 0.622 | 0.518 | 0.033 | 0.488 | 0.564 |

Hand-built colour features (linear-sRGB statistics of the sample pixels found by a Python port
of `shared/segmentation` ContrastMask, raw and divided by the board colour) did not help
glume colour (0.584) and helped grain colour a little (0.690 with the embedding; 0.645 alone).
Grain colour from colour statistics alone is close to the CNN, so it may belong as a
*measured* reader on colour-card-corrected grain photos (a T17 candidate).

### Model and test result (trait-heads-v1)

```sh
# train extra (TF 2.20): 15 frozen-head epochs, then fine-tuning from block_12_expand at 3e-5
python -m sorghum_model.cli trait-train --data-root <data>/cultivar \
  --starting-model <runs>/v2-3/run/species.keras --run-dir <runs>/trait-heads-1/run --fine-tune-epochs 20
# export extra (TF 2.17): INT8, one temperature per head on INT8 validation, one test scoring
python -m sorghum_model.cli trait-export --data-root <data>/cultivar \
  --run-dir <runs>/trait-heads-1/run --version 1 --out-dir <runs>/trait-heads-1/export
python -m sorghum_model.cli trait-ranking --outputs <runs>/trait-heads-1/export/trait-heads-v1-outputs.npz \
  --out <runs>/trait-heads-1/export/trait-heads-v1-ranking.json
```

One model, three softmax heads on the traits-v2 MobileNetV2 backbone (`trait_training.py`); a
photo trains every head its accession has a state for, with loss weight 0 on the others. The
run was first 15 + 10 epochs, then resumed to 15 + 20 because validation loss was still
falling; the checkpoint with the best total validation loss (epoch 29, 1.887) was exported.
Fine-tuning beat the frozen heads on validation for grain colour only (0.702 against 0.671);
glume and panicle were level. The heads are found in the TFLite file by matching each to the
output whose top-1 agrees with the float head (`match_heads_to_outputs`); the JSON records
each head's `outputIndex`.

Test, INT8 with its validation temperature (gate: `TraitGateSettings`, set before any head was
scored: accuracy >= 0.70, >= 0.10 over the better of the majority and planting baselines,
macro recall >= 0.50, ECE <= 0.05, |float - INT8| <= 0.02):

| Head (states) | Test photos | Accuracy | Macro recall | ECE before / after T | Float | Majority | Planting | Gate |
|---|---|---|---|---|---|---|---|---|
| glumeColour (1-6) | 658 | 0.588 | 0.352 | 0.096 / 0.040 | 0.590 | 0.460 | 0.562 | missed: accuracy, margin 0.026, macro recall |
| grainColour (1-5) | 850 | 0.668 | 0.464 | 0.081 / 0.038 | 0.692 | 0.451 | 0.491 | missed: accuracy, macro recall, INT8 delta 0.024 |
| panicleCompactnessAndShape (1, 8, 9, 10) | 509 | 0.676 | 0.537 | 0.137 / 0.057 | 0.680 | 0.487 | 0.587 | missed: accuracy, margin 0.088, ECE |

Per-state recall, support and confusion are in `trait-heads-v1-report.txt`. In short: glume
Purple and Black are read (0.70, 0.71), Sienna, Mahogany and Red are not (0, 0.14, 0.17);
grain White 0.84, Brown 0.69, Red 0.53, Yellow 0.27, Buff 0; panicle semi-compact elliptic 0.90
and lax 0.71, compact oval 0.53, compact elliptic 0.01 (answered as semi-compact elliptic).
The looser criterion in `docs/architecture/model-status.md` (+0.10 over majority, INT8 within
0.02) would pass glume and panicle; the R6 gate above is the one that decides.

### Trait-first ranking check (`trait_ranking.py`)

The heads' test outputs through naive Bayes as `shared/reasoning` computes it (soft evidence
sum_s P(s | class) r(s), the 0.01 floor on readings and rows). Race tables and prior from
training accessions; the race answer rule chosen on validation for 80% coverage; 1,032 test
photos with a scored race. "Oracle" reads the accession's own GRIN states instead of the
heads: the ceiling of a perfect reader of the same traits.

| Readings | Race top-1 | Top-3 | Coverage | Selective acc. | Mean group | Accession top-1 / top-10 / top-100 (8,956 candidates) |
|---|---|---|---|---|---|---|
| heads (3 traits) | 0.456 | 0.678 | 0.836 | 0.665 | 2.38 | 0.001 / 0.011 / 0.075 |
| GRIN oracle, same traits | 0.441 | 0.681 | 0.934 | 0.641 | 2.26 | 0.013 / 0.100 / 0.338 |
| GRIN oracle + 100-seed weight | 0.450 | 0.731 | 0.837 | 0.685 | 2.09 | 0.032 / 0.172 / 0.478 |
| race-v1 (direct race head) | 0.558 | | 0.797 | 0.768 | 1.78 | |

Even perfect readings of these traits leave race identification well below the direct race
model, and exact-accession matching is not usable (accessions share trait profiles; risk R1).
Accession matching uses every labelled GRIN accession as the table, the test accession
included, as a genebank table would hold it; no image of a test accession was trained on.

### What would close the gap

Glume colour and compact-elliptic panicles are small details in a whole-board 224 px photo;
crops of the panicle and of the grain (the app's own photo types) and a colour card would help
more than more epochs. A second GRIN reading per accession would also measure label agreement,
the ceiling these heads are scored against.

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
| `cultivar_traits.py` | Per-accession trait labels from GRIN descriptors, exclusions, head states |
| `trait_training.py`, `trait_export.py` | Multi-head trait model training, INT8 export, per-head temperature and R6 gate |
| `trait_evaluation.py` | Trait head scores, baselines, the R6 gate, TFLite output matching |
| `trait_ranking.py` | Offline naive Bayes over trait readings (race and accession ranking) |

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
