# The CLI

Source: `vyne/cli/` (main.py, new.py, project.py, config.py, android.py,
doctor.py, dependencies.py, extension_new.py).

The CLI is the developer-facing tool for creating, building, and running
Vyne apps on Android.

## Commands

| command | purpose |
|---|---|
| `vyne new <name>` | scaffold a new project directory |
| `vyne new .` | initialize an existing uv project |
| `vyne doctor` | check build prerequisites |
| `vyne build` | assemble the APK via Gradle |
| `vyne install` | build + adb install |
| `vyne run` | build + install + launch |
| `vyne launch` | launch an already-installed app |
| `vyne test` | run local Python unit tests |
| `vyne extension new <name>` | scaffold an extension |

## Quick start

```bash
uv sync
uv run vyne doctor
./vyne new HelloApp
cd HelloApp
uv run vyne run
```

`./vyne` is the checkout launcher: it sets `PYTHONPATH` to the framework
source and runs `python3 -m vyne.cli.main`. After `uv sync`, the installed
console script `vyne` is also available.

## Generated project

`vyne new` creates:

```text
app.py                user app entry point
vyne.toml       app/package/build configuration
android/              generated Android Gradle host project
tests/                app-level Python tests
```

- an existing `pyproject.toml` is preserved and updated with a `vyne`
  dependency if needed
- generated files refuse to overwrite unless `--force` is passed
- the Android Gradle build uses Chaquopy to package Python 3.14, so
  generated projects need no separately downloaded CPython prefix
- `vyne.toml` records the packaged base-project paths, so creating a
  project does not require a framework checkout

The APK is written to
`android/app/build/outputs/apk/debug/app-debug.apk` (generated project)
or `android/host/build/outputs/apk/debug/host-debug.apk` (framework
checkout).

## Config

`vyne/cli/config.py` reads `vyne.toml`:

- app/package/build configuration
- framework root and packaged base-project paths
- extension discovery

## Doctor

`vyne doctor` verifies prerequisites:

- toolchain availability (uv, Gradle, Android SDK, adb)
- project structure and configuration
- extension validity

## Dependencies

`vyne/cli/dependencies.py` manages the `vyne` dependency entry in a
project's `pyproject.toml` (add/update/remove), keeping the project
self-contained.

## Related

- [generation.md](generation.md) — how scaffolding works
- [testing.md](../testing/testing.md) — what `vyne test` runs
- [../extensions/extensions.md](../extensions/extensions.md) — extension commands
