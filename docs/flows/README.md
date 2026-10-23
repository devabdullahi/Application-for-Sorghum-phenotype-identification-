# Interaction flows

One Mermaid file per flow. Each file starts with a `%% Status:` line: **built** (in code
today), **written** (code exists but is not run or wired in yet) or **target** (design only,
from [ARCHITECTURE.md](../architecture/ARCHITECTURE.md)).

GitHub does not render standalone `.mermaid` files. To view one, paste it into
<https://mermaid.live>, or use the Mermaid preview in VS Code or Android Studio.

| File | Flow | Status |
|---|---|---|
| [01-system-overview](01-system-overview.mermaid) | Modules and dependency direction: Android app, `shared/`, `model/` | partly built |
| [02-live-guidance](02-live-guidance.mermaid) | Camera frame + tilt reading become one on-screen instruction | built |
| [03-guidance-decision](03-guidance-decision.mermaid) | Priority order: level, then sample, then 800 ms hold | built |
| [04-capture-and-quality-check](04-capture-and-quality-check.mermaid) | Take photo, crop, check at 640 px, accept or reject | built |
| [05-capture-state-machine](05-capture-state-machine.mermaid) | `CaptureState` transitions in `shared/session` | built |
| [06-species-gate](06-species-gate.mermaid) | "Is it sorghum?" through the `ImageModel` port and LiteRT | target (model side written) |
| [07-model-training-pipeline](07-model-training-pipeline.mermaid) | `model/`: photos to `traits-vN.tflite` + metadata + fixtures | written |
| [08-identification-target](08-identification-target.mermaid) | Full path from photo to cultivar result | target |
| [09-trait-correction](09-trait-correction.mermaid) | User corrects a trait; only reasoning re-runs | target |
| [10-failure-paths](10-failure-paths.mermaid) | What the app does when each step fails | partly built |
| [11-team-workflow](11-team-workflow.mermaid) | Branches, worktrees and PRs for parallel work | in use |

When a flow changes in code, update its file and its status line in the same PR.
