# Model status: what "model finished" means today

Audit for T10 (#33), 2026-10-30, against `origin/main` at `0b50625`. It checks every component
of the identification path in [ADR-0001](adr/0001-trait-first-identification.md) (photo →
descriptor-state probabilities → naive Bayes over accession tables) and the accuracy target in
[ADR-0011](adr/0011-cultivar-accuracy-target.md). Update this file when a component changes
state, and log the change in `docs/KEEP_UP.md`.

States: **complete** (built, tested, meets its bar), **deferred** (not needed for "model
finished", or waits on a decision; ticket named), **blocked** (cannot start or finish without
something outside the team), **not started** (needed, nothing built yet).

## Scope decision

"Model finished" means the `model/` deliverables that the trait-first path needs from
training and data: the species gate, the learned trait heads, the cultivar table, and an
honest race-level evaluation. The pipeline that runs them in the app (measured readers,
`session`, result screen) is ARCHITECTURE.md section 8 step 6, not part of the model, and is
listed below so nothing falls between the two.

## Components

| # | Component | State | Evidence | Exit criterion for the remaining work | Owner |
|---|---|---|---|---|---|
| 1 | Species gate, `traits-v2` | **Complete** | `ios/SorghumCapture/Resources/Models/traits-v2.{tflite,json}` (PR #30, bundled in PR #34); `shared/species/{SpeciesGate,ModelMetadata}.kt` with 23 + 15 `commonTest` tests; `ios/SorghumCaptureTests/SpeciesModelParityTests.swift`. Test split: sorghum vs not 0.932 (bar 0.90), INT8 1.2 points under float (bar 2), ECE 0.013 after temperature scaling (`model/README.md`, Status) | Nothing for "model finished". Separately: R3 benchmark on a real iPhone; Android runner paused (`feature/android-litert`) | model |
| 2 | Learned trait heads | **Not started** (ticket #35) | `traits-v2.json` has only the species head; `shared/species/ModelMetadata.kt` reads only `heads.species`, so there is no trait-head → `TraitEstimate` mapping yet. Training data exists: GRIN photos (9,393) with descriptor states in `model/manifests/cultivar-grin-descriptors.csv` | Per head, on `accession_split` test scored once: accuracy at least 0.10 above the majority-state baseline, INT8 within 0.02 of float, temperature fitted on validation with ECE reported (R4, R6). Shipped as `traits-v3` with the head's state order; `shared/` maps the head to a `TraitEstimate` with the floor | cultivar/model |
| 3 | Measured trait readers (grain colour, glume colour, seed size, midrib colour, pigmentation, lustre) | **Not started** (backlog S5; proposed ticket T17) | `shared/traits` holds `TraitCatalogue.kt`, `TraitEstimate.kt` (20 tests) and `ContinuousTraitEstimate.kt` (9 tests), but no reader. Their inputs exist: `shared/calibration` (ADR-0008, 33 tests) and the board-contrast mask in `shared/segmentation` (13 tests), neither wired into a pipeline | One pure reader per measured trait with boundary tests, a fixture image with its expected estimate, and a reasoning test showing the trait moves the posterior (CLAUDE.md, "Adding a new trait"). Not part of "model finished" | shared |
| 4 | Cultivar tables `cultivars-vN.json` | **Not started**; shipped table **blocked** on R2 | No `cultivars-v*.json` anywhere in the repo or on the data drive. The schema v1 parser and `CultivarTableSource` port exist (`shared/reasoning/CultivarTablesParser.kt`, 19 tests), tested only with hand-made tables (`TestTables.kt`). The Genesys builder (backlog S8) waits on an API key. But GRIN already supplies the rows: 60,987 observations over 8,959 accessions in IBPGR codes for 6 of 7 catalogue traits (`cultivar-grin-descriptors.csv`; GRIN has no grain lustre) | Proposed ticket T16: a builder in `model/` writes `cultivars-v1.json` (schema 1, data version 1, attribution naming USDA GRIN-Global) from the GRIN manifest and `parseCultivarTables` accepts it. The shipped table also needs the target cultivar list and its accession mapping (R2, product owner) | cultivar data |
| 5 | Naive Bayes reasoning | **Complete** (code); not yet run on real tables | `shared/reasoning/CultivarIdentification.kt`: noise floor, uniform-reading skip, groups, "unrecognized", `correctTrait` recompute, explanations from the posterior; 28 + 5 tests (PR #8) | Run once on `cultivars-v1` over GRIN accessions with trait states from held-out photos: report top-1, top-3, mean group size and coverage on `planting_split` test (ADR-0011 secondary metrics) | shared |
| 6 | Race model `race-v1` | **Deferred** (#37, #38); not bundled | `/Volumes/LaCie/sorghum-model/runs/race-v1/export/race-v1.{tflite,json}` and `race-v1-report.txt`; code `model/sorghum_model/race_{training,evaluation,export}.py` (PR #39). Test, INT8: selective group-aware accuracy **0.768 at 0.797 coverage**; gate 0.89 at ≥ 0.80. Passed: +0.275 over the planting baseline (bar 0.10), float/INT8 delta 0.009 (bar 0.02) | Either the gate is met on a fresh test scoring (0.89 selective at ≥ 0.80 coverage), or #38 records a product decision to show race as a non-gating hint with its abstention rule. #37 measures the five-basic-race output (secondary score 0.978) as a separately named result | model, product |
| 7 | Race labels and splits | **Complete** | `model/splits/cultivar-grin-v1.csv` and `-summary.txt`: 6,462 scored accessions, accession and planting splits, exclusions kept per photo (`cultivar_races.py`). Only the first image of multi-image accessions was downloaded | #36 adds the extra GRIN images per accession, each in its accession's existing split | data |
| 8 | Ship test on phone photos | **Blocked** | ADR-0011: no phone close-up set labelled by cultivar exists; Sorghum-100 needs a Kaggle login, TERRA-REF seasons 4 and 6 a Globus account | A team-collected phone set of the target cultivars with the app's capture protocol, its accessions reserved for test | product owner |
| 9 | App pipeline: `session` (S6a) and result screen (S7) | **Deferred** (not model work) | ADR-0009 design merged (PR #13); `shared/session` holds only `CaptureFlow.kt` | First cultivar result on iPhone (ARCHITECTURE.md step 6) | shared, iOS |

## What the GRIN tables can and cannot tell apart (risk R1)

Counted from `model/manifests/cultivar-grin-descriptors.csv` (one state per trait; accessions
with several recorded states keep them all as one combined value):

| Traits used | Accessions with all of them | Distinct profiles | Accessions with a unique profile | Median accessions sharing a profile |
|---|---|---|---|---|
| 6 (all GRIN traits) | 1,926 | 408 | 191 (9.9%) | 14 |
| 5 (without panicle shape) | 3,077 | 260 | 110 (3.6%) | 65 |

So exact-accession top-1 from these traits alone is capped near 10% even with perfect trait
readings; results will be groups. This supports ADR-0011's decision to state the target at
race level and to report group size with every accuracy.

## Remaining blockers

- **Target cultivar list** (R2): needed for the shipped table and for priors. Product owner.
- **Phone test set**: needed for the ship test. Team collection.
- **External data accounts**: Kaggle (Sorghum-100), Globus (TERRA-REF), the Yang 2025 authors.
- **Genesys API key**: needed only if tables must come from Genesys rather than GRIN.

## Proposed tickets

Not yet opened on GitHub:

- **T16, cultivars-v1 from GRIN** (cultivar data, `feature/cultivar-tables-v1`): builder in
  `model/`, output accepted by `parseCultivarTables`, accession/trait/row counts and the R1
  profile report committed. Update the Genesys-only wording in `CultivarTables.kt` and
  ARCHITECTURE.md section 5 if GRIN becomes a table source.
- **T17, measured trait readers** (shared, `feature/measured-trait-readers`): the backlog S5
  readers with the acceptance in row 3.
