# Testing

This page maps every test suite and how to run it.

## Python unit tests (host-independent)

```bash
uv run python -m unittest discover -s tests
```

Coverage includes:

- reconciliation planner and the reference applier (`native_model.py`)
- lowering, precedence, edges
- protocol validation, events, motion
- commit coordinator, publication faults, revision receipts
- state journal, async callbacks (matrix), scheduler caveats
- direct transport, native bridge
- CLI: config, generation transaction, project identity
- extensions: registry, lowering, protocol, bootstrap, notification
- Material: callbacks, colors, dates, selection, slider model, disabled
  matrix
- Canvas and Path contracts, static draw geometry
- schema coverage, value spec validation
- element immutability, occurrence refs, component keys
- launch, bootstrap context
- showcase app (`examples/app.py`)

## Kotlin JVM tests

```bash
cd android && ./gradlew :host:testDebugUnitTest \
  -Pvyne.extensionKotlinDirs=../../extensions/second_surface/android
```

The checked-in `ExtensionRegistrant.kt` references the checkout's
extensions, so their Kotlin source dirs must be on the compile path
(colon-separated if more than one).

Coverage includes:

- preflight and transaction rollback (RendererTransactionTest,
  RenderTransactionApplierTest)
- mechanical digest (StaticDrawMechanicsTest)
- BridgeWorkScheduler, order-preserving event queue, callback admission
- PointerSession, EventBindings, OutlineStrategy
- PresentationEngine, renderer animation units, corner radii
- ElementRegistry extensions, accessibility semantics
- TextInput focus

The presentation engine takes its frame clock as a constructor parameter,
so JVM tests drive frames deterministically.

## Instrumentation tests (emulator)

Device tests use a dedicated packaged Python app and cover the real
Python-to-Kotlin bridge: commits, callbacks in both directions, renderer
properties, native input, keyed moves, lifecycle shutdown, and async
work.

```bash
adb devices
python scripts/run_emulator_tests.py                     # requires a running emulator
python scripts/run_emulator_tests.py --serial emulator-5554
```

Rules:

- Vyne deliberately does not create or delete an emulator
- physical-device serials are rejected unless `--allow-physical` is
  passed
- machine-readable evidence is written to
  `build/emulator-test-results.json`

Suites: FrameworkAcceptanceInstrumentationTest,
RendererInstrumentationTest, RendererSurfaceInstrumentationTest,
RendererExtensionInstrumentationTest, LaunchIntentAdapterInstrumentationTest,
NotificationEntryInstrumentationTest.

## Generated-project smoke

```bash
python scripts/run_generated_project_smoke.py --work-root /tmp/x --venv-root /tmp/y
```

Verifies the whole toolchain: wheel install -> `vyne new` -> gradle
assemble -> APK metadata -> extension build + generated wiring.

`scripts/run_generated_project_smoke.py` gates the packaged baseline.

## Showcase and benchmarks

- `examples/app.py` — Vyne Lab, the interactive showcase (Motion, Async,
  Style, Controls, Lists, and Material tabs). `test_showcase_app.py` renders
  the galleries and exercises list mutation.
- `benchmarks/bridge_benchmark_app.py` — bridge performance measurement
  (logcat `VYNE_BENCH` lines from `beginMeasurement`).

## Common test idioms

- Runtime tests use `MemoryTransport` with an attached runtime, which
  auto-acknowledges commits so the recovery state machine advances.
- `wait_for_async_callbacks()` settles scheduled async work in tests.

## Related

- [contributing/getting-started.md](../contributing/getting-started.md) — where to start
- [android-host/overview.md](../android-host/overview.md) — emulator setup
