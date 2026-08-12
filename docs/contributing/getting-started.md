# First-Time Contributor: Getting Started

## Setup

```bash
# 1. Install dependencies and the CLI (editable)
uv sync
uv run vyne doctor

# 2. Run the Python test suite
uv run python -m unittest discover -s tests

# 3. Build the showcase APK
./vyne build        # APK at android/host/build/outputs/apk/debug/host-debug.apk

# 4. Run Vyne Lab on an emulator
./vyne run
```

## Reading order

1. [README.md](../../README.md) — public API and quick start.
2. [concepts/principles.md](../concepts/principles.md) — the core
   principle.
3. [concepts/data-flow.md](../concepts/data-flow.md) — how a render moves
   through the stack.
4. [concepts/core-model.md](../concepts/core-model.md) — the data types.
5. [framework/reconciliation.md](../framework/reconciliation.md) — the
   diffing algorithm (the heart of the framework).
6. [framework/runtime.md](../framework/runtime.md) — the orchestrator.
7. [framework/protocol.md](../framework/protocol.md) — the wire
   contract.
8. [android-host/renderer.md](../android-host/renderer.md) — the native
   applier.
9. [android-host/overview.md](../android-host/overview.md) — the
   threading boundary.
10. [design-rules.md](design-rules.md) — the invariants that protect the
    design.

## Where the code lives

| concern | files |
|---|---|
| public API | `vyne/__init__.py` |
| elements | `vyne/elements.py` |
| lowering | `vyne/lowering.py` |
| reconciliation | `vyne/reconcile.py` |
| protocol | `vyne/protocol.py` |
| runtime | `vyne/runtime.py` |
| state / scheduler | `vyne/state.py`, `vyne/scheduler.py` |
| recovery | `vyne/recovery.py` |
| transport | `vyne/transport.py`, `vyne/direct_transport.py` |
| animation | `vyne/animations.py`, `vyne/motion.py` |
| schema | `vyne/spec/schema_v2.py`, `vyne/spec/model.py` |
| element typing | `vyne/elements.pyi` (generated) |
| material | `packages/vyne-material/src/vyne_material/` |
| native host | `android/host/src/main/java/dev/vyne/` |
| CLI | `vyne/cli/` |

## Common tasks

### Add a prop

1. Add a `PropSpec` in `vyne/spec/schema_v2.py` (value domain, default,
   `applies_to`, `animatable`, `drop_default`).
2. Regenerate `ElementContracts.kt` with `tools/generate_schema.py`.
3. Regenerate the Python typing stubs with
   `uv run python scripts/generate_schema_stubs.py` (add `--check` in CI).
4. Add the set/reset entries in `PropertyApplicators.kt` (generic props)
   or in the widget's `ElementSpec` in `NativeWidgets.kt`.
5. Add tests: lowering validation, wire round trip, renderer apply.

### Add a primitive kind

1. Extend `PRIMITIVE_KINDS` in `vyne/spec/schema_v2.py`.
2. Register the View factory in `NativeWidgets.kt`.
3. Regenerate the contracts.
4. Add tests: schema coverage, lowering, protocol, renderer.

### Change reconciliation

Edit `vyne/reconcile.py` and prove it with the reference applier
(`tests/support/native_model.py`). The planner must stay pure: no
IO, no transport, no accepted-state mutation.

### Add a Material component

Compose primitives in `packages/vyne-material/src/vyne_material/components.py`.
No Kotlin changes are needed. Components are controlled: Python owns the
value; callbacks receive the proposed next value.

### Add an extension

1. `vyne extension new <name>` scaffolds it.
2. Implement the Kotlin view and `ElementSpec` registration.
3. Provide the Python constructor module.
4. `vyne doctor` validates; `vyne build` regenerates the registrant.

### Change the protocol

Edit the validators in `vyne/protocol.py` and the matching Kotlin
preflight in `Renderer.kt`. Keep both sides in sync. Add protocol
validation tests and renderer preflight tests.

## Never do

- mutate the accepted snapshot during planning
- call `state.set()` during render (guard raises)
- add a Python-side extension registration (the host is the source of
  truth)
- send unbounded events without `latest()` coalescing
- let a failing handler clear the accepted tree (RE-1)
- silently ignore an unsupported prop (MODEL-02 — fail with a path)
- add per-frame Python work (frames are native-owned)

## Choosing what to run

| change | run |
|---|---|
| Python logic | `uv run python -m unittest discover -s tests` |
| Kotlin host | `cd android && ./gradlew :host:testDebugUnitTest -Pvyne.extensionKotlinDirs=../../extensions/second_surface/android` (the checked-in registrant references checkout extensions) |
| bridge / device | `scripts/run_emulator_tests.py` (needs a running emulator) |
| CLI / generation | Python suite + `scripts/run_generated_project_smoke.py` |

## Related

- [testing.md](../testing/testing.md) — the full test map
- [design-rules.md](design-rules.md) — invariants and codes
