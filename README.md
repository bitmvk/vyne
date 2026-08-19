# Vyne

> ⚠️ **Alpha Release** — This is an early alpha release. APIs may change
> and features may be incomplete. Use at your own risk.

Framework for writing Android native UI in Python while keeping platform
runtime code thin.

```text
examples/app.py
-> vyne Python framework
-> Chaquopy-managed CPython
-> direct typed Kotlin transactions
-> native-view renderer
-> Android native views
```

Python owns components, state, reconciliation, event dispatch, and the ordered
native operation stream. Chaquopy owns Python initialization and Python/JVM
interop. Repeated mount and property operations use typed bulk calls so a
commit does not cross JNI once per operation.

## Quick Start

Python packages are managed with `uv`. From a framework checkout, install the
CLI in editable mode:

```sh
uv sync
uv run vyne doctor
```

Create and run a new app from anywhere by calling the checkout launcher:

```sh
./vyne new HelloApp
cd HelloApp
uv run vyne run
```

To initialize an existing `uv` project, run:

```sh
uv run vyne new .
```

An existing `pyproject.toml` is preserved and updated with a `vyne`
dependency if needed. Other generated files still refuse to overwrite unless
`--force` is passed.

If you are not already in the framework checkout, use the full path:

```sh
/path/to/vyne/vyne new HelloApp
```

The generated project contains:

```text
app.py                user app entry point
vyne.toml       app/package/build configuration
android/              generated Android Gradle host project
tests/                app-level Python tests
```

The reusable Android host base lives inside the `vyne` package.
`vyne new` records those package paths in `vyne.toml`, so creating a
project does not require an existing app project. A future release can add a
network-backed `vyne update` path to refresh that packaged base.

The Android Gradle build uses Chaquopy to package Python 3.14, so generated
projects do not need a separately downloaded CPython prefix.

Common app commands:

```sh
vyne doctor
vyne test
vyne build
vyne install
vyne run    # dev loop: R = full rebuild, r = hot reload (see docs/cli/live-reload.md)
```

The APK is written to:

```text
android/app/build/outputs/apk/debug/app-debug.apk
```

For the framework checkout showcase app, the APK is written to:

```text
android/host/build/outputs/apk/debug/host-debug.apk
```

When working directly inside this framework checkout, the same CLI also works
against the bundled showcase app:

```sh
./vyne doctor
./vyne build
```

After `uv sync`, the installed console script is also available:

```sh
uv run vyne test
uv run vyne build
uv run vyne run
```

## Project Layout

```text
packages/vyne/src/vyne/  Python framework API, runtime, diffing, events
packages/vyne/src/vyne/cli/
                                     project generator and build CLI
android/                             self-contained Android Gradle project
android/host/                        Android host Activity and native-view renderer
examples/app.py                      interactive framework showcase
tests/                               Python framework tests
```

The source tree keeps one canonical copy of the Android host. During wheel
builds, `setup.py` assembles it into
`vyne/base_project` so installed CLI projects can be created without a
framework checkout.

For developers and contributors, the developer documentation starts at
[`docs/README.md`](docs/README.md). It explains the framework's
principles, algorithms (reconciliation, commit coordination, recovery,
animation), threading model, and repository layout — one file per concern.

## Bundled Showcase

Running `uv run vyne run` from this checkout launches **Vyne Lab**. Its six
tabs exercise the framework as a real application:

- **Motion** — declarative multi-property animation, native springs, animated
  Canvas geometry and paint, imperative keyframes, cancellation, and async
  lifecycle callbacks.
- **Async** — ordered commits on both sides of `await`, responsive concurrent
  callbacks, out-of-order job completion, and native animation while Python is
  suspended.
- **Visuals** — direct visual props and structured `Decoration` values, strokes,
  independent corners, shadows, ripple state, and typography.
- **Controls** — controlled text input, checkbox, switch, chips, slider,
  progress, segmented buttons, and Material button variants.
- **Lists** — 30,000 static horizontal items plus 30,000 dynamic keyed rows
  with add, remove, and reverse operations, both on the generic virtual-list
  engine.
- **Material** — one live example of every public Material widget constructor,
  grouped into a scrollable catalog.

The root uses `safe_area=True`; native system insets are added to its explicit
padding and updated without a Python round trip. `safe_area` is available on
every primitive view, including leaf views.

## Current Scope

The Python framework currently exposes:

