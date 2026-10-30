# Type evaluation protocol, version 1

Status: **Frozen** · Version: `type-eval-v1` · Date: 2026-10-30 · Decision record:
[ADR-0013](adr/0013-five-race-type-evaluation-protocol.md) · Ticket: T25 (#51)

This protocol says how the "89% sorghum type accuracy" goal is measured. It is frozen before
any phone photo is collected and before any model is tuned for it. To change anything below,
write version 2 with a new date and a reason. A change made after test accessions are
assigned (section 6) needs a new sealed test set. The old set's result is then reported but
does not count for the gate.

## 1. What is scored

- **Type** means one of the **five basic races** of Harlan & de Wet (1972): Bicolor, Guinea,
  Caudatum, Kafir, Durra. This is the product owner's decision of 2026-10-30 (#51). The ten
  intermediate races are reported apart (section 4) and are not part of the gate. Exact cultivar
  and use type (grain, sweet, forage) are out of scope for the goal.
- **Unit: the accession.** One accession is one test item, however many photos it has. The
  accession's photos are combined into one answer (section 2). This stops an accession with many
  photos from counting more than one with few.
- **Truth label.** The accession's race in the assignment manifest (section 5), fixed before
  any photo is taken. Only accessions whose label passes the label rule (section 5.2) are used.

## 2. The answer for one accession

1. Each photo goes through the frozen app pipeline (quality check, colour correction, model)
   and gives calibrated probabilities over the five basic races.
2. **Aggregation:** the mean of those probabilities over all of the accession's scored photos
   (every view the model reads), then renormalised. Version 1 fixes this rule. A different rule,
   such as a weighted mean per view, needs version 2 and must be chosen on development
   accessions only.
3. **Answer rule:** the smallest set of top races whose probabilities add up to the group mass
   `m`. If that set holds **more than two races**, the answer is "unrecognized". Two of five races
   is the most that still names a useful type. This matches `BASIC_RACE_RULE_SEARCH`
   (`max_group_sizes=(1, 2)`). `m` is chosen on development accessions only, with a coverage
   margin, before the test is scored.
4. A photo rejected by the quality check, or with no colour card, gives no probabilities
   (ARCHITECTURE.md section 4.3). An accession with no scorable photo is **"unrecognized"**. It
   is never dropped from the denominator.

## 3. Metrics and the gate

For the N test accessions:

| Name | Definition |
|---|---|
| answered | the accession gets a group of one or two races |
| correct | answered, and the true race is in the group (group-aware) |
| **type accuracy** (headline) | correct / N. An abstention counts as **not correct** |
| coverage | answered / N |
| selective accuracy | correct / answered |
| mean group size | over answered accessions; the share of two-race groups is also reported |

**Gate (all four must hold, on the single test scoring):**

1. selective accuracy **>= 0.89**,
2. coverage **>= 0.80** (the coverage floor),
3. selective accuracy at least **0.10 above the majority-race baseline** of the test set,
4. |float - INT8| selective accuracy **<= 0.02** under the same rule.

These are `RaceGateSettings` (0.89, 0.80, 0.10, 0.02), applied at accession level. Because an
abstention counts as not correct, a passing model has type accuracy >= 0.89 x 0.80 = **0.712**.
Type accuracy is published first, so a model cannot look good by abstaining. The gate is judged
on point estimates. Every number is also published with its **Wilson 95% interval**. A pass
whose interval reaches below 0.89 is reported as "passed at the point estimate". With 250 test
accessions (50 per race), the interval of a selective accuracy near 0.90 is about +-0.04.

**Per race (always reported, not part of the gate):** for each of the five races, its accession
count, coverage, in-group recall (correct / accessions of that race) and selective accuracy,
each with a Wilson 95% interval. Also reported: macro type accuracy (mean of the five
in-group recalls) and the confusion matrix (rows: true race; columns: top-1 race of answered
accessions, then "unrecognized"). Version 1 sets no per-race floor. At 50 accessions per race,
an interval is about +-0.09 wide, so a floor would fail or pass by chance. Any race with
in-group recall below 0.70 is named in the result as a known weakness.

## 4. Intermediate side report

Intermediate-race accessions are scored with the same frozen model and rule, but **never enter
the gate**. Per intermediate race, and for all of them together, the report gives:

- the answered share;
- the **parent-in-group** rate: answered, and a basic parent of the intermediate is in the group
  (Caudatum or Durra for Durra-caudatum);
- the **both-parents** rate: a two-race group that is exactly the two parents.

The intermediate set comes from the development pool's spare accessions and is labelled with
role `intermediate-report` in the assignment manifest. It is collected only after the 5 x 150
core accessions are photographed. GRIN's intermediate photos (`model/splits/cultivar-grin-v1.csv`)
can stand in until then.

## 5. Accessions and the split manifest

### 5.1 Size

Planning target per basic race: **150 accessions, 100 for development** (training, validation,
tuning) **and 50 for test**. The proposed list and any shortfall per race are in
`model/manifests/core-accession-shortlist.csv` (T26, #52). A shortfall is documented, never
filled with labels that fail 5.2. The test set must hold the same number of accessions for
each race, so the majority baseline is about 0.20. If one race is short, every race's test count
drops to that race's count.

### 5.2 Label rule

An accession can be used only when:

- every GRIN race observation names the same basic race (`cultivar_races.race_labels`; conflicting,
  Unknown, Mixed and Shattercane records are excluded), **and**
- no other source names a different race or an intermediate of it. The Frontiers 2023 panel is
  the second source today (`model/manifests/race-crosswalk-frontiers.csv`, T24). Once the
  Genesys export exists, ICRISAT passport data is the third.

**Test accessions need a confirmed label.** A development accession may rest on one GRIN
observation. A test accession needs its basic race named by **two independent observations**,
in one of these ways:

- two GRIN plantings agree (label tier `repeated`);
- GRIN and a second source agree (`corroborated`: Frontiers 2023, or ICRISAT passport data); or
- a sorghum race specialist names the race from the team's own grown panicles, without seeing
  the GRIN label, before the draw in section 6 (`expert-verified`).

The reason is the crosswalk (T24, `model/manifests/race-crosswalk-frontiers-summary.txt`).
Where GRIN and Frontiers both name a basic race, they agree on only 0.79 [0.62, 0.90] of
accessions. Over all shared accessions they agree on 0.40 [0.28, 0.53], and every mismatch rests
on a single GRIN observation. A test whose labels are wrong one time in five cannot show 89%.
That measured agreement is quoted with every result, because it caps what any accuracy on
these labels can show.

### 5.3 Test accessions are unseen

A test accession's photos, including its GRIN photos, are never used to train, validate, tune
or choose a rule for any model scored on this test. An accession is **test-eligible** when it
has a confirmed label (5.2) and no GRIN photo in the `accession_split` train or validation split.
If an accession's GRIN photo is in train or validation, it can go to test only if that photo is
removed from every model scored on the test.

### 5.4 Assignment manifest schema (`type-eval-v1-assignment.csv`)

One row per accession, committed **before** any photo is taken:

| Column | Meaning |
|---|---|
| `accession` | GRIN accession number ("PI 562744"), or the ICRISAT IS number when seed comes from ICRISAT |
| `icrisat_number` | the IS number, if one is known |
| `race` | the truth label, written the way GRIN writes it ("Caudatum", "Durra-bicolor") |
| `race_group` | the basic race, or `intermediate` |
| `label_sources` | the sources that agree, e.g. `grin(2 studies)+frontiers` |
| `role` | `development`, `test` or `intermediate-report` |
| `seed_source` | genebank and lot (`GRIN PI 562744 01 SD`, `ICRISAT IS 1233`) |
| `protocol_version` | `type-eval-v1` |

### 5.5 Photo manifest schema (`type-eval-v1-photos.csv`)

One row per photo, written by the capture team (development) or the custodian (test):

| Column | Meaning |
|---|---|
| `photo_sha256` | SHA-256 of the image file as captured |
| `accession` | as in the assignment manifest |
| `view` | `panicle`, `grain`, `glume` or `leaf` |
| `plant` | which plant of the accession (1, 2, ...). Photos of one plant share it |
| `capture_session` | date and place of the session, e.g. `2027-03-04-patancheru` |
| `device` | phone model |
| `app_version` | app build used to capture |
| `has_colour_card`, `has_ruler` | `yes` or `no`, as checked by the capture team |
| `role` | copied from the assignment manifest |

Splits stay by accession. Development validation is drawn by accession inside the development
role, never by photo. The photos themselves stay out of git, as all datasets do. The manifests
are committed. Test photo rows are committed by the custodian and hold hashes only.

## 6. Sealed test procedure

1. **Custodian.** One named person who does not train or tune models holds the test photos.
   The product owner names them in the assignment commit. The custodian keeps the test photos on
   a separate encrypted drive, not on the shared data drive.
2. **Commit, then draw.** The custodian commits the candidate list (the shortlist CSV) together
   with the SHA-256 of a secret salt. They then draw the test accessions: within each race, among
   the test-eligible core accessions, the ones with the smallest SHA-256(salt + accession). The
   assignment manifest and the salt are then committed, so anyone can recompute the draw. All of
   this happens **before** any photo is taken.
3. **Capture.** Development and test accessions are photographed under the same protocol
   (section 7), in mixed order, by the same people. Test photos go straight to the custodian,
   who commits their hashes (5.5). Model developers never open them.
4. **Freeze.** Before scoring, the developers hand over the frozen model (`.tflite` and metadata
   JSON with their SHA-256), the code commit, the aggregation rule, `m` and the temperatures.
   These are committed together.
5. **Single scoring.** The custodian runs the scoring script once on the test photos and
   publishes the full result (section 3) whether it passes or fails. A photo hash that does not
   match the manifest stops the scoring. A second model version is scored against a **new**
   sealed set. On this set, a second model is reported as "not gating".

## 7. Photo protocol (team guide: [docs/photo-guide.md](../photo-guide.md))

Every photo uses the app's capture flow (portrait, level check, quality check). Each photo shows
the sample on a matte, neutral-grey board, with the **ColorChecker Classic Mini** (ADR-0008) and
a **mm ruler** fully in the frame, in diffuse daylight or shade, without flash. Per accession:

| View | Required | What | Why |
|---|---|---|---|
| **Panicle** | yes, 2 plants | The whole harvested panicle laid flat. One photo per plant | Race is defined by panicle and spikelet form; compactness and shape are catalogue traits |
| **Grain** | yes, 1 | About 50 threshed grains in one layer, not touching | Grain shape and colour, and seed size from the ruler |
| **Glume** | yes, 1 | A close-up of 10 to 20 spikelets with glumes, grain still in place | How much of the grain the glumes cover, and glume shape, are the key race characters (Harlan & de Wet 1972) |
| **Leaf** | optional | The middle part of the flag leaf, upper side, with the midrib | See below |

**Why the leaf view is optional.** Race is defined by spikelet, glume and grain shape. The leaf
carries no race character, so it is not needed for the type gate, and no race result may depend
on it in version 1. It is still worth taking when time allows, because two catalogue traits for
cultivar matching are on the leaf (midrib colour, plant pigmentation), and leaf photos train the
species gate on phone images. It costs one extra photo per plant. A leaf result can be used for
race only through a version 2 protocol fixed before a new sealed test.
