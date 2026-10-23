# PM backlog

Working list for the autonomous project-manager loop. The PM reads this file each iteration,
picks unblocked tasks, and updates it when a task changes state. Status history goes in
`docs/KEEP_UP.md`; design goes in `docs/architecture/`.

**Goal (2026-10-23):** (1) the app recognises sorghum with a trained species model;
(2) ARCHITECTURE.md step 6, first cultivar result on iPhone. iOS first, then Android.

## Lanes

| Lane | Owner | Branches / worktrees |
|---|---|---|
| ML: species model, `model/`, data on `/Volumes/LaCie/sorghum-model` | Peer session "cd" | `feature/model-species-head` (PR #1), `docs/keep-up` (PR #2) |
| PM, `shared/` step 6, iOS UI | PM session + agents | `pm/*`, `feature/<task>` in `../sorghum-<task>` |

Rules: one worktree per task off `origin/main`. The main disk has about 3 GB free, so at most
two agents build at once, and `build/` dirs are deleted after merge. Never touch the LaCie
venv or another lane's worktree.

## Tasks

| ID | Task | Lane | Depends on | Status |
|---|---|---|---|---|
| P1 | Rebase PR #1 / #2 onto main, merge | ML | — | cd rebasing |
| P2 | Download, train, export species model (`traits-v1.tflite/json`, fixtures). Bar: >=90% held-out, INT8 within 2 pts of float | ML | P1 | cd working |
| P3 | Bundle `traits-v1` in iOS, verify sorghum vs not-sorghum on simulator/device | iOS | P2 | blocked |
| S1 | `traits` core: catalogue (IBPGR/ICRISAT ids, states, photo type, method), `TraitEstimate` with floor | shared | — | in progress |
| S2 | `reasoning`: `CultivarTables` + JSON schema `cultivars-v1`, `CultivarTableSource` port, noise floor, naive Bayes, unrecognized/groups, explanation, correction recompute | shared | S1 | in progress (stacked on S1) |
| S3 | `calibration`: colour card find, affine colour fit to linear sRGB, px/mm | shared | — | in progress |
| S4 | `segmentation`: contrast mask vs plain board (panicle, grain); move `GreenCoverage` into `segmentation` | shared | — | todo |
| S5 | Measured trait readers (grain colour, glume colour, seed size, ...) | shared | S1 S3 S4 | todo |
| S6 | `SessionState` design (ADR) + session pipeline: quality, species, calibration, traits, reasoning, correctTrait | shared | S2 S5 | todo |
| S7 | iOS result screen + trait correction (renders `SessionState`) | iOS | S6 | todo |
| S8 | Genesys table builder in `model/` (needs API key: stub until user adds it) | ML | S2 | todo, ask cd |
| A1 | Android LiteRT runner + model bundling; check merged manifest for `INTERNET` | Android | P2 | todo (after iOS) |
| A2 | Android result screen | Android | S6 | todo (after iOS) |
| D1 | ARCHITECTURE §10: close the LiteRT iOS question (ADR-0007 chose CocoaPods) | PM | — | todo |

## Assumptions to confirm

Each one is also logged in `docs/KEEP_UP.md` as "ASSUMPTION — confirm".

- Species pass bar: >=90% held-out accuracy for sorghum vs not-sorghum, INT8 within 2 points of float.
- Licence policy widened to CC BY-NC / BY-NC-SA (non-commercial app, ARCHITECTURE §2).