- `Box`
- `Canvas`
- `Column`
- `Text`
- `Row`
- `Image`
- `Layout`
- `Path`
- `Scroll`
- `TextInput`
- `List` (virtualized) with `ListController`
- `CornerRadius`
- `Decoration`
- `Fill`
- `Ripple`
- `Shadow`
- `Shape`
- `Stroke`
- `Animated`
- `animate`
- `component`
- `latest`
- `state`
- `run_app`
- `AppContext` with `AppState` and `BackHandler` (host capabilities)
- `LaunchData`
- `activity()` and `callback()` (application-owned Android escape hatch)
- `Ref` / `ViewHandle` (imperative access)

The complete Material 3 Expressive catalog is available from the separate
`vyne-material` distribution as the `vyne_material` import package. It
contains all 36 current component families, shared color/type/shape/motion
tokens, and controlled Python callbacks without adding Material-specific
renderer kinds. Install it with `uv add vyne-material` (or
`pip install vyne-material`). See
[`docs/material3-expressive.md`](docs/material3-expressive.md) for the
catalog and usage guide.

For a click effect or a one-off transition, animate the properties directly.
There is no animated value to declare first:

```python
from vyne import animate

def press(event):
    return animate(
        event.target,
        y=[-4, 0],
        scale=[0.96, 1.0],
        opacity=[0.8, 1.0],
        duration=90,  # per keyframe segment
        easing="ease_out",
    )
```

Named properties are the preferred API. `x`, `y`, `scale`, and `alpha` are
short aliases for `translation_x`, `translation_y`, both scale axes, and
`opacity`. Supplying several properties starts them together and returns one
group handle. The earlier positional form
`animate(ref, "opacity", to=1.0)` remains supported.

Use `Animated.Value` when one persistent timeline needs to drive multiple
properties, derived values, or both Views and Canvas:

```python
from vyne import Animated, Box, Canvas, component

@component
def Meter():
    progress = Animated.Value(0.0)
    pulse = Animated.Value(1.0)
    width = progress.interpolate([0, 1], [12, 240], extrapolate="clamp")
    opacity = progress.interpolate([0, 1], [0.35, 1.0])

    def fill():
        Animated.parallel(
            [
                Animated.timing(
                    progress,
                    to=1.0,
                    duration=420,
                    easing="ease_in_out",
                ),
                Animated.spring(pulse, to=[0.94, 1.0]),
            ]
        ).start()

    return Box(
        Box(
            width=width,
            height=12,
            opacity=opacity,
            scale_x=pulse,
            scale_y=pulse,
        ),
        Canvas(
            draw=[
                {
                    "kind": "circle",
                    "cx": width,
                    "cy": 24,
                    "r": 6,
                }
            ],
            on_click=fill,
        ),
    )
```

`Animated.timing()` and `Animated.spring()` create plans.
`Animated.parallel()` and `Animated.sequence()` compose them before
`.start()`. Arithmetic, `clamp()`, and `interpolate()` create derived
expressions evaluated on every native frame; a single driver can therefore
update many presentation slots without calling Python.

Imperative animation commands are ordered with the tree commit which created or
updated their target, but frames run entirely on the native display clock:

```python
handle = animate(
    ref,
    opacity=[0.4, 1.0],
    duration=120,  # per keyframe segment
    retarget="maintain_velocity",
    on_complete=lambda event: print(event.status),
)
```

One property returns an `AnimationHandle`; several properties return an
`AnimationGroupHandle`. Both are generation-safe. Calling `handle.cancel()`
from an event or render callback cannot cancel a newer replacement animation.
Completion and cancellation are delivered to Python as ordered lifecycle
events; async lifecycle callbacks are supported. Python is never called for
individual frames, so an already accepted animation continues while Python is
awaiting or temporarily busy.

Reusable stateful sections use the ``@component`` decorator:

```python
from vyne import Text, component, state

@component
def Counter():
    count = state(0)
    return Text(
        text=f"Count: {count.value}",
        on_click=lambda: count.set(count.value + 1),
    )
```

Components cache their output and only re-execute when state changes or
inputs differ.  Reconciliation always covers the full tree — component
boundaries are a performance optimisation, not an isolation boundary.
Component calls, `state()` hooks, and `Animated.Value()` hooks must keep a
stable order within their owning component.

Event and Android callbacks may also be declared with `async def`; they are
passed to widgets and `callback()` exactly like synchronous functions:

```python
async def load_profile():
    loading.set(True)
    profile = await fetch_profile()
    data.set(profile)
    loading.set(False)

Text("Load", on_click=load_profile)
```

State changes before an incomplete `await` are batched into one ordered
commit. Changes made when the callback resumes are batched into a later
commit, while other callbacks remain able to run.

Apps register their entry point with `run_app`:

```python
from vyne import run_app

def TodoApp():
    ...

run_app(TodoApp)
```

