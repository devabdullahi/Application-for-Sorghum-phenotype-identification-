# ADR-0010: What "89% sorghum type accuracy" means, and how to reach it

Status: Draft, **ASSUMPTION — confirm** with the product owner · Date: 2026-10-30

## Context
The product goal is ">= 89% accuracy on identifying sorghum types". ADR-0001 chose trait-first identification: photo → IBPGR/ICRISAT descriptor-state probabilities → naive Bayes over Genesys accession tables → top matches, a group, or "unrecognized". This note checks that goal against the image data that can actually be obtained, and says how accuracy should be measured.

Cultivar-labelled sorghum image data found on 2026-10-29/30 (every page opened):

| Dataset | What it shows | Labels | Licence | Can we get it without an account? |
|---|---|---|---|---|
| **GRIN-Global sorghum IMAGE studies** (USDA-ARS) | Harvested panicles and threshed grain on a grey board with a cm ruler, studio light | Accession (PI/GRIF) per image; 9,410 images, 8,965 accessions, 11 plantings 1993–2012. Only **426 accessions appear in 2+ plantings** (423 in two, 3 in three) | US federal government work, public domain in the US (ASSUMPTION: no licence is shown on the images) | **Yes.** Downloaded (`sorghum-model grin-download`) |
| Sorghum-100 / FGVC9 (TERRA-REF) | Overhead gantry plot crops, canopy and soil | 100 cultivars, 48,106 images; best published 78.8% top-1 cross-plot | Not readable (Kaggle) | No: Kaggle login. No Hugging Face, Zenodo or GitHub mirror exists |
| SG×P (NeurIPS 2023) | Gantry RGB + 3D scans, 300+ cultivars, 543k RGB images | Cultivar folders | CC0 (GitHub repo) | No: every `cs.slu.edu` download link returns 404 (GitHub issue #1, open since 2024-09) |
| TERRA-REF seasons 4 and 6 (2017–18 BAP diversity panel) | Gantry RGB, plot-clipped GeoTIFFs | Plot → cultivar via metadata | CC0 | No: Globus account needed (`ncsa#terra-public`). Only one plot sample zip is on CyVerse |
| PhytoOracle / TERRA-REF seasons 11–20 (CyVerse, anonymous WebDAV) | Raw gantry scans (tarballs per day) | Field books map plot → genotype; mostly EMS mutants of BTx623 plus ~400 accessions | ODC-By 1.0 | Yes, but raw multi-TB tarballs of near-identical BTx623 mutants, overhead only. Not downloaded |
| Image Safari (CGIAR, Hugging Face `Project-AgML/image_safari_sorghum_*`) | Smartphone field photos, Kenya, Tanzania, Malawi, Senegal; 109k images, 6 subsets | Plot id and growth stage only, **no variety** | CC BY-SA 4.0 | Yes, but unusable for cultivar ID (useful later for the species head and phone-domain negatives) |
| Yang 2025 seed set (8 varieties, 86.6% RGB-only) | Lab seed crops | Variety | — | No: on request |

No dataset of phone close-ups (leaf, panicle or grain on a board) labelled by cultivar exists.

## Options
1. **Direct learned cultivar head** (ADR-0001 option 1). A softmax over N cultivars on the shared backbone. Needs many photos per cultivar from several plantings; the data above gives ~1 photo per accession, and Sorghum-100 shows 78.8% top-1 over 100 cultivars even with dense same-season imagery. Adding a cultivar means retraining.
2. **Hybrid: learned cultivar head as one more naive Bayes input** (ADR-0001 option 3). Its errors are correlated with the trait heads (same photo, same backbone), so naive Bayes would count the same evidence twice and become overconfident (risk R4).
3. **Trait-first only (ADR-0001), with a defined, group-aware metric.** Learned and measured traits feed naive Bayes; the result is a top-k list, a group, or "unrecognized".

## Decision (proposed)
Option 3. A direct cultivar head is not added, now or as an independent Bayes input. If one is tried later, it is a separately calibrated reranker evaluated against option 3, never a naive Bayes factor.

"89% accuracy" is defined as follows (ASSUMPTION — confirm which level the product owner means):

- **Primary metric: group-aware accuracy at the "type" level**, where a type is the sorghum race (bicolor, guinea, caudatum, kafir, durra and their intermediates) unless the product owner names another taxonomy. Use type (grain, sweet, forage) is a different taxonomy and must not be mixed in. A result counts as correct when the true type is in the returned group; "unrecognized" counts as an abstention, not a hit.
- **Always reported alongside:** coverage (share of samples that get a specific answer) and selective accuracy (accuracy on those). 89% at 30% coverage is not 89%.
- **Secondary metrics:** exact-accession top-1 and top-3, and mean returned group size, against the cultivar list the app targets (open question R2).
- **Splits:** never by image. Trait heads are evaluated on accessions they never saw (`accession_split`). Cultivar matching is evaluated on a planting the accession was not trained on (`planting_split`, the Sorghum-100 cross-plot idea). The ship test is a phone set captured with the app's own protocol, with its accessions reserved for test only.

## Consequences
- GRIN's photos are the main asset, but for **traits, not cultivar classes**: each photo has an accession whose descriptor observations (seed colour, glume colour, panicle compactness and shape, grain covering) are in GRIN/Genesys, and the ruler gives mm for seed and panicle size. They train learned trait heads and give an end-to-end test of trait-first matching over thousands of accessions.
- Only 426 GRIN accessions have a second planting. That is enough to measure cross-planting matching, but not to train a per-cultivar classifier.
- Domain gap: GRIN is studio light on a grey board, harvested and dry; gantry data is overhead canopy; the app sees phone close-ups with a colour card. Expect lower accuracy on phones until colour correction (ADR-0008) and phone photos exist. Models must not learn the planting (board, light, year) instead of the trait: the accession split keeps that visible.
- Reaching 89% at type level is plausible from traits (race is defined by panicle and spikelet shape, which are visible). 89% exact-cultivar top-1 is an unproven research goal and should not be promised until a representative, accession-disjoint phone test set supports it.
- Blockers needing the user: a Kaggle account (Sorghum-100), a Globus account (TERRA-REF seasons 4 and 6), and a request to the Yang 2025 authors. A team-collected phone set of the target cultivars is still needed for the ship test.
- Second opinion (Codex, 2026-10-30) agreed: no direct head as a Bayes input (double-counted evidence), define the target at race level with group-aware accuracy plus coverage, split by accession and planting, and do not promise exact-cultivar 89% from these data.
