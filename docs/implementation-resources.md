# Vyne Implementation — Resources & Constraints (REFER TO THIS FILE)

This file records the locked implementation decisions and the current
verification evidence. Do not re-litigate the locked decisions without a
design discussion first.

## Verification evidence (current)

- Python unit tests: 1531 passed
  (`uv run python -m unittest discover -s tests`)
- Kotlin JVM: 181 passed
  (`cd android && ./gradlew :host:testDebugUnitTest` — see below for the
  extension-dir property)
- Instrumentation on emulator-5554 (API 35): 90/90
  (`scripts/run_emulator_tests.py`; evidence in
  `build/emulator-test-results.json`)
- Generated-project smoke: `scripts/run_generated_project_smoke.py` (10
  gates)
- Docs acceptance: `tests/test_acceptance_docs.py`

## Emulator / testing

- Emulator: emulator-5554 (API 35). Physical phone: Vivo V2413 (API 36) —
  serial starts with `adb-10BF3U0EFZ0032H-`; target it with
  `ANDROID_SERIAL`.
- adb at `/opt/android-sdk/platform-tools`. `GRADLE_USER_HOME=/tmp/gradle-home`.
- Python: `uv run python -m unittest discover -s tests`.
- JVM: `cd android && ./gradlew :host:testDebugUnitTest
  -Pvyne.extensionKotlinDirs=../../extensions/second_surface/android`.
  The checked-in `ExtensionRegistrant.kt` references the checkout's
  extensions, so their Kotlin source dirs must be on the compile path.
- Instrumentation: `scripts/run_emulator_tests.py --serial ...` (the
  runner discovers and passes the extension dirs itself).

## Plan sources

- `docs/extensions.md` — the extension guide (contract: Kotlin
  `ElementSpec` is the single source of truth; Python host-query;
  `pre_launch` is app-composed).
- `agent.md` — Python owns framework logic; correct models over
  special-case patches.

## Decisions locked (do not re-litigate)

1. No pip/uv — extensions are dev-written folders under `extensions/`.
2. No Python-side registration — host query; no automatic launch wiring.
3. At-most-once delivery; extension/app-owned durability pattern.
4. Sync-only `pre_launch`; extension props not animatable.
5. Notification `PendingIntent` is app/extension-owned (`entryKey` in
   data URI).
6. Extension listeners share one `ListenerRecord` model; one handler per
   prop (null = removal); origin derived from the session sequence.
