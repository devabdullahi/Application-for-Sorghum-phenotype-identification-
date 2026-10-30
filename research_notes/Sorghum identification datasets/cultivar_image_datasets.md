# Sorghum image datasets for cultivar identification and trait classification (as of Oct 2026)

Scope: public sorghum image datasets (leaf, panicle, grain/seed, whole plot) with cultivar/accession labels or trait labels; key results; phone-based studies; reusable pretrained models. Every page cited below was opened unless marked "(not opened: 403/429)". Licence/download status is recorded as found on the page; "not stated" means the opened page did not state it.

## 1. Datasets with cultivar / variety / accession labels

### Takeaway
Sorghum-100 (TERRA-REF, 100 cultivars, 48,106 gantry RGB images, cultivar-labelled, hosted as a Kaggle FGVC competition) is the only large openly hosted cultivar-labelled sorghum image set found. It is overhead field imagery of whole plots, not organ close-ups, and its licence could not be confirmed. Seed-level cultivar datasets (Yang 2025, 8 varieties; Aqil 2025, 5 Indonesian varieties) exist in papers, but neither is publicly downloadable. Yang 2025 is "available from the authors", and Aqil 2025 has no data statement on the page I opened. No Kaggle, Indian, African or USDA sorghum seed-variety image set was found.