An app may instead accept one `AppContext` argument holding the immutable
Android launch data and host capabilities (such as app-state transitions):

```python
from vyne import AppContext, Text, run_app

def App(context: AppContext):
    route = context.launch.extras.get("route", "home")
    return Text(text=f"Route: {route}")

run_app(App)
```

The first Android `Intent` is supplied before the initial render. A later
`onNewIntent` delivery reruns the same root with a new `AppContext` while
preserving its state and runtime. Vyne projects the intent action, URI, and
bridge-safe extras; application manifest, notification, `PendingIntent`, and
launch-mode configuration remain owned by the application.

Application-owned Android code can use a deliberately small escape hatch:

```python
from com.example.device import DeviceHooks
from vyne import Column, Text, activity, callback, run_app, state

def App():
    status = state("waiting")
    subscription = state(None)

    def start_sensor():
        if subscription.value is not None:
            return
        readings = callback(
            lambda result: status.set(result["status"]),
            delivery="latest",
            sample_interval_ms=50,
        )
        subscription.set(readings)
        DeviceHooks.startSensor(activity(), readings)

    def stop_sensor():
        DeviceHooks.stopSensor(activity())
        if subscription.value is not None:
            subscription.value.dispose()
            subscription.set(None)

    return Column(
        Text(status.value),
        Text("Start", on_click=start_sensor),
        Text("Stop", on_click=stop_sensor),
    )

run_app(App)
```

The corresponding Kotlin API accepts Vyne's one-method callback:

```kotlin
import android.app.Activity
import dev.vyne.VyneCallback

object DeviceHooks {
    @JvmStatic
    fun startSensor(activity: Activity, readings: VyneCallback) {
        Thread {
            val result = mapOf("status" to "ready")
            readings.invoke(result)
        }.start()
    }
}
```

`activity()` returns the current host `Activity`. `callback(fn)` returns a
`VyneCallback` whose `invoke(payload)` may be called from any Android thread;
Vyne converts bridge-safe mappings and sequences to Python values, then
`Runtime.dispatch_external_callbacks` runs the active subscriptions as one
state-journalled render batch on the single-owner asyncio runtime. Both
synchronous and asynchronous callbacks are supported. `delivery="all"`
preserves every queued value, while `delivery="latest"` bounds a backed-up
subscription to its newest value. `sample_interval_ms` mechanically limits
how often values enter the queue.

Call `readings.dispose()` when the Android producer is stopped. Disposal is
ordered through the same executor, removes queued values, and releases the
Python callable; runtime shutdown also disposes every remaining subscription.
The application remains responsible for its Kotlin source, dependencies,
manifest declarations, permissions, producer shutdown, and Android lifecycle
cleanup. These primitives do not add an extension registry or a second
framework lifecycle.

Visual properties are passed directly to elements:

```python
from vyne import Text

Text(
    "Todo List",
    text_color="#172554",
    font_size=24,
)
```

Reusable visual conventions can be expressed as components or prop mappings:

```python
title_props = {"text_color": "#172554", "font_size": 24}
Text(text="Title", **title_props)
```

Decorations provide native drawable-backed visual chrome:

```python
from vyne import Decoration, Ripple, Shadow, Stroke, Text

Text(
    "Card",
    padding=12,
    decoration=Decoration.rectangle(
        fill="#ffffff",
        stroke=Stroke(color="#e5e7eb", width=1),
        corners=8,
        shadow=Shadow(elevation=2),
        ripple=Ripple(color="#22000000"),
    ),
)
```

The first decoration tier maps to Android shape drawables, ripples, elevation,
and outline clipping.

The renderer applies Python-generated patch operations after the first mount,
so typing in a native text field updates only the changed property instead of
recreating the UI tree on every keystroke. Production Android traffic uses
typed direct calls, with semantic batching for initial mounts and repeated
property updates.

## Runtime Notes

The framework configures Chaquopy Python 3.14 for `arm64-v8a` devices and
`x86_64` emulators. Generated projects store package/base-project paths in
`vyne.toml` and use them for the Android host sources and Python package.

## Testing

Run the complete host-independent suite with:

```bash
uv run python -m unittest discover -s tests
```

Device tests use a dedicated packaged Python app and cover the actual
Python-to-Kotlin bridge, commits, callbacks in both directions, renderer
properties, native input, keyed moves, lifecycle shutdown, and async work.
The tester starts an emulator first; Vyne deliberately does not create or
delete one:

```bash
adb devices
python scripts/run_emulator_tests.py
```

When more than one device is online, pass `--serial emulator-5554`. The
runner rejects physical-device serials unless `--allow-physical` is supplied
and writes machine-readable evidence to
`build/emulator-test-results.json`.
