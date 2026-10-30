# ADR-0013: The type goal is five basic races, scored per accession on a sealed phone test

Status: Accepted · Date: 2026-10-30 · Amends: [ADR-0011](0011-cultivar-accuracy-target.md) ·
Protocol: [type-evaluation-protocol.md](../type-evaluation-protocol.md) (`type-eval-v1`)

## Context
ADR-0011 defined "89% sorghum type accuracy" as group-aware accuracy over the fifteen races,
with coverage, and left open which taxonomy the product owner means. What happened since:

- On 2026-10-30 the product owner decided (#51): **type = the five basic races** (Bicolor,
  Guinea, Caudatum, Kafir, Durra). Intermediates are reported separately and are not part of
  the gate. Exact cultivar and use type are out of scope for the goal.
- race-v1 (fifteen races) scored 0.768 selective at 0.797 coverage on GRIN test photos.
  basic-race-v1 scored 0.965 at 0.793 (`model/README.md`). Both were scored per photo, on GRIN
  studio photos, with a test split that has since been seen.
- GRIN race labels were checked against the Frontiers 2023 race panel (T24,
  `model/manifests/race-crosswalk-frontiers-summary.txt`). On 58 shared accessions the two agree
  exactly on 0.40 [0.28, 0.53]. Where both name a basic race they agree on 0.79 [0.62, 0.90].
  Every mismatch rests on a single GRIN observation.
- No phone test set exists. One will be collected from requested seed (T26).

## Options
1. **Keep the per-photo GRIN evaluation as the gate.** It already exists, but it measures studio
   photos, its test split has been seen, and an accession with four photos counts four times.
2. **Accession-level, five basic races, on a sealed phone set collected with the app.** Measures
   what the app does for its users. Needs seed, a custodian and a frozen protocol.
3. **Option 2, but scored over the fifteen races.** The product owner ruled this out.

## Decision
Option 2, frozen as `type-eval-v1`:

- **Type accuracy** (headline) = correct / all test accessions, with the true basic race in the
  returned group of at most two races. "Unrecognized" counts as not correct.
- **Gate** (`RaceGateSettings`, now applied per accession): selective accuracy >= 0.89 **and**
  coverage >= 0.80, +0.10 over the majority baseline, INT8 within 0.02 of float. A pass
  therefore implies type accuracy >= 0.712. Selective accuracy is gated, not type accuracy:
  type accuracy can never exceed coverage, so a gate on it at 0.89 would make the 80% coverage
  floor meaningless.
- **Accession answer** = mean of the per-photo calibrated probabilities, then the group rule.
  An accession with no scorable photo is "unrecognized".
- **Per-race** results with Wilson 95% intervals are always published. There is no per-race floor
  in v1, because 50 accessions per race give intervals of about +-0.09.
- **Intermediate side report**, never gating: answered share, parent-in-group, both-parents.
- **Sealed test:** assignment committed before photography (salt hash, then draw), a custodian
  who does not train models, test photos hashed and held apart, the model frozen and hashed, one
  scoring. A new model version needs a new sealed set.
- **Photos:** panicle (two plants), grain and glume views on a grey board with a ColorChecker
  Classic Mini and a mm ruler. A leaf view is optional (it carries no race character, but it
  feeds cultivar traits and the species gate).
- **Labels:** GRIN-consistent and not contradicted by any second source (Frontiers now, Genesys
  when available). A **test** accession also needs a confirmed label: two GRIN plantings agree, a
  second source agrees, or a race specialist names the race from the grown plants without seeing
  the GRIN label. A one-curator label is right only about four times in five (T24). That is too
  noisy to measure 89%.

## Consequences
- basic-race-v1's 0.965 is not a result under this protocol: it is per photo, on studio photos,
  on a seen split. It stays a research result.
- The goal cannot be claimed until seed is obtained (T26), photographed with the app, and scored
  once by the custodian.
- Per-race weakness (Kafir, Bicolor and Guinea recall in basic-race-v1) is visible in every
  report, but it does not block the gate. If the product needs a guarantee per race, version 2
  must add floors and more test accessions per race.
- The label agreement measured in T24 caps every accuracy number on these labels and is quoted
  with them.