### Cited Findings
**Sorghum-100 / TERRA-REF (Ren et al., CVPRW 2021)**
- 48,106 RGB images of 100 sorghum cultivars, grown June 2017, captured mid-season by the TERRA-REF gantry field scanner (Maricopa, AZ). Images are labelled by cultivar and day after planting — [Ren et al., arXiv 2106.05748 (ar5iv)](https://ar5iv.labs.arxiv.org/html/2106.05748)
- Images are plot crops cut out using camera-position metadata and plot boundaries. Crops include ground and soil, and plant parts are cut off at plot edges. Each cultivar was planted in two plots: training uses one plot and test the other, so models must generalise across field locations — [ar5iv](https://ar5iv.labs.arxiv.org/html/2106.05748)
- Results (test accuracy): whole-image average pooling 0.721; the best, multi-resolution (high + low res) multi-crop with Dynamic Outlier Pooling, 0.788 — [ar5iv](https://ar5iv.labs.arxiv.org/html/2106.05748)
- The paper only says the dataset "will be released publicly" with a Kaggle competition. It gives no licence or direct link — [ar5iv](https://ar5iv.labs.arxiv.org/html/2106.05748)
- Kaggle hosts it as "Sorghum-100 Cultivar Identification - FGVC 9" (kaggle.com/competitions/sorghum-id-fgvc-9). The page renders only its title to an unauthenticated fetch, so data rules and licence could not be read — [Kaggle FGVC9 data](https://www.kaggle.com/competitions/sorghum-id-fgvc-9/data), [Kaggle overview](https://www.kaggle.com/competitions/sorghum-id-fgvc-9/overview)
- TERRA-REF describes Sorghum-100 as a curated, cultivar-labelled subset of TERRA-REF RGB imagery and links kaggle.com/c/sorghum-100 — [TERRA-REF publication page](https://terraref.org/publication/multi-resolution-outlier-pooling-sorghum-classification.html)
- The parent TERRA-REF Dryad release (doi:10.5061/dryad.4b8gtht99, Aug 2020) is 800 MB: metadata, sensor data catalogues, trait data and code. It covers a sorghum diversity panel. The page names no specific licence ("licensed for reuse" under Dryad terms), and raw imagery is not in the Dryad files — [Dryad TERRA-REF](https://datadryad.org/dataset/doi:10.5061/dryad.4b8gtht99)

**TERRA-REF imagery labelled by genetic marker (Zhang et al., Frontiers in AI 2022)**
- Same gantry RGB images (2017, June; raw 3296×2016, plot-cropped, resized to 512×512) from the Bioenergy Association Panel (390 cultivars). CNNs predicted reference vs alternate alleles for five marker families: leaf wax, dw (height), Dry Stalk d locus, ma (maturity) and tan (pigmentation). Leaf wax split: 67/114 training cultivars, 6,700/11,400 training images — [Zhang et al. 2022](https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2022.872858/full)
- The embedding network did best, with per-cultivar accuracy about 0.65–0.83 (d locus 0.833, ma 0.650; chance 0.5) — [Zhang et al. 2022](https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2022.872858/full)
- Code, cultivar_labels.csv and dataset_split.pkl are at github.com/GWUvision/sorghum-snp-classification. No licence file is visible and no pretrained weights are listed, although the paper says pretrained models are there — [GitHub repo](https://github.com/GWUvision/sorghum-snp-classification); [paper](https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2022.872858/full)

**SG×P benchmark (NeurIPS 2023 Datasets and Benchmarks)**
- Genotype data plus a time series of field-plot RGB and laser 3D scanner imagery for more than 300 sorghum varieties. Hosted at sorghumsnpbenchmark.com. The abstract page states neither the image count nor the licence — [NeurIPS proceedings](https://proceedings.neurips.cc/paper_files/paper/2023/hash/39d02e8e23bafadd7cd405f2281bc05c-Abstract.html)

**Yang et al. 2025 seed dataset (Frontiers in Plant Science 16:1632698)**
- 8 varieties from the Jilin Academy of Agricultural Sciences (JZ127, JZ136, JZ141, JZ159, JZ160, JZ177, JZ186, JZ187); 12,800 seeds (1,600 per variety); 7:2:1 split — [Yang et al. 2025, PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC12412220/)
- RGB from a Nikon D7100. Seeds were segmented from multi-seed images and cropped to 224×224 on a dark background (per the figure). Each seed also has an ASD FieldSpec4 350–2500 nm spectrum, rendered as a curve image and fused side by side with the RGB crop (224×448×3) — [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC12412220/)
- Accuracy: RGB-only ResNet50 86.64%; RGB+HSI ResNet50 89.61%; proposed CBAM-ResNet50-DSC 94.84% — [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC12412220/)
- Data availability: "The raw data ... will be made available by the authors, without undue reservation." This means on request, not public. The public datasets the paper used for generalisation tests (Mendeley v6vzvfszj6; Kaggle DOIs 10.34740/kaggle/dsv/8681789 and /6457847) are rice, maize and soybean seed sets, not sorghum — [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC12412220/)

**Aqil 2025, tropical (Indonesian) sorghum varieties (J. Agriculture and Food Research, doi:10.1016/j.jafr.2025.101931)**
- 5 varieties: Numbu, Kawali, Super 1, Suri 3 Agritan, Super 4, from sites in South Sulawesi. The best stacking ensemble (SqueezeNet + LR, Bayesian search) reached 0.978; VGG16-KNN reached 0.924 — [UNHAS record](https://discover.unhas.ac.id/publications/pub_scopus_105003734046)
- The record is inconsistent on organ (the abstract says seed, a highlight says panicle). No image count and no data statement appear on the page — [UNHAS record](https://discover.unhas.ac.id/publications/pub_scopus_105003734046)

### Inferences
- For validating cultivar ID from close-up leaf, panicle or grain phone photos, no public sorghum dataset matches the target domain. Sorghum-100 is overhead plot imagery dominated by leaf canopy, so it validates fine-grained canopy discrimination, not panicle or grain ID. A team-collected, cultivar-labelled phone dataset will likely be needed.
- Sorghum-100 baselines (~72–79% for 100 classes, under a cross-plot split) show that fine-grained cultivar ID is hard even with dense same-season imagery.
- The Yang 2025 RGB-only result (86.6% for 8 varieties from seeds) is a realistic reference for seed-image cultivar ID with a small number of locally adapted varieties.

### Gaps
- Exact licence and rules for Sorghum-100 on Kaggle could not be read (the page needs JavaScript or login). Kaggle competition data is often limited to competition or non-commercial use, but this is unverified. Confirm it by logging in to Kaggle.
- I found no public Kaggle, Indian (ICRISAT/IIMR), African or USDA-GRIN sorghum seed-variety image dataset. GRIN and genebank passport pages surfaced in searches, but none with labelled image sets.
- Whether Yang 2025 data can actually be obtained (it is on request only).

## 2. Datasets with trait labels (panicle, grain colour/size, leaf, disease)

### Takeaway
Panicle detection and counting data are the richest category: UAV head-detection sets from Australia, a smartphone panicle set from Kansas, and 3D point-cloud panicle sets. Most of the image sets, though, are supplementary-only, gated (form or request) or CC BY-NC. I found no public dataset with morphological descriptor labels (waxy bloom, panicle compactness/shape, glume colour, grain covering, awns, lustre, plumpness). Grain colour has one strong study (2024 bioRxiv, >1,500 scanner images), but I could not verify its data availability.

### Cited Findings
**Panicle detection / counting (UAV)**
- Guo et al. 2018 (Frontiers in Plant Science, 10.3389/fpls.2018.01544): Sony RX100M3 on a UAV at 20 m, 5472×3648 px, GSD 0.45 cm, 2,109 images, 1,440 plots, 22 checks plus 903 test-cross hybrids (Hermitage, QLD). Head pixel classes were green, orange and white. F-measure was 0.92 (Dataset 1) and 0.89 (40 plots). "Datasets 1 and 2 along with the manual labeling ... are available in the Supplementary Materials" — [Guo et al. 2018](https://frontiersin.org/journals/plant-science/articles/10.3389/fpls.2018.01544/full)
- Ghosal et al. 2019 (Plant Phenomics, weakly supervised RetinaNet): same trial; 1,269 labelled plot images with bounding boxes (KITTI format); mAP 0.941 at IoU 0.5; plot-count R² 0.88. Heritability of head number was 0.65, against 0.31 from human counts. The model fails on white-head genotypes — [Ghosal et al. 2019, PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC7706102)
- The DeepSorghumHead repo ships trained Keras RetinaNet weights. The image dataset is gated behind a Google Form, and no licence is visible — [github.com/oceam/DeepSorghumHead](https://github.com/oceam/DeepSorghumHead)
- UQ "Sorghum diversity head counting dataset" (doi:10.48610/45BEB77): UAV images of a diversity trial at Gatton, 2015–16, linked to "Diffusion Fields" panicle counting. Licence CC BY-NC 4.0, "Restrictions apply", access by request. No image count stated — [Research Data Australia](https://researchdata.edu.au/sorghum-diversity-head-counting-dataset/4011317)
- Purdue authors note that labour-intensive ground truthing of UAV images is a bottleneck for sorghum panicle detection — [arXiv 2205.03947](https://arxiv.org/pdf/2205.03947) (seen in search results only, not opened)

**Panicle 3D**
- SegVoteNet (James, Chandra & Chapman, Plant Phenomics 2025, 10.1016/j.plaphe.2025.100050): UAV (DJI Mavic 3E) video and grid flights at 5 m, reconstructed with SfM and NeRF into plot point clouds; 14 commercial cultivars. Synthetic training set of 600 plots; real test set of 40 row models with 1,337 panicles. Detection mAP@0.5 is 0.850 on real test (0.986 on synthetic); panicle segmentation accuracy 0.936. Field vs lab panicle length r = 0.938 (MAE 1.18 cm). Open vs semi-open panicle type is described only qualitatively; compactness is not measured — [PMC12709908](https://pmc.ncbi.nlm.nih.gov/articles/PMC12709908/)
- The SegVoteNet GitHub holds dataset samples (real/ and synthetic/ folders, whose README labels appear swapped) and a pretrained checkpoint (MMDetection3D 1.4.0). No licence is visible — [github.com/chr15-j/SegVoteNet](https://github.com/chr15-j/SegVoteNet)
- Mendeley "Sorghum Plants Labeled 3D LiDAR Point Cloud Data" (doi:10.17632/pfnfzrmrg7.1, Aug 2023): point-wise labels for leaf, stem and panicle — [Mendeley](https://data.mendeley.com/datasets/pfnfzrmrg7/1) (search snippet only; licence not verified)
- Freeman et al., ICRA 2023, "3D Reconstruction-Based Seed Counting of Sorghum Panicles": the arXiv page gives no dataset or code link — [arXiv 2211.07748](https://arxiv.org/abs/2211.07748). Papers-with-Code lists a related dataset, "High-Resolution Stereo Scans of 100 Sorghum Panicles" — [PwC](https://paperswithcode.com/dataset/high-resolution-stereo-scans-of-100-sorghum) (not opened; hosting and licence unknown)
- No CT-based sorghum panicle image dataset was found.

**Grain / seed colour and size**
- bioRxiv 2024.07.22.604683, "Off-the-shelf image analysis models outperform human visual assessment in identifying genes controlling seed color variation in sorghum": more than 1,500 flatbed-scanner seed images. It used seed-analysis models trained on rice or wheat, extracted seed size and colour intensities, and got stronger GWAS signals than manual colour scoring. Later published in Plant Phenome Journal (10.1002/ppj2.70013) — [bioRxiv](https://www.biorxiv.org/content/10.1101/2024.07.22.604683v1) (not opened: 429; details from search summary); [Wiley](https://acsess.onlinelibrary.wiley.com/doi/10.1002/ppj2.70013) (not opened: 403)
- "Sorghum-grain-count: A large image dataset and benchmark for sorghum grain count estimation" (ScienceDirect, PII S2772375525004496, 2025). Panicle and quadrant images are bounding-box annotated in LabelMe — [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S2772375525004496) (not opened: 403; ResearchGate also 403). Image counts, varieties, licence and link are unverified.

**Leaf / disease / weeds (contain sorghum leaves)**
- Mendeley "Sorghum Disease Image Dataset" (Thite & Patil, doi:10.17632/fgb3cmfrg2.1, 14 Jun 2024): 7,167 JPEGs. Classes are anthracnose & red rot, cereal grain molds, covered kernel smut, head smut, loose smut and rust; no healthy class is listed. Licence CC BY 4.0, downloadable. Capture device and setting are not stated — [Mendeley](https://data.mendeley.com/datasets/fgb3cmfrg2/1)
- Mendeley "SorghumWeedDataset_Classification" (doi:10.17632/4gkcyxjyss.1): 4,312 field RGB images (1,404 sorghum seedlings, 1,467 grass, 1,441 broadleaf), Canon EOS 80D (6000×4000, resized to 224×224), Tamil Nadu, India, 2023. Licence CC BY 4.0 — [Mendeley](https://data.mendeley.com/datasets/4gkcyxjyss/1); companion data paper — [Data in Brief, PMC10789999](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10789999/) (not opened)

**Descriptor-trait labels (glume colour, compactness, shape)**
- I found no image dataset labelled for panicle compactness, shape or glume colour. Standard descriptor classes exist (glume colour such as sienna, mahogany, red, black, purple, white, grey; compactness compact, semi-compact, semi-loose, loose; shape classes), and an ICRISAT table gives their frequencies across about 5,300 South Asian accessions — [PMC9218377 table](https://pmc.ncbi.nlm.nih.gov/articles/PMC9218377/table/tbl2) (search snippet only, not opened)
- The nearest learned-trait proxy is Zhang 2022, where TERRA-REF CNNs classify leaf wax (waxy bloom related) and tan (pigmentation) alleles from plot images at about 0.65–0.83 per-cultivar accuracy — [Zhang et al. 2022](https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2022.872858/full)

### Inferences
- Panicle detectors are well covered, so a panicle-localisation stage (crop the head before trait classification) can be bootstrapped from existing data and models. Note the domain shift: most of this is UAV top-view imagery, not side-view phone shots, and white heads are a known failure mode.
- Trait classifiers for waxy bloom, compactness, glume colour, covering, awns, lustre and plumpness will need team-labelled data, using IBPGR/ICRISAT descriptor classes as the label schema.
- Grain colour and size can probably be measured with off-the-shelf seed-segmentation tools rather than a learned classifier, as the 2024 bioRxiv work suggests.

### Gaps
- Data availability and licence for the 2024 seed-colour study (bioRxiv/PPJ) and the Sorghum-grain-count dataset: both pages were blocked (429/403).
- Image counts and contents of the Guo 2018 supplementary zip and the Ghosal 2019 supplementary zip (51.8 MB) were not checked.
- Licence of the Mendeley LiDAR point-cloud set and the hosting of "Stereo scans of 100 panicles".
- Leaf midrib (dry/juicy) image datasets: none found. No search was run specifically for midrib.

## 3. Image type summary per dataset

### Takeaway
Almost all large labelled sorghum image sets are field UAV or gantry (top-down, soil and canopy background) or lab seed images on a dark or scanner background. Only the Kansas set (Santiago 2024) is a phone-in-field set of panicles, and it is on request.

### Cited Findings
| Dataset | Organ | Setting / device | Size | Labels | Licence | Download |
|---|---|---|---|---|---|---|
| Sorghum-100 (TERRA-REF) | Whole plot (canopy) | Field gantry RGB, top-down, soil background | 48,106 imgs, 100 cultivars | Cultivar | Not confirmed | Kaggle competition — [ar5iv](https://ar5iv.labs.arxiv.org/html/2106.05748) |
| TERRA-REF BAP marker set | Plot | Gantry RGB 3296×2016 | ~18k training imgs per marker | Allele (leaf wax, tan, dw, d, ma) | Not stated | Labels/splits on GitHub — [Zhang 2022](https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2022.872858/full) |
| SG×P | Plot | Field RGB + 3D laser | >300 varieties | Genotype | Not stated | sorghumsnpbenchmark.com — [NeurIPS](https://proceedings.neurips.cc/paper_files/paper/2023/hash/39d02e8e23bafadd7cd405f2281bc05c-Abstract.html) |
| Yang 2025 seeds | Grain | Lab, Nikon D7100, dark background, + ASD spectra | 12,800 seeds, 8 vars | Variety | n/a | On request — [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC12412220/) |
| Aqil 2025 | Seed/panicle (unclear) | Not stated | Not stated | 5 vars | n/a | Not stated — [UNHAS](https://discover.unhas.ac.id/publications/pub_scopus_105003734046) |
| Guo 2018 / Ghosal 2019 | Panicle | UAV 20 m, 5472×3648 | 2,109 imgs; 1,269 labelled plots | Head boxes/pixels | Article CC BY | Supplement; full set via Google Form — [Ghosal](https://pmc.ncbi.nlm.nih.gov/articles/PMC7706102), [repo](https://github.com/oceam/DeepSorghumHead) |
| UQ diversity head counting | Panicle | UAV | Not stated | Head counts | CC BY-NC 4.0 | Request access — [RDA](https://researchdata.edu.au/sorghum-diversity-head-counting-dataset/4011317) |
| SegVoteNet | Panicle 3D | UAV video → SfM/NeRF point clouds | 1,337 test panicles, 14 cultivars | Panicle boxes, organ segmentation | Not stated | GitHub samples + checkpoint — [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC12709908/) |
| Santiago 2024 | Panicle | Phone 64 MP, field, other plants behind | 457 + 40 + 198 imgs, 20 hybrids | Panicle masks, grain counts | n/a | On request; code public — [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC11658820/) |
| Sorghum Disease (Mendeley) | Leaf/panicle/grain disease | Not stated | 7,167 | 6 diseases, no healthy class | CC BY 4.0 | Yes — [Mendeley](https://data.mendeley.com/datasets/fgb3cmfrg2/1) |
| SorghumWeedDataset | Seedling | Field DSLR, India | 4,312 | Crop/weed | CC BY 4.0 | Yes — [Mendeley](https://data.mendeley.com/datasets/4gkcyxjyss/1) |

### Inferences
- Openly downloadable with a clear permissive licence (CC BY 4.0): only the two Mendeley sets (disease, weeds), and neither has cultivar or descriptor-trait labels.

### Gaps
- Per-image resolution and background for the Mendeley disease set are not stated.

## 4. Phone-based sorghum phenotyping apps and studies

### Takeaway
The main phone study is Santiago et al. 2024 (Plant Phenomics). From field phone photos of 20 hybrids, YOLOv8 segments panicles (AP50 about 0.89) and a density-map CNN counts grains (MAPE 17%). Its data is on request, and its code is on GitHub. Earlier and adjacent tools exist (OpenCV counter, SorghumYield app, SeedCounter, OpenPheno), but I found no published sorghum-specific phone app for descriptor traits.

### Cited Findings
- Santiago et al. 2024 (Plant Phenomics 0234): generic phone with a 64 MP Sony IMX582 sensor, about 1 m from and parallel to the panicle, other plants in the background, Wamego, Kansas, Oct 2023, 20 commercial hybrids. Detection/segmentation AP50: YOLOv8-seg 0.887/0.890, Detectron2 0.785/0.756. Sorghum-Net density-map grain count MAPE 17%; whole-panicle (two-side) regression MAPE 17%, RMSE 604 grains, R² 0.48. The abstract says 648 images, which conflicts with the Methods (457 + 40 + 198). Data "available upon reasonable request"; code at github.com/GustavoSantiago113/Sorghum_Grain_Counter — [PMC11658820](https://pmc.ncbi.nlm.nih.gov/articles/PMC11658820/)
- An earlier Kansas State report used OpenCV contour grain counting on phone images, with RMSPE 53%. Its authors recommended an AI model and a mobile app — [K-State KAESRR](https://newprairiepress.org/kaesrr/vol9/iss4/6) (search snippet only, not opened)
- SorghumYield app (Bossio et al., 2015 ASA poster): grain number estimation validated on more than 1,700 head pictures; accuracy not given in the snippet — [poster PDF](https://scisoc.confex.com/crops/2015am/webprogram/Handout/Paper93787/Bossio%20etal.pdf) (not opened)
- SeedCounter: an Android app for cereal grain count and size (Frontiers in Plant Science 2017) — [Frontiers](https://www.frontiersin.org/journals/plant-science/articles/10.3389/fpls.2016.01990/epub) (not opened)
- OpenPheno (2025): a smartphone plus cloud platform with a SeedPheno module for seed size and count — [PMC12131570](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12131570/) (not opened)

### Inferences
- Santiago's YOLOv8-seg approach (phone, field background, side view) is the closest published analogue to the target app's panicle-photo pipeline. Its AP50 of about 0.89 is a useful benchmark for panicle segmentation before trait classification.

### Gaps
- PlantCV sorghum-specific workflows were not found in this pass.
- I did not verify whether SeedCounter or OpenPheno report sorghum-specific accuracy.

## 5. Pretrained sorghum-specific models available for reuse

### Takeaway
Three reusable sorghum-specific model artefacts were found: a DeepSorghumHead RetinaNet (UAV head detection, weights in the repo), a SegVoteNet checkpoint (3D panicle detection and segmentation), and the Sorghum_Grain_Counter code (phone panicle and grain; whether weights are included was not checked). None states a licence. The TERRA-REF marker classifier repo provides labels and splits but no visible weights.

### Cited Findings
- DeepSorghumHead (Keras RetinaNet), with trained and fine-tuned models in DeepSorghumHead_Keras/bin/inf_models/. No licence is visible — [GitHub](https://github.com/oceam/DeepSorghumHead)
- SegVoteNet pretrained checkpoint in model_chkpts/ (MMDetection3D 1.4.0). No licence is visible — [GitHub](https://github.com/chr15-j/SegVoteNet)
- Sorghum_Grain_Counter (YOLOv8-seg + Sorghum-Net) code — [PMC11658820](https://pmc.ncbi.nlm.nih.gov/articles/PMC11658820/)
- sorghum-snp-classification: training code, cultivar_labels.csv and dataset_split.pkl. No weights or licence are visible in the listing — [GitHub](https://github.com/GWUvision/sorghum-snp-classification)

### Inferences
- For a phone app, the Santiago YOLOv8-seg panicle segmenter, if its weights are released, is the most domain-relevant starting point. DeepSorghumHead is top-view UAV and would need fine-tuning.
- With no licence stated, a repository is "all rights reserved" by default. Contact the authors before any commercial or redistributed use.

### Gaps
- Whether the Sorghum_Grain_Counter repo includes trained weights was not checked.
- No public pretrained sorghum seed segmenter or seed-variety classifier was found.
