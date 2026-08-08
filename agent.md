# Agent Notes

## The Framework is on the python side.

Treat this project as if the whole framework is on the python side. the kotlin side(native android side) is only to be used as the rendered.
Only use it if python doesn't solve the issue faced, and if python is not enough.
Strongly stear away from having framework logic on the kotlin side.
The conceptual ideal architecture is, kotlin providing the basic tools for python, and python doing all of the hardlifting, and make the final required setup.


## Prefer Correct Models Over Special-Case Patches

Do not patch existing logic just to make one observed case work. If a fix starts to add
special cases, duplicate state, or separate code paths for create/update/remove behavior,
stop and revisit the underlying model.

For this codebase, repeated patches are a signal that the algorithm is wrong or incomplete.
Rewrite or consolidate the logic so the same mechanism handles the full lifecycle:
initial creation, updates, removals, reordering, and future extensions.

Before editing, ask:

- Is this fixing the root model, or only the current symptom?
- Will the same path handle initial render and later updates?
- Will removal/reset go through the same logic?
- Are related props represented in one coherent state model?
- Can this avoid future one-off fixes for nearby cases?

Small local edits are fine for genuinely local bugs. But when behavior depends on lifecycle,
layout, synchronization, styling, or renderer state, prefer a proper redesign of the logic
over incremental patching.
