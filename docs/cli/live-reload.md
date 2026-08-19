# Dev loop and hot reload

`vyne run` stays alive after the first build/install/launch and drives the
iteration loop from the keyboard — no rebuild for Python edits.

```text
vyne run
  R  rebuild: Gradle build + install + relaunch  (native/framework changes)
  r  hot reload: swap the app's Python, no rebuild
  q  quit
```

`vyne run --once` keeps the old behavior: build/install/launch and exit
(handy for CI and scripts).

## How hot reload works

The app on the device is a normal host APK; live mode is a runtime
capability (`vyne/live.py`) packed with the framework.

- On `r`, the CLI stages the app's Python (the directory containing the
  app source file, plus extension `python/` trees) on the device via adb,
  copies it into the app's private files dir (`run-as`), and bumps a `REV`
  marker.
- The packaged `vyne.live` watcher sees the `REV` change and asks the host
  Activity to recreate itself; the recreated session re-imports the pushed
  Python and mounts it on the same live Renderer.

`vyne.live.install()` runs at the top of `start_direct`, before the app
module is imported. It only acts when the device carries an `ENABLED`
marker inside `<filesDir>/vyne-live`, so normal debug and release builds
are unchanged. When armed it:

1. puts `<filesDir>/vyne-live` at the front of `sys.path` — `import app`
   resolves to the pushed copy, not the frozen APK one;
2. evicts the already-imported swappable modules from `sys.modules`, so
   re-import is a true re-read of the new files;
3. starts a watcher thread that, on a `REV` change, requests the Activity
   recreate.

## First activation

The first `r` arms live mode: it pushes the sources, then force-stops and
relaunches the app so the loader picks up the `ENABLED` marker. Every later
`r` swaps in place without a restart.

## What swaps — and what does not

- **Swappable (`r`):** the app's own Python and extension `python/` trees —
  the UI layer.
- **Needs `R`:** the `vyne` framework itself, Material, and everything
  Kotlin/native (host, extensions' Kotlin, resources). Same boundary as
  React Native native modules needing a dev-client rebuild.

State is **not** preserved across a hot reload — the swap is a full
re-mount of the Python session (reconciliation starts from empty), so
in-memory app state resets. This is "rapid reload," intentionally: a
state-preserving hot swap is a later milestone.

## Failure behavior

A broken edit reloads to a broken app: `start_direct` fails, the host shows
the startup error screen, and the previously shown tree is gone (the
Activity already recreated). The loader itself never blocks startup — every
live-path failure is caught and degraded to running the frozen code.

## Notes

- Pushed files live in the app's private files dir (written via `run-as`,
  so the APK must be debuggable — all debug builds are). Uninstalling the
  app removes all pushed state.
- Only the main activity session is reloadable in v1; surface sessions
  (`second_surface`) are not.
- No backend is involved — this is purely the on-device UI + Python layer.
