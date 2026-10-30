# Non-image sorghum trait databases and methods for naive-Bayes cultivar ID on a phone

Research date: 2026-10-19. "Opened" means the page was fetched and read. "Snippet only" means the page could not be fetched (SSL or connection failure) and the claim rests on search-result text, so check it before relying on it.

## 1. Databases that give visible descriptor states per accession or cultivar (usable as conditional probability tables)

### Takeaway
The large open, machine-readable sources are genebank accession datasets, not lists of named released cultivars:
- ICRISAT Genesys "Sorghum Characterization": 42,869 accessions, 22 traits, CC BY-SA 4.0, xlsx.
- USDA GRIN (NPGS) sorghum descriptors, such as GLUMECOLOR, with per-value accession lists.
- KALRO-GeRRI Kibos datasets on Genesys: CC BY-NC 4.0.

Named released cultivars with visible traits appear only in semi-structured national sources:
- IIMR (India) PDF tables of released varieties, with free-text "salient features".
- Ethiopia's ethioseed.moa.gov.et variety records: mostly seed colour, often blank.
- PPV&FRA/IIMR DUS data on 33 characteristics for more than 117 candidate varieties, which is not public.

UPOV, CPVO and other DUS variety descriptions were not found as open per-variety tables.

### Cited Findings

