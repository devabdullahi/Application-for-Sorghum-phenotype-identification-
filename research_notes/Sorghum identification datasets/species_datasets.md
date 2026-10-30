# Datasets and pretrained models for an "is it sorghum?" phone classifier

Scope: public image data and models with labelled Sorghum bicolor and look-alike classes (maize, pearl millet, finger millet, sugarcane, Johnson grass, sudangrass, other grasses), for a MobileNetV3-Small binary head running offline on a phone. Researched October 2026. Each page cited below was opened unless marked "(search snippet only)".

## 1. General plant-ID datasets (iNaturalist, Pl@ntNet, PlantNet-300K, GBIF)

### Takeaway
iNaturalist has the most phone-style, whole-plant images of sorghum and its look-alikes. Live counts: Sorghum bicolor about 10.8k observations, Johnson grass about 37.6k, maize about 18.2k, sugarcane about 5.1k, pearl millet about 1.1k and finger millet about 0.2k. That makes finger and pearl millet the small classes. PlantNet-300K (306k images, 1,081 species) has a species-name file, but I could not confirm that Sorghum is one of its classes.

### Cited Findings
- iNaturalist live observation counts at species rank (an observation can hold several photos, so image counts are higher):
  - Sorghum halepense (Johnson grass): 37,595
  - Sorghum bicolor (Sorghum): 10,835
  - Sorghum leiocladum (wild sorghum): 301
  - Other wild Sorghum species: under 110 each
  — [iNat API taxa?q=Sorghum](https://api.inaturalist.org/v1/taxa?q=Sorghum&rank=species&per_page=30)
- The same iNat query returned other tall andropogonoid grasses that look like sorghum, useful as hard negatives:
  - Little bluestem: 34,772
  - Indiangrass (Sorghastrum nutans): 29,366
  - Big bluestem: 29,085
  - King Ranch bluestem: 12,177
  - Thatching grass (Hyparrhenia hirta): 5,769
  — [iNat API](https://api.inaturalist.org/v1/taxa?q=Sorghum&rank=species&per_page=30)
- More iNat live counts:
  - Zea mays (maize): 18,230 observations, plus 736 for Zea mays mays (sweet corn) — [iNat API](https://api.inaturalist.org/v1/taxa/autocomplete?q=Zea%20mays&per_page=5)
  - Cenchrus americanus (pearl millet): 1,082 — [iNat API](https://api.inaturalist.org/v1/taxa?q=Cenchrus%20americanus&per_page=3)
  - Eleusine coracana (finger millet): 229, plus 32 for subsp. africana — [iNat API](https://api.inaturalist.org/v1/taxa?q=Eleusine%20coracana&per_page=3)
  - Saccharum officinarum (sugarcane): 5,128 — [iNat API](https://api.inaturalist.org/v1/taxa?q=Saccharum%20officinarum&per_page=3)
- Sudangrass (Sorghum × drummondii / S. bicolor subsp. drummondii) did not appear in the iNat species-rank query results. — [iNat API](https://api.inaturalist.org/v1/taxa?q=Sorghum&rank=species&per_page=30)
- Pl@ntNet regional species pages list Sorghum bicolor with roughly 1,600 to 2,000 observations, depending on the regional flora (for example, 1,645 in the Comoros flora). Common names given are grain sorghum, Guinea corn and broom-corn. — [Pl@ntNet Comoros page](https://identify.plantnet.org/comores/species/Sorghum%20bicolor%20(L.)%20Moench/data) (search snippet only; the World-flora page returned HTTP 403 to automated fetch)
- PlantNet-300K:
  - 306,146 images of 1,081 species (243,916 train / 31,118 val / 31,112 test)
  - Download from Zenodo record 5645731 (v1.1 recommended)
  - Per-image licence is in `plantnet300K_metadata.json`; code is BSD-2-Clause
  - Species names are in `plantnet300K_species_id_2_name.json`
  - Pretrained ResNet18 weights are linked from the repo, with no weight licence stated
  — [PlantNet-300K GitHub](https://github.com/plantnet/PlantNet-300K)
- TreeOfLife-200M (the BioCLIP 2 training set; it aggregates GBIF/iNat/EOL-style sources):
  - The dataset card lists CC0-1.0
  - It points to a provenance file with per-image licences, so individual images keep their own terms
  — [HF TreeOfLife-200M card](https://huggingface.co/datasets/imageomics/TreeOfLife-200M/blob/refs%2Fpr%2F9/README.md) (search snippet only)

### Inferences
- iNat research-grade photos are mostly phone pictures of whole plants, panicles and field edges. That is the closest match to what app users will take.
  - Download them via the iNat API or the iNat Open Data on AWS, or as a GBIF occurrence download with media filtered to CC0 / CC-BY / CC-BY-NC.
  - Filter by licence: many iNat photos are CC-BY-NC, which is not usable commercially.
- Johnson grass has about 3.5x more observations than cultivated sorghum, so hard negatives are plentiful. Finger millet (about 230 observations) and pearl millet (about 1,100) are thin and will need extra field data or augmentation.
- Some iNat "Sorghum bicolor" observations are probably feral or ornamental, or are sudangrass/shattercane forms. Expect label noise near the decision boundary.

### Gaps
- I could not confirm whether Sorghum bicolor, Zea mays or Johnson grass are among the 1,081 PlantNet-300K classes. The species-name JSON was not fetched, and the dataset skews toward European flora. The team should grep `plantnet300K_species_id_2_name.json`.
- I did not obtain the iNat2021 class list or GBIF image counts (with media) for these species.
- I did not get the per-image licence mix (CC0 / CC-BY / CC-BY-NC) for iNat sorghum photos.
- I found no count for sudangrass.

## 2. Crop/weed field datasets with sorghum, maize or millet

### Takeaway
SorghumWeedDataset is the best openly downloadable field set with labelled sorghum seedlings against grass and broadleaf weeds (about 1.4k images per class). CropAndWeed has maize (six growth-stage labels) and many weedy grasses but no sorghum or millet, and it is non-commercial only. PlantVillage covers maize leaves only, shot in the lab.

### Cited Findings
- SorghumWeedDataset_Classification (Justina & Thenmozhi, Data in Brief 2023):
  - 4,312 images: Sorghum 1,404, grasses 1,467, broadleaf weeds 1,441
  - Images resized to 224×224
  - Taken in the field on a Canon EOS 80D at 6000×4000, 20–40 cm from plants
  - Covers the first four sorghum growth stages, in sun, wind and rain and in morning and afternoon light
  - Location: SRM Care Farm, Tamil Nadu, India; collected April–May 2023
  - Download: [Mendeley 4gkcyxjyss](https://data.mendeley.com/datasets/4gkcyxjyss/1)
  - Segmentation set: 252 images / 5,555 segments, at [Mendeley y9bmtf4xmr](https://data.mendeley.com/datasets/y9bmtf4xmr/1)
  - The article is CC BY 4.0; the dataset licence is not stated in the article
  — [PMC10789999](https://pmc.ncbi.nlm.nih.gov/articles/PMC10789999/)
- CropAndWeed (Steininger et al., WACV 2023):
  - About 112k annotated instances in more than 8k high-resolution images, with boxes, stem positions and semantic masks — [WACV paper page](https://openaccess.thecvf.com/content/WACV2023/html/Steininger_The_CropAndWeed_Dataset_A_Multi-Modal_Learning_Approach_for_Efficient_Crop_WACV_2023_paper.html) (search snippet only)
  - Licence: released "for non-commercial purposes"; download via `setup.py` — [GitHub](https://github.com/cropandweed/cropandweed-dataset)
- CropAndWeed label set:
  - Maize: Maize, plus two-, four-, six- and eight-leaf-stage and max labels (IDs 1–6)
  - Grass weeds: Cockspur grass (Echinochloa), Purple crabgrass, Green bristlegrass (Setaria), Meadow-grass, Annual meadow grass, Wall barley, Annual fescue, Soft brome, Common wild oat, Rye brome
  - Also hemp, sunflower, soybean and others
  - No sorghum and no millet label
  — [datasets.py](https://raw.githubusercontent.com/cropandweed/cropandweed-dataset/main/cnw/utilities/datasets.py)
- Sorghum Disease Image Dataset (Thite & Patil, Mendeley 2024):
  - 7,167 JPEGs of sorghum diseases: Anthracnose & Red Rot, Cereal Grain Molds, Covered Kernel Smut, Head Smut, Loose Smut, Rust
  - No healthy class listed
  - The description says "five major diseases" but names six
  - CC BY 4.0
  — [Mendeley fgb3cmfrg2](https://data.mendeley.com/datasets/fgb3cmfrg2/1)
- PlantVillage (TFDS):
  - 54,303 leaf images in 38 classes, with `Background_without_leaves` removed
  - The TFDS page lists neither per-class counts nor a dataset licence; source is [Mendeley tywbtsjrjv](https://data.mendeley.com/datasets/tywbtsjrjv/1)
  — [TFDS plant_village](https://www.tensorflow.org/datasets/catalog/plant_village)
- A 2025 arXiv comparison table mentions a separate "Sorghum-Weed" dataset from 2022. — [arXiv 2502.13103](https://arxiv.org/html/2502.13103v1) (search snippet only)

### Inferences
- SorghumWeedDataset is close-up seedling imagery from a single Indian farm. It is a good positive set for "young sorghum in a field", but it does not show adult plants or panicles.
- CropAndWeed maize and grass-weed crops (cut out using its bounding boxes) make good hard negatives for research. Do not ship a commercial model trained on it.
- Sorghum disease images show diseased leaves, panicles and grain. They are still sorghum, so they can be used as extra positives for leaf/panicle/grain views, with care about domain bias.
- PlantVillage corn leaves are single detached leaves on a plain background. They are weak negatives for in-field phone photos.

### Gaps
- I did not verify per-class counts for PlantVillage corn classes. They are believed to be Cercospora/grey leaf spot, common rust, northern leaf blight and healthy (unverified).
- I did not verify the Mendeley licence of SorghumWeedDataset.
- I found no open Kaggle/Mendeley dataset with labelled pearl-millet or finger-millet plant images (not searched in depth).
- I did not check DeepWeeds. It is Australian rangeland weeds with no cereals, as I recall (unverified).

## 3. Grain/seed image datasets

### Takeaway
GrainSet (Scientific Data 2023, CC BY 4.0) is the main open source: 102.7k single-kernel sorghum images alongside wheat, maize and rice. It is industrial-camera imagery, not phone photos. GrainSpace (CVPR 2022, 5.25M images) has no sorghum. I found no millet kernel dataset.

### Cited Findings
- GrainSet single-kernel image counts: wheat 200K, maize 19K, sorghum 102.7K, rice 31K; total 352.7K — [PMC10632488](https://pmc.ncbi.nlm.nih.gov/articles/PMC10632488/)
- How GrainSet was captured:
  - Custom device with a vibration belt and two industrial cameras (5480×3648) above and below a transparent plate
  - Shadow-free circular lighting at about 860 dpi
  - Each kernel is cropped and has an up and a down view
  — [PMC10632488](https://pmc.ncbi.nlm.nih.gov/articles/PMC10632488/)
- GrainSet downloads (CC BY 4.0, Figshare):
  - [sorghum](https://doi.org/10.6084/m9.figshare.22988981.v2)
  - [maize](https://doi.org/10.6084/m9.figshare.22987562.v2)
  - [wheat](https://doi.org/10.6084/m9.figshare.22992317.v2)
  - [rice](https://doi.org/10.6084/m9.figshare.22987292.v3)
  - Code and models: [github.com/GrainSpace/GrainSet](https://github.com/GrainSpace/GrainSet)
  — [PMC10632488](https://pmc.ncbi.nlm.nih.gov/articles/PMC10632488/)
- GrainSet's benchmark is within-species damage/quality classification (8 categories), not species ID. Sorghum scored 96.1% accuracy / 94.0 F1. — [PMC10632488](https://pmc.ncbi.nlm.nih.gov/articles/PMC10632488/)
- GrainSpace (CVPR 2022): 5.25M images of wheat, maize and rice; no sorghum or millet — [arXiv 2203.05306](https://ar5iv.labs.arxiv.org/html/2203.05306) (search snippet only)

### Inferences
- A model trained on GrainSet kernels will not transfer directly to phone photos of a handful of grain on a palm or table. Plan for heavy augmentation (backgrounds, blur, multi-kernel composites) or for collecting phone grain photos.
- Pearl and finger millet grain negatives are missing from open data and must be collected.

### Gaps
- I found no open millet grain or seed image dataset.
- I found no study of species-level classification (sorghum vs. maize vs. millet kernels) from phone photos.

## 4. Panicle/head datasets (sorghum positives)

### Takeaway
UQ's Sorghum Panicle Detection Ground-UAV dataset is CC BY 4.0, with box annotations from a 1.5 m ground camera and a 20 m UAV. These images are top-down canopy views, which makes them useful as panicle positives only if cropped.

### Cited Findings
- UQ Sorghum Panicle Detection Ground-UAV Dataset:
  - Ground subset: OAK-1 camera about 1.5 m above the canopy, 2160×2160
  - UAV subset: DJI Matrice 300 at 20 m, 8192×3040, GSD 0.25 cm/px
  - Bounding boxes for both subsets; image count not stated
  - CC-BY 4.0, open access
  - DOI [10.48610/9c3dd16](http://dx.doi.org/10.48610/9c3dd16); paper James et al. 2023, Plant Phenomics, [doi 10.34133/plantphenomics.0017](https://doi.org/10.34133/plantphenomics.0017)
  — [Research Data Australia](https://researchdata.edu.au/sorghum-panicle-detection-uav-dataset/3367794)
- UQ also lists a "Sorghum diversity head counting dataset" (Diffusion Fields subset; UAV, Gatton). — [Research Data Australia](https://researchdata.edu.au/sorghum-diversity-head-counting-dataset/4011317) (search snippet only)
- Purdue UAV sorghum panicle work: semi-supervised detection with 10% of labels ([arXiv 2305.09810](https://arxiv.org/pdf/2305.09810)) and GAN-synthesised UAV panicle images ([CVPRW 2022](https://openaccess.thecvf.com/content/CVPR2022W/AgriVision/papers/Cai_High-Resolution_UAV_Image_Generation_for_Sorghum_Panicle_Detection_CVPRW_2022_paper.pdf)). No public download was confirmed (search snippet only).
- Sorghum panicle detection and counting from UAS imagery with deep learning. — [PMC7492560](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7492560/) (search snippet only)

### Inferences
- Crop around the boxes to get thousands of panicle patches as positives. The top-down view and low resolution (UAV) differ from side-on phone shots, so mix them with iNat panicle photos.

### Gaps
- I did not obtain image or box counts for the UQ dataset.
- I did not check the Global Wheat Head Dataset as a negative source.

## 5. Pretrained models with sorghum in their label set

### Takeaway
BioCLIP 2 (MIT, ViT-L/14, trained on about 214M images / 952K taxa) can zero-shot "Sorghum bicolor" against look-alikes and is a good teacher or pseudo-labeller. It is too large for a phone, so distil it into MobileNetV3-Small. The PlantNet-300K ResNet18 weights are small, but I could not confirm that sorghum is among their classes or what licence they carry.

### Cited Findings
- BioCLIP 2 (imageomics/bioclip-2):
  - MIT licence tag; base model is CLIP pre-trained on LAION-2B
  - ViT-L/14 image encoder
  - Trained on TreeOfLife-200M (about 214M images, 952K taxa)
  - Zero-shot classification "provided the species names"
  - Reports 96.8 on PlantNet and 25.1 on PlantVillage
  — [HF model card](https://huggingface.co/imageomics/bioclip-2)
- BioCLIP 2 code is MIT ([GitHub](https://github.com/Imageomics/bioclip-2)). A newer "BioCLIP 2.5 Huge" uses an expanded TreeOfLife-200M (+19M images). — [Imageomics](https://imageomics.osu.edu/imageomics-foundation-model) (search snippet only)
- PlantNet-300K pretrained weights (ResNet18 named; others may exist) are at [lab.plantnet.org seafile](https://lab.plantnet.org/seafile/d/01ab6658dad6447c95ae/); no weight licence is stated. — [GitHub](https://github.com/plantnet/PlantNet-300K)

### Inferences
- Recommended pipeline:
  1. Use BioCLIP 2 zero-shot with prompts for Sorghum bicolor, Zea mays, Cenchrus americanus, Eleusine coracana, Saccharum officinarum, Sorghum halepense and S. × drummondii to filter and pseudo-label iNat/GBIF photos.
  2. Train or distil a MobileNetV3-Small binary head on the result.
- The MIT licence permits commercial use. The LAION-2B base and image licences in the training data may still raise provenance questions.

### Gaps
- I could not open the Pl@ntNet API terms, quota or commercial terms; the docs page returned navigation only. I found no evidence of an offline or on-device Pl@ntNet model.
- I did not verify the iNaturalist/Seek on-device model licence or label list; it is not openly licensed as far as I know (unverified).
- I did not search Hugging Face/Kaggle for crop-specific "sorghum vs. maize" checkpoints.

## 6. Papers classifying sorghum vs. other crops from images

### Takeaway
I found no paper that directly classifies sorghum plants against maize or millet from RGB photos. The closest work is sorghum vs. weeds (SorghumWeedDataset), within-sorghum seed variety ID, and sorghum-to-maize transfer for organ segmentation.

### Cited Findings
- Sorghum seed variety ID (8 varieties, 12,800 seeds, RGB plus hyperspectral fusion): CBAM-ResNet50-DSC reached 94.84% accuracy. — [PMC12412220](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12412220/) (search snippet only)
- Sorghum crop classification/segmentation with a Swin transformer plus YOLOv9 localisation. — [PMC12500700](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12500700/) (search snippet only; accuracy not obtained)
- Frontiers in Plant Science 2025 (sorghum-related): EfficientNet-B3 reached 86.97% on a sorghum disease classification task. — [Frontiers 10.3389/fpls.2025.1632698](https://www.frontiersin.org/journals/plant-science/articles/10.3389/fpls.2025.1632698/full) (search snippet only)
- Sorghum-trained organ segmentation transferred well to maize leaves and stalks but poorly to maize reproductive organs. — [NSF PAR 10529619](https://par.nsf.gov/biblio/10529619) (search snippet only)
- GrainSet within-species kernel quality: sorghum 96.1% accuracy (Section 3). — [PMC10632488](https://pmc.ncbi.nlm.nih.gov/articles/PMC10632488/)

### Inferences
- Because sorghum and maize leaves and stalks look alike to models (transfer works), panicle and inflorescence views are the most discriminative cue against maize. The app could prompt users to photograph the head when the plant is at heading stage.

### Gaps
- No accuracy figure was found for sorghum vs. maize/millet/sugarcane/Johnson grass classification. This is an open gap; the team's own validation set will be the benchmark.
- I did not open the SorghumWeedDataset baseline accuracies.
