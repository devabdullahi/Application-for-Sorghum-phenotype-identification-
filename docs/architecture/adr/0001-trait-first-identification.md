# ADR-0001: Identify cultivars from visible traits, not directly from photos

Status: Accepted (from design doc, 2026-10-03) · Date: 2026-10-19

## Context
The README's earlier plan was a MobileNetV3 classifier mapping a whole-plant photo straight to a cultivar. Prior work shows direct models degrade as classes grow (Sorghum-100: 78.8% over 100 cultivars on a field scanner) and need photos of every cultivar. Genebanks already describe cultivars by standard visible descriptors (IBPGR/ICRISAT 1993; UPOV TG/122), and Genesys holds those descriptors for 42,869 accessions.

## Options
1. **Direct photo → cultivar classifier.** Simple pipeline. Needs labelled photos per cultivar; no explanation; retrain to add a cultivar.
2. **Trait-first: photo → descriptor-state probabilities → naive Bayes over cultivars.** More components. Cultivars added as table rows; explains results; user can correct a trait.
3. Hybrid (direct classifier as an extra Bayes input). Possible later; adds a non-independent input.

## Decision
Option 2. Every trait outputs a probability distribution over its descriptor states. Reasoning is naive Bayes with tables from genebank data, a noise floor per state, and priors from region/user lists.

## Consequences
- Accuracy ceiling = how many cultivars share a visible profile; results may be groups.
- `reasoning` is independent of imaging and testable with plain numbers.
- Needs a calibrated, colour-corrected pipeline for measured traits (colour card).
- The README's direct-classifier section is superseded and should be updated.