**ICRISAT "Sorghum Characterization" (Genesys, v1.0)**
- 42,869 accessions and 22 traits, opened. [Genesys dataset fbb7bb31](https://www.genesys-pgr.org/datasets/fbb7bb31-67bb-4010-9fe1-5bf7ac55adc8)
- The 22 traits:
  - Race
  - Plant height (postrainy) and plant height (rainy)
  - Plant pigmentation
  - Basal tillers number
  - Nodal tillering
  - Leaf midrib color
  - Days to flowering (postrainy) and days to flowering (rainy)
  - Panicle exertion
  - Panicle length and panicle width
  - Panicle compactness and shape
  - Glume color
  - Glume covering
  - Seed color
  - Seed lustre
  - Seed subcoat
  - Seed size
  - 100 seed weight
  - Endosperm texture
  - Threshability
  - Source: [Genesys dataset](https://www.genesys-pgr.org/datasets/fbb7bb31-67bb-4010-9fe1-5bf7ac55adc8)
- Licence and files: CC BY-SA 4.0. Files are "Genesys Characterization_12122024.xlsx", Metadata.xlsx and an MCPD passport xlsx. [Genesys dataset](https://www.genesys-pgr.org/datasets/fbb7bb31-67bb-4010-9fe1-5bf7ac55adc8)
- Dates and location: evaluations ran from 18 Dec 1973 to 2024 at Patancheru, India. Published on Genesys 6 Jan 2025. Curator is Dr M. Vetriventhan. No dataset DOI is given. [Genesys dataset](https://www.genesys-pgr.org/datasets/fbb7bb31-67bb-4010-9fe1-5bf7ac55adc8)
- Methods notes: several traits are scored at dough stage on 5 random competitive plants. 100-seed weight is taken at 12% moisture. Seed size is the widest seed width, measured with a Vernier scale. [Genesys dataset](https://www.genesys-pgr.org/datasets/fbb7bb31-67bb-4010-9fe1-5bf7ac55adc8)

**USDA GRIN-Global (NPGS) sorghum**
- The GLUMECOLOR descriptor ("Color of the glume") is CGC-approved and morphological, opened. Its codes and accession counts are:
  - 1 Purple: 5,849
  - 2 Red: 1,362
  - 3 Tan: 818
  - 4 Black: 3,176
  - 5 Sienna: 112
  - 6 Mahogany: 293
  - 7 Straw: 1,739
  - 8 Mixed: 837
  - 9 Segregating: 739
  - Source: [NPGS descriptor 69042](https://npgsweb.ars-grin.gov/gringlobal/descriptordetail?id=69042)
- Glume colour was scored in 13 studies or environments, including:
  - SORGHUM.ETHIOPIAN.1998 (2,145 accessions) and SORGHUM.ETHIOPIAN.2000 (2,741)
  - SORGHUM.MALI (1,612)
  - SORGHUM.STC1993.SUDAN (2,915)
  - Puerto Rico sites (Isabela and Mayaguez, 1993–94)
  - Source: [NPGS descriptor 69042](https://npgsweb.ars-grin.gov/gringlobal/descriptordetail?id=69042)
- Accession lists can be downloaded per trait, per study and per value. [NPGS descriptor 69042](https://npgsweb.ars-grin.gov/gringlobal/descriptordetail?id=69042)
- The same studies give the environment-by-trait structure that a CPT needs.
- A separate KERCOLOR descriptor (phenotypic seed colour, glumes not involved) exists. Snippet only, from the npgstest server. [npgstest descriptor 69005](https://npgstest.ars-grin.gov/gringlobal/descriptordetail?id=69005)
- The descriptor-search page lists crops SORGHUM and SORGHUM-GENSTOCKS. Germplasm distribution terms are on the page: no home or garden distribution, and an SMTA policy that splits propagative from non-propagative material from 1 Jan 2025. The page states no data licence. As US-government data it is generally public domain, but that is an inference. [NPGS descriptor search](https://npgsweb.ars-grin.gov/gringlobal/descriptors?crop=SORGHUM)

**Kenya: KALRO-GeRRI "Agro-morphological characterization of sorghum accessions in Kibos 2022"**
- 193 accessions and 17 traits, opened. The visual traits include:
  - Leaf mid-rib colour
  - Inflorescence compactness and shape
  - Glume colour
  - Grain covering
  - Grain colour
  - Source: [Genesys dataset cde06d9c](https://www.genesys-pgr.org/datasets/cde06d9c-671b-4f20-ac60-f37af35274fd)
- Licence is CC BY-NC 4.0 (non-commercial, which matters for a commercial app). Files are xlsx. The trial ran Mar–Aug 2022. [Genesys dataset cde06d9c](https://www.genesys-pgr.org/datasets/cde06d9c-671b-4f20-ac60-f37af35274fd)
- A 2021 Kibos dataset of 202 accessions on IBPGR descriptors is reported in search results but was not opened.

**India: named released cultivars (IIMR)**
- IIMR's "Details of nationally released kharif sorghum varieties" (PDF, created 2017) was opened and its text extracted.
  - Per variety it gives name, year, notification no., pedigree, grain and fodder yield, maturity days, and free-text "salient features".
  - Examples from the salient features:
    - CSV 1 "Swarna": "Purple pigmented … earhead elliptic and compact, grain elliptical and bold, yellow endosperm"
    - CSV 2: "Glumes reddish purple with awns"
    - CSV 3: "earhead elliptic and lax, Glumes straw coloured. Grain white pearly"
    - CSV 4: "Tan … Glumes short & straw coloured"
  - Coverage is uneven. Later entries (CSV 10, CSV 11, CO 26) give only "compact head" or "loose panicle".
  - Source: [IIMR kharif varieties PDF](https://millets.res.in/technologies/kharif_sorghum_varieties.pdf)
- PPV&FRA national DUS guidelines for sorghum date from February 2007 and use 33 descriptors. New varieties are tested over 2 seasons, and extant or farmers' varieties over 1. [IIMR DUS page](https://www.millets.res.in/dus.php)
- IIMR has DUS-tested 117 candidate varieties since 2008 and keeps more than 110 reference varieties. It has registered 75 sorghum varieties, and its reference-variety database goes to PPV&FRA. No public variety-description database is offered. [IIMR DUS page](https://www.millets.res.in/dus.php)
- A forage sorghum DUS study scored 26 varieties, 20 of them released or notified, on 40 PPV&FRA/ICAR descriptors. [IJGPB article 1167](https://isgpb.org/journal/index.php/IJGPB/article/view/1167) (search result, not opened in full)

**Ethiopia: national seed portal (ethioseed.moa.gov.et)**
- Per-variety records list seed colour, flower colour, leaf arrangement, panicle length and 1000-seed weight, but many fields are "None" or "Not mentioned". Snippet only; the site refused the connection.
- Examples from search results:
  - Jabaa (2022): white seed, 26.1 g
  - A2267-2 (2022): white seed
  - Alene (2017): white seed, yellow flowers
  - Bonsa (2017) and Jiru (2016): brown seed
- Source: [ethioseed record 1031](https://ethioseed.moa.gov.et/seed-variety-details/1031/)

**Farmer naming evidence (Ethiopia)**
- Ethiopian farmers name landraces mainly by midrib colour, grain colour, grain size, glume colour, glume hairiness and grain shape. These are the same visual traits as the descriptor lists. [IDRC record, Euphytica 1997 study](https://idl-bnc-idrc.dspacedirect.org/handle/10625/54503) (search snippet)

### Inferences
- For CPTs P(trait state | cultivar), the ICRISAT xlsx is the best open base. Its licence is ShareAlike, so derived tables shipped in an app must be CC BY-SA. It is mostly landrace and germplasm (IS numbers), not released cultivars.
- Named cultivars can be cross-referenced only where a released variety is also an IS accession, or by hand-encoding IIMR and Ethiopian free-text descriptions.
- GRIN's "Mixed" and "Segregating" counts and its multi-environment scoring are useful for estimating within-accession variability and smoothing priors.

### Gaps
- No open per-variety DUS descriptions were found for sorghum in UPOV, CPVO, or the Kenya, Nigeria or Sudan registers. KEPHIS and Nigeria's NASC catalogues were not checked; search found nothing with descriptor states.
- The PPV&FRA guideline PDF and the full 33-characteristic list were not obtained.
- No seed-company catalogues with structured descriptor states were found.
- The licence of GRIN data was not stated on the pages opened.

## 2. Descriptor standards (IBPGR/ICRISAT 1993, UPOV TG/122) and which traits are visual

### Takeaway
- **IBPGR/ICRISAT Descriptors for Sorghum (1993):** freely available as a PDF and as an online Genesys descriptor list of 40 descriptors.
- **UPOV TG/122/4 (2015-03-25):** 36 characteristics, about 25 assessed visually (VG).
- **Shared visual core across both:** plant/stem pigmentation, midrib colour, glume colour, grain colour, panicle compactness and shape, awns, glume covering, grain lustre and subcoat, and endosperm texture and colour.

### Cited Findings

**IBPGR/ICRISAT 1993**
- The manual is available as a PDF at [ICRISAT OAR RA_00246.pdf](https://oar.icrisat.org/1011/1/RA_00246.pdf) (ISBN 92-9043-135-0). Fetching failed with an SSL error; the record is at [oar.icrisat.org/1011](https://oar.icrisat.org/1011).
- The Genesys online list (IBPGR, 1993) has 40 descriptors, opened. They include:
  - Plant colour
  - Leaf midrib colour
  - Waxy bloom
  - Inflorescence compactness and shape
  - Glume colour
  - Grain covering
  - Awns
  - Grain colour
  - Grain lustre
  - Grain sub-coat
  - Grain form
  - Endosperm texture, colour and type
  - Inflorescence exsertion
  - Source: [Genesys descriptor list](https://www.genesys-pgr.org/descriptorlists/6291a6d8-d034-4c16-b302-59f9e92b9cdc)
- States for the key visual descriptors, from the same [Genesys descriptor list](https://www.genesys-pgr.org/descriptorlists/6291a6d8-d034-4c16-b302-59f9e92b9cdc):
  - Glume colour: White, Sienna, Mahogany, Red, Purple, Black, Grey, Other
  - Grain colour: White, Yellow, Red, Brown, Buff, Other
  - Inflorescence compactness and shape (13 states): very lax; very loose erect or drooping; loose erect or drooping; semi-loose erect or drooping; semi-compact elliptic; compact elliptic; compact oval; half broom corn; broom corn; other
  - Plant colour: Pigmented, Tan
  - Midrib colour: White, Dull green, Yellow, Brown, Purple, Other
- No licence is stated on the Genesys page.
- A later Bioversity "key descriptors" list builds on the 1993 edition. [CGIAR Genebank key descriptors](https://genebanks.cgiar.org/resources/publications/key-descriptors-sorghum) (search result)

**UPOV TG/122/4 (opened via a COBORU-hosted PDF, text extracted)**
- Scope is Sorghum bicolor and S. ×drummondii. It has 36 characteristics. [TG/122/4 PDF (COBORU mirror)](https://coboru.gov.pl/Publikacje_coboru/Metodyki/UPOV/TG1224%20z%2025.03.2015.pdf); UPOV original: [tg122.docx](https://www.upov.int/edocs/tgdocs/en/tg122.docx)
- Characteristics with VG (visual) assessment, with growth stage and states:
  - 1 Seedling anthocyanin of coleoptile (12–14)
  - 2 Leaf blade anthocyanin (15)
  - 4 Leaf intensity of green (45–59)
  - 5 Leaf midrib colour, PQ, asterisked: white, yellowish white, light green, light yellow, medium yellow, dark yellow, brownish
  - 6 Area of midrib discoloration
  - 8 Glume anthocyanin (65–69)
  - 9 Stigma anthocyanin
  - 10 Stigma colour, PQ, grouping: white, light yellow, medium yellow, dark yellow, grey
  - 11 Stigma length
  - 12 Flower length
  - 13 Self-fertility
  - 14 Glume colour at end of flowering, PQ: light green, medium green, yellow green, light yellow, medium yellow
  - 15 Panicle density at end of flowering
  - 16 Lemma arista (awn) length, asterisked
  - 17 Dry anther colour, PQ, asterisked: light yellow, greyish pink, orange, orange red, red, red brown
  - 25 Panicle density at maturity, grouping: very sparse to very dense
  - 26 Position of broadest part of panicle, grouping: very low to very high
  - 27 Glume colour at maturity, PQ, asterisked: white, light yellow, medium yellow, light brown, reddish brown, dark brown, black
  - 28 Glume length
  - 29 Grain colour, PQ, grouping: white, yellowish white, grey white, light yellow, orange, orange red, light brown, red brown, dark brown, purple, black
  - 31 Grain shape in dorsal view: narrow elliptic, broad elliptic, ovate, circular
  - 32 Size of germ mark
  - 34 Endosperm type: fully vitreous to fully farinaceous
  - 35 Colour of vitreous endosperm: white, yellow, orange, violet
- Characteristics with VG/MS (visual or measured): 20–21 leaf blade length and width, 22 panicle length, 23 neck length, 24 primary branch length.
- Characteristics that are MS or MG only: 3 tillers (MS/MG/VG), 7 time of panicle emergence, 18 plant length (17-state scale from dwarf to giant), 19 stem diameter, 30 1000-grain weight, 33 tannin, 36 photoperiod sensitivity. [TG/122/4](https://coboru.gov.pl/Publikacje_coboru/Metodyki/UPOV/TG1224%20z%2025.03.2015.pdf)
- The superseded TG/122/3 dates from 1989-10-06. [UPOV TG/122/3](https://www.upov.int/de/publications/tg-rom/tg122/tg_122_3.pdf) (search result)

### Inferences
- The UPOV and IBPGR state vocabularies differ. UPOV has 7 glume-colour states; IBPGR has 8; GRIN has 9 codes, including Tan, Straw, Mixed and Segregating.
- The app needs a crosswalk to harmonise these into a coarser, phone-observable state set, for example glume: white/straw, yellow/tan, red/brown, purple/black.
- Growth-stage dependence is strong: glume colour at flowering differs from glume colour at maturity. The app should ask the growth stage, or restrict itself to maturity traits (25–29, 31, 34–35).

### Gaps
- The PDF of the IBPGR 1993 manual could not be opened (SSL error), so its minimum or "highly discriminating" descriptor subset was not verified.
- The example varieties in the UPOV table were not extracted.

## 3. Methods: trait-based or Bayesian identification, concept bottlenecks, calibration, DUS grouping

### Takeaway
- Tyrrell (2019) is a directly relevant naive-Bayes identification-key method. It uses Gaussian likelihoods for continuous characters, frequency-weighted PMFs for discrete ones, additive smoothing, and an evidence score in decibels. It is open (CC BY 4.0) and has R code.
- No concept-bottleneck model applied to plant species or cultivar ID was found. Only post-hoc concept explanation (TCAV) for plant disease exists, and the general CBM literature warns of concept leakage.
- UPOV DUS testing handles near-identical varieties with "grouping characteristics", then side-by-side comparison. Its 8 sorghum grouping characteristics are a ready-made coarse first stage.

### Cited Findings

**Tyrrell 2019, Applications in Plant Sciences 7(5): e1247 (DOI 10.1002/aps3.1247), opened.** Source for all points below: [PMC6526653](https://pmc.ncbi.nlm.nih.gov/articles/PMC6526653)
- Continuous characters are modelled as normal distributions per taxon. A measurement with known precision is integrated over its interval.
- Discrete states use a uniform PMF, which can be weighted by observed frequency.
- Characters are combined under the independence assumption using log-sums. Additive smoothing avoids zero probabilities.
- "Jaynes evidence" is 10·log10 of the odds, in dB.
- The author's stated limitations: correlated characters (augmented naive Bayes is suggested), normality assumptions, range-only data, and small samples.
- Tests on Myriophyllum and Rhipidocladum showed ambiguous zones that one published dichotomous key splits wrongly. Combining 2 characters still produced a MAP tie for one type specimen.
- Code is at GitHub cdtyrrell/id-key. The article is CC BY 4.0.

**Concept bottleneck models**
- Concept explainability for plant disease uses a tomato-disease ontology plus TCAV. This is post hoc, not a bottleneck architecture. [Amara et al., arXiv 2309.08739](https://ar5iv.labs.arxiv.org/html/2309.08739) (search snippet)
- Known CBM failure modes are reported in search snippets, not opened:
  - Concepts may not map to semantically meaningful input regions: ["Do Concept Bottleneck Models Learn as Intended?"](https://cs.paperswithcode.com/paper/do-concept-bottleneck-models-learn-as)
  - Information leakage through concept probabilities: [arXiv 2202.01459](https://arxiv.org/abs/2202.01459v1)
- The CBM decision-support study used CUB birds with 6 concepts and excluded subjective colour descriptions. [arXiv 2608.25581](https://arxiv.org/pdf/2608.25581) (search snippet)

**Trait-to-taxon machine learning**
- Random forest and gradient boosting predicted Helianthus species from functional traits with high accuracy. [PMC11443442](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11443442/) (search snippet)
- Three traits (height, SLA or leaf habit, leaf size) were enough to separate Pacific Northwest understory species. Search snippet; source among the [PMC results](https://pmc.ncbi.nlm.nih.gov/articles/PMC7394705), not verified which article.

**How DUS testing groups indistinguishable varieties (UPOV TG/122/4, sections 5.1–5.3)**
- Grouping characteristics select which reference varieties can be excluded from the trial, and arrange the trial so that similar varieties are grown together.
- The 8 sorghum grouping characteristics are:
  - Time of panicle emergence (7)
  - Stigma colour (10)
  - Self-fertility (13)
  - Plant length (18)
  - Panicle density at maturity (25)
  - Position of broadest part (26)
  - Grain colour (29)
  - Photoperiod sensitivity (36)
- Uniformity and stability of hybrids may be assessed through their parent lines.
- Source: [TG/122/4](https://coboru.gov.pl/Publikacje_coboru/Metodyki/UPOV/TG1224%20z%2025.03.2015.pdf)

### Inferences
- For a phone app, a naive Bayes model over harmonised descriptor states is a sound design if it does the following:
  - Uses the Tyrrell treatment: Gaussian likelihoods for height, panicle length and seed size, and frequency-weighted categorical CPTs with Laplace smoothing taken from GRIN or ICRISAT state frequencies.
  - Reports the top-k results with an evidence or posterior margin.
  - Merges cultivars whose descriptor profiles are identical into "indistinguishable groups", as DUS grouping does, instead of forcing a single answer.
- If image models predict the traits (a CBM-style pipeline), their calibrated per-trait probabilities can be passed as soft evidence into naive Bayes. Leakage is not an issue there because naive Bayes consumes only the concept probabilities.

### Gaps
- No published naive Bayes or Bayesian sorghum cultivar identifier was found.
- No plant-specific CBM paper and no paper on calibrating trait-prediction probabilities in plant vision were found.
- Literature on temperature scaling and calibration was not searched.

## 4. Colour and scale calibration on phones (PlantCV, smartphone accuracy, RHS mapping)

### Takeaway
- PlantCV provides colour-card correction (`transform.correct_color`, using a 24-patch ColorChecker Passport) and card detection.
- Smartphone colour studies show good agreement with instruments after calibration:
  - Phone-app Lab values vs a chromameter on chrysanthemums: R² > 0.85.
  - A UPOV-reported image-to-RHS match rate of 98% (snippet only).
- No plant study reporting ΔE for smartphone plus ColorChecker was found.

### Cited Findings

**PlantCV**
- `pcv.transform.correct_color` uses a 24-colour ColorChecker Passport in its example. It returns target, source and transformation matrices (saved as .npz) and a corrected image. Masks come from `detect_color_card`. The page does not state the transformation maths or any accuracy figures. [PlantCV docs](https://docs.plantcv.org/en/latest/transform_correct_color/) (opened)

**Smartphone colour accuracy studies (all from search snippets)**
- Chrysanthemum study (UGM, Indonesia): flower colour was first scored on the RHS Colour Chart. Iro Shirabe app L\*a\*b\* values on an iPhone 11 Pro Max and a Realme XT agreed closely with a chromameter (R² > 0.85). [Jurnal UGM](https://journal.ugm.ac.id/jbp/article/download/75631/37205)
- UPOV TWC/24/15: photos of RHS charts and petals on a black board with an 8-colour ruler, black/white calibration, and an RHS-number-to-RGB database. Across 51 varieties, inner petal colour matched manual observation 98% of the time, with 86% matching the first RHS chart number. Snippet only; fetching failed with an SSL handshake error. [UPOV TWC/24/15](https://www.acc.upov.int/edocs/mdocs/upov/en/twc/24/twc_24_15.pdf)
- Rice leaves (86 samples, smartphone, outdoor light, SpyderCheckr calibration): calibration improved correlation with SPAD and chlorophyll, with 87.9–92.3% precision for SPAD prediction. [Planta Tropika](https://journal.umy.ac.id/index.php/pt/article/download/20553/9482)
- Bristol 2011: cheap custom colour targets placed in the scene, rather than characterising each camera, for plant pathology with low-quality cameras. [SciTePress 2011](https://www.scitepress.org/Papers/2011/32913/)
- Leaf colour chart relative calibration with KNN: more than 83% accuracy across 2 phones. [ITS OAJIS](https://is.its.ac.id/pubs/oajis/index.php/home/detail/1250/Assessment-of-Color-Levels-in-Leaf-Color-Chart-Using-Smartphone-Camera-with-Relative-Calibration)

### Inferences
- Putting an in-frame reference card (ColorChecker-style, or a cheap printed card) next to the panicle or grain, then converting to CIELAB, then using nearest-neighbour matching to harmonised descriptor colour states, is supported by this evidence.
- The UPOV RHS work suggests coarse descriptor classes (for example, 7–11 grain colours) are achievable. A known object in frame (the card) also gives scale for seed size and panicle length.

### Gaps
- No ΔE2000 accuracy figures were found for smartphone plus ColorChecker on plant tissue.
- PlantCV's algorithm details and licence were not confirmed on the opened page. The project is MIT-licensed on GitHub as far as I know, but that was not verified here.
- The UPOV TWC/24/15 PDF could not be opened.

## 5. On-device models: MobileNetV3/LiteRT plant apps, accuracy and latency

### Takeaway
- PlantVillage Nuru is the best-documented offline field app. On cassava:
  - 65% (±3) accuracy on the CaSRAT test in 2020, against 49% for trained extension officers and 23% for trained farmers.
  - About 73–93% per disease when 6 leaves per plant are assessed.
  - The article gives no latency figures and does not name the architecture.
- MobileNetV3 phone latency figures exist only in search snippets: for example, about 3.9 ms and 94.5% accuracy for a 1.18 MB quantised TFLite MobileNetV3-Small model on corn leaves (unverified).

### Cited Findings

**PlantVillage Nuru (Mrisho et al. 2020, Frontiers in Plant Science, DOI 10.3389/fpls.2020.590889, opened).** Source for all points below: [Frontiers](https://www.frontiersin.org/journals/plant-science/articles/10.3389/fpls.2020.590889/full)
- Nuru is a deep-learning object-detection model that runs offline on the live camera feed.
- CaSRAT accuracy rose from 40% (±10) in 2018 to 65% (±3) in 2020. For comparison:
  - Extension officers: 49% trained, 32% untrained
  - Farmers: 23% trained, 12% untrained
  - Researchers: 86% trained
- Single-leaf field accuracy: CMD 59%, CBSD 21%, CGM 56%, asymptomatic 90%.
- With 6 leaves: CMD 93%, CBSD 73%, CGM 93%. The abstract gives 74–88%.
- Phones used:
  - Field test: Huawei P10
  - 2020 CaSRAT test: Galaxy A10, Infinix Hot 7, Tecno Camon CM, Tecno Spark3 Pro and Huawei P30, with overall scores of 62–68%
- No latency is reported and the architecture is not named. Abstract figures (extension agents 40–58%, farmers 18–31%) differ from the subgroup figures above.

**MobileNetV3 on phones (search snippets, not opened)**
- Corn leaf: MobileNetV3-Small, 94.54% accuracy, 1.18 MB dynamic-range-quantised TFLite model, 3.89 ± 0.04 ms on an Android CPU. Device not verified. [MDPI Electronics 15:3343](https://mdpi-res.com/d_attachment/electronics/electronics-15-03343/article_deploy/electronics-15-03343.pdf)
- Distilled MobileNetV3 for tomato disease: int8 TFLite on Android and Raspberry Pi 4, 22.96 ms CPU latency (device unclear). [arXiv 2504.16128](https://arxiv.org/pdf/2504.16128)
- Improved lightweight MobileNetV3 for agricultural disease identification. [arXiv 2207.11238](https://arxiv.org/pdf/2207.11238)
- A TFLite detection pipeline lost accuracy in conversion (mAP@0.5 0.984 → 0.908) and averaged 4,991.5 ms/frame on a mid-range Android phone (architecture unclear). [arXiv 2508.10817](https://arxiv.org/pdf/2508.10817v1)

### Inferences
- Nuru's main lesson for this app is that aggregating several observations per plant greatly improves field accuracy. This maps naturally onto naive Bayes: multiply the likelihoods from several panicles or leaves.
- The 3–25 ms MobileNetV3-Small latencies suggest per-trait classifier heads (glume colour, grain colour, panicle shape) are cheap on-device, and naive Bayes inference over a few hundred cultivars is negligible.

### Gaps
- The MobileNetV3 latency and accuracy figures were not verified from full text.
- No sorghum-specific on-device trait app was found.
- LiteRT (the renamed TFLite) benchmark documentation was not opened.
