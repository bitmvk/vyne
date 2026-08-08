# Glossary

| term | meaning |
|---|---|
| accepted | the last exactly acknowledged snapshot; read-only for planning |
| acknowledgement | a native-reported value for a controlled prop (e.g. the text a user typed) |
| ack map | (node, prop) -> native value; suppresses equal `set_prop` echoes |
| animation-only commit | a commit containing only motion ops, no tree changes |
| apply result | native answer to a commit: ok / rejected_known / verified_rollback / partial / unknown |
| bridge-safe | values that can cross the Python/Kotlin boundary: scalars, string-key mappings, sequences; no cycles, no NaN |
| candidate | a staged render, not yet sent or promoted |
| canonical key | a string, non-bool int, or tuple of those; element keys are validated against this domain |
| CanonicalElement | lowered, validated, frozen element with flat props |
| commit | revision + ordered ops, Python -> native |
| component | a `@component`-decorated function with isolated hooks and cached output |
| controlled component | a Material component whose value lives in Python state |
| controlled prop | a prop whose native value is reported back by an event (text, has_focus, range value) |
| digest | mechanical native-tree fingerprint compared before/after apply |
| direct transport | typed Chaquopy calls; no message envelope or codec |
| driver | a persistent numeric value (`Animated.Value`) animated natively; bound expressions read it each frame |
| Element | immutable public UI node (kind + props + children), no runtime identity |
| event batch | a group of native events dispatched together, producing one commit |
| gesture id | per down-up pointer session id; key for `latest` coalescing |
| handler id | registry id for one event callback; stable across renders while a listener stays installed |
| in-flight | a revision sent, awaiting the native receipt |
| intent binding | binding refs and event handlers to a planned tree |
| journal | per-flush record of state writes, rolled back on failure |
| keyed matching | O(1) reconciliation match by (key, kind) |
| latest | delivery policy that coalesces queued events by key |
| lowering | Element -> CanonicalElement: validate, merge layers, freeze |
| node id | monotonic integer identity of one RenderNode / native view |
| op | one operation in a commit (create, set_prop, insert_child, ...) |
| pass guard | bounded render-pass counter (5 per flush) |
| preflight | native validation of every op before any mutation |
| PropMemento | accepted-prop record: presence, wire value, live presentation values |
| receipt | system event carrying an apply result + revision + session |
| recovery state | SYNCED / AWAITING_APPLY / NEEDS_RESET / FAULTED / DISPOSED |
| reconcile | diff the accepted snapshot against the desired canonical tree |
| ref | Python handle to a mounted view (Ref / ViewHandle) |
| RenderNode | runtime mirror of one native view |
| RenderSnapshot | full tree state at one revision |
| revision | monotonic commit number |
| shadow list | mutable native-order child list used for correct op indices |
| slot | stable identity of one animatable presentation value (view prop or canvas field) |
| snapshot commit | clear + full rebuild of the native tree (used on NEEDS_RESET) |
| State cell | one `state()` hook result, matched by index |
| StateHost | the narrow interface binding a cell to its owning Runtime |
| transport | the delivery layer for logical messages |
| tween | fixed-duration interpolation with a named easing |
| spring | damped harmonic oscillator with stiffness and damping ratio |
